"""События по объявлениям: смена цены и снятие. Получателей определяем сразу, в той же транзакции, что и
само изменение: при удалении объявления его обычные уведомления пропадают, и позже узнать, кого предупредить, уже нельзя.

Предупреждаем тех, кому это объявление уже присылали (по активной подписке). Своё объявление владельцу не приходит."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.database.ai_models import (EventNotification, Listing, ListingEvent, ListingEventKind, Notification,
                                       SearchSubscription)
from mysite.services import billing

_CENT = Decimal("0.01")
PERIODS = {"month": "в месяц", "night": "за ночь", "day": "за сутки", "week": "в неделю", "year": "в год", "total": ""}


def _q(value) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(_CENT)


def price_changed(old_price, old_currency, new_price, new_currency) -> bool:
    return _q(old_price) != _q(new_price) or (old_currency or None) != (new_currency or None)


async def record_listing_event(db: AsyncSession, listing: Listing, kind: str, *, old_price=None, old_currency=None,
                               now: datetime | None = None) -> ListingEvent | None:
    """Создаёт событие и доставки получателям. Не делает commit: вызывающий код коммитит вместе со своим изменением.
    Если предупреждать некого, событие не создаётся."""
    now = now or billing.now_utc()
    rows = (await db.execute(
        select(Notification.user_id, Notification.channel)
        .join(SearchSubscription, SearchSubscription.id == Notification.subscription_id)
        .where(Notification.listing_id == listing.id, Notification.status == "sent",
               SearchSubscription.is_active.is_(True))
        .distinct())).all()
    recipients = [(u, c) for u, c in rows if u != listing.owner_id]
    if not recipients:
        return None

    event = ListingEvent(
        kind=kind, listing_id=listing.id, title=listing.title, old_price=_q(old_price), old_currency=old_currency,
        new_price=_q(listing.price) if kind == ListingEventKind.PRICE_CHANGED else None,
        currency=listing.currency, price_period=listing.price_period, source_url=listing.source_url)
    db.add(event)
    await db.flush()  # нужен id события
    for user_id, channel in recipients:
        in_app = channel == "api"  # канал api — «входящие» в приложении, отправлять некуда
        db.add(EventNotification(event_id=event.id, user_id=user_id, channel=channel,
                                 status="sent" if in_app else "pending", sent_at=now if in_app else None))
    return event


def _money(value: Decimal | None, currency: str | None, period: str | None = None) -> str:
    if value is None:
        return "цена не указана"
    number = f"{value:f}".rstrip("0").rstrip(".") if "." in f"{value:f}" else f"{value:f}"
    return f"{number} {currency or ''} {PERIODS.get(period or '', '')}".strip()


def build_event_text(event: ListingEvent) -> str:
    if event.kind == ListingEventKind.REMOVED:
        lines = ["Объявление снято с публикации.", "", event.title,
                 "Оно больше недоступно для просмотра."]
    else:
        old = _money(event.old_price, event.old_currency or event.currency, event.price_period)
        new = _money(event.new_price, event.currency, event.price_period)
        direction = ""
        if (event.old_price is not None and event.new_price is not None
                and (event.old_currency or event.currency) == event.currency):
            direction = " (подешевело)" if event.new_price < event.old_price else (
                " (подорожало)" if event.new_price > event.old_price else "")
        lines = [f"Цена изменилась{direction}.", "", event.title, f"Было: {old}", f"Стало: {new}"]
        if event.source_url:
            lines.append(f"Ссылка: {event.source_url}")
    return "\n".join(lines)
