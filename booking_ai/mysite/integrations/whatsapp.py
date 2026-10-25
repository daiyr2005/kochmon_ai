"""WhatsApp Business Cloud API (официальный API Meta): отправка сообщений и обработка входящих webhook.

Важные правила WhatsApp:
- Писать первыми можно только по одобренному шаблону. Свободный текст доходит, если человек писал нам
  в последние 24 часа. Для уведомлений вне этого окна задайте WHATSAPP_TEMPLATE_NAME (шаблон с одним параметром).
- Номер считается подписанным на уведомления, только когда человек сам привязал его кодом. Слово СТОП отключает рассылку."""
import hashlib
import hmac
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mysite.integrations.ollama import OllamaUnavailable
from mysite.database.ai_models import ChannelAccount
from mysite.integrations.telegram import claim_message, format_reply, link_account, linked_user, unlink_account
from mysite.agents.runtime import AIRuntime

# в лог httpx попадает полный URL запроса: глушим, чтобы не светить лишнего
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("booking_ai.whatsapp")

CHANNEL = "whatsapp"
MAX_TEXT = 2000
WA_LIMIT = 4000

HELP = ("Я помогаю искать объявления и присылаю уведомления по подпискам.\n"
        "Чтобы привязать этот номер, получите код в приложении и отправьте мне: /start КОД\n"
        "Отвязать: /unlink. Отключить уведомления: СТОП")


class WhatsAppError(RuntimeError):
    pass


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Meta подписывает тело запроса: заголовок X-Hub-Signature-256 = sha256=<hmac>."""
    if not header or not header.startswith("sha256="):
        return False
    wanted = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], wanted)


class WhatsAppClient:
    def __init__(self, access_token: str, phone_number_id: str, *, template_name: str | None = None,
                 template_lang: str = "ru", api_version: str = "v21.0",
                 transport: httpx.AsyncBaseTransport | None = None):
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._template = template_name
        self._lang = template_lang
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), transport=transport)

    async def _post(self, payload: dict[str, Any]) -> None:
        try:
            r = await self._http.post(self._url, json=payload, headers=self._headers)
        except httpx.HTTPError as e:
            raise WhatsAppError(f"WhatsApp API недоступен ({type(e).__name__})") from None
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
                text = f"{err.get('code')}: {err.get('message', 'ошибка')}"
            except ValueError:
                text = f"HTTP {r.status_code}"
            raise WhatsAppError(f"WhatsApp API: {text}")

    async def send_text(self, to: str, text: str) -> None:
        for i in range(0, max(len(text), 1), WA_LIMIT):
            await self._post({"messaging_product": "whatsapp", "to": to, "type": "text",
                              "text": {"body": text[i:i + WA_LIMIT] or "…"}})

    async def send_template(self, to: str, text: str) -> None:
        # в параметрах шаблона нельзя переносы строк, поэтому склеиваем строки разделителем
        flat = " | ".join(line.strip() for line in text.splitlines() if line.strip())[:1000]
        await self._post({"messaging_product": "whatsapp", "to": to, "type": "template",
                          "template": {"name": self._template, "language": {"code": self._lang},
                                       "components": [{"type": "body", "parameters": [{"type": "text", "text": flat}]}]}})

    async def send_notification(self, to: str, text: str) -> None:
        """Уведомление: по шаблону, если он настроен, иначе обычным текстом."""
        if self._template:
            await self.send_template(to, text)
        else:
            await self.send_text(to, text)

    async def aclose(self) -> None:
        await self._http.aclose()


def extract_messages(payload: dict) -> list[dict]:
    """Достаёт текстовые сообщения из тела webhook. Статусы доставки и прочее игнорируем."""
    found = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for msg in (change.get("value") or {}).get("messages") or []:
                if msg.get("type") == "text" and isinstance(msg.get("text", {}).get("body"), str) and msg.get("from"):
                    found.append({"id": msg.get("id"), "from": str(msg["from"]), "text": msg["text"]["body"]})
    return found


async def stop_notifications(session: AsyncSession, phone: str) -> str:
    acc = await session.scalar(select(ChannelAccount).where(
        ChannelAccount.channel == CHANNEL, ChannelAccount.external_user_id == phone))
    if acc is None:
        return "Этот номер ни к чему не привязан."
    acc.is_active = False
    await session.commit()
    return "Уведомления отключены. Чтобы включить снова, привяжите номер кодом: /start КОД"


async def process_message(session: AsyncSession, runtime: AIRuntime, *, phone: str, text: str) -> str:
    cmd, _, arg = text.partition(" ")
    cmd = cmd.lower()
    if cmd in ("/start", "start") and arg.strip():
        return await link_account(session, arg.strip(), phone, CHANNEL)
    if cmd in ("/help", "help", "/start", "start"):
        return HELP
    if cmd in ("/unlink",):
        return await unlink_account(session, phone, CHANNEL)
    if text.strip().lower() in ("стоп", "stop"):
        return await stop_notifications(session, phone)

    user = await linked_user(session, phone, CHANNEL)
    out = await runtime.handle(session, user, CHANNEL, phone, text)
    return format_reply(out)


async def handle_payload(payload: dict, *, runtime: AIRuntime, client: WhatsAppClient,
                         maker: async_sessionmaker[AsyncSession]) -> None:
    """Обрабатывает тело webhook. Ошибки не пробрасываются: человеку уходит нейтральный ответ."""
    for msg in extract_messages(payload):
        text = msg["text"].strip()[:MAX_TEXT]
        if not text:
            continue
        try:
            async with maker() as session:
                if msg["id"] and not await claim_message(session, msg["id"], CHANNEL):
                    continue  # Meta повторяет доставку: одно сообщение обрабатываем один раз
                reply = await process_message(session, runtime, phone=msg["from"], text=text)
        except OllamaUnavailable:
            reply = "Ассистент временно недоступен, попробуйте позже."
        except Exception:
            log.exception("Ошибка обработки сообщения WhatsApp")
            reply = "Что-то пошло не так, попробуйте ещё раз позже."
        try:
            await client.send_text(msg["from"], reply)
        except WhatsAppError as e:
            log.warning("Не удалось отправить ответ: %s", e)
