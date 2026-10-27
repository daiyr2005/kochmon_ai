"""Платёжные провайдеры. Чтобы подключить свой банк или эквайринг, добавьте класс с теми же двумя методами."""
import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from mysite.config import Settings
from mysite.database.ai_models import Payment
from mysite.services.errors import ServiceError


@dataclass
class PaymentEvent:
    payment_id: int
    status: str                  # paid / failed
    provider_payment_id: str | None
    amount: Decimal | None
    currency: str | None
    event_id: str | None = None


class DevProvider:
    """Только для разработки: «оплата» подтверждается вызовом POST /payments/{id}/dev-pay."""
    name = "dev"
    supports_recurring = True   # «списание» имитируется, чтобы можно было проверить автопродление без банка

    def create_checkout(self, payment: Payment) -> str:
        return f"/api/payments/{payment.id}/dev-pay"

    async def charge_recurring(self, payment: Payment) -> str:
        return f"dev-recurring-{payment.id}"

    def parse_webhook(self, headers, body: bytes) -> PaymentEvent:
        raise ServiceError(404, "У провайдера dev нет webhook")


class GenericProvider:
    """Любая внешняя платёжка, которая шлёт webhook JSON с подписью HMAC-SHA256 в заголовке X-Signature.

    Ожидаемое тело: {"payment_id": 1, "status": "paid", "provider_payment_id": "abc", "amount": "299.00",
    "currency": "KGS"}. Если у вашей платёжки другой формат, поправьте parse_webhook."""
    name = "generic"
    # Автосписание с сохранённой карты зависит от конкретной платёжки (токен карты, отдельный запрос).
    # Здесь его нет: автопродление выставляет счёт со ссылкой на оплату. Если ваш банк умеет списывать
    # по токену, поставьте supports_recurring = True и реализуйте charge_recurring.
    supports_recurring = False

    def __init__(self, secret: str, checkout_url: str):
        self.secret = secret
        self.checkout_url = checkout_url

    def create_checkout(self, payment: Payment) -> str:
        return self.checkout_url.format(payment_id=payment.id, amount=payment.amount, currency=payment.currency)

    async def charge_recurring(self, payment: Payment) -> str:
        raise ServiceError(501, "Автосписание для этого провайдера не реализовано")

    def parse_webhook(self, headers, body: bytes) -> PaymentEvent:
        sent = headers.get("x-signature", "")
        wanted = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sent, wanted):
            raise ServiceError(403, "Неверная подпись")
        try:
            data = json.loads(body)
            amount = Decimal(str(data["amount"])) if data.get("amount") is not None else None
            return PaymentEvent(int(data["payment_id"]), str(data["status"]), data.get("provider_payment_id"),
                                amount, data.get("currency"), str(data.get("event_id") or ""))
        except (ValueError, KeyError, TypeError, InvalidOperation):
            raise ServiceError(400, "Некорректное тело webhook")


def build_provider(settings: Settings):
    if settings.payment_provider == "generic":
        if not (settings.payment_webhook_secret and settings.payment_checkout_url):
            raise RuntimeError("Для PAYMENT_PROVIDER=generic задайте PAYMENT_WEBHOOK_SECRET и PAYMENT_CHECKOUT_URL")
        return GenericProvider(settings.payment_webhook_secret, settings.payment_checkout_url)
    return DevProvider()
