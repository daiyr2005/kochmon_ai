"""Автоматические уведомления по подпискам.

Один цикл (run_cycle) делает по порядку:
  1. Находит подписки, которым пора проверяться (с учётом тарифа).
  2. Ищет новые подходящие объявления и создаёт уведомления. Повтор не создаётся: в таблице уникальная пара.
  3. Отправляет неотправленные уведомления в Telegram / WhatsApp, с ограниченным числом повторов.
Поиск по интернету сюда не входит: уведомляем о новых объявлениях самой платформы."""
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mysite.database.ai_models import (Category, ChannelAccount, City, EventNotification, Listing, ListingEvent,
                                       ListingStatus, Notification, SearchSubscription)
from mysite.services import billing, events
from mysite.services import listing_service as svc

log = logging.getLogger("booking_ai.notifier")

MAX_ATTEMPTS = 3
BATCH = 200

# канал -> функция отправки (получатель, текст)
Sender = Callable[[str, str], Awaitable[None]]

PERIODS = {"month": "в месяц", "night": "за ночь", "day": "за сутки", "total": ""}


def build_text(listing: Listing, sub: SearchSubscription, category: str | None, city: str | None) -> str:
    """Текст уведомления: только то, что реально есть в объявлении."""
    lines = ["Новое объявление по вашей подписке!", "", listing.title]
    if category:
        lines.append(f"Категория: {category}")
    if city:
        lines.append(f"Город: {city}")
    if listing.price is not None:
        price = f"{listing.price:f}".rstrip("0").rstrip(".")
        lines.append(f"Цена: {price} {listing.currency or ''} {PERIODS.get(listing.price_period or '', '')}".strip())
    if listing.rooms is not None:
        lines.append(f"Комнаты: {listing.rooms}")
    lines.append(f"Источник: {listing.source_name or 'Booking AI'}")
    if listing.source_url:
        lines.append(f"Ссылка: {listing.source_url}")

    reasons = []
    if sub.city_id:
        reasons.append("город")
    if sub.price_min is not None or sub.price_max is not None:
        reasons.append("бюджет")
    if (sub.filters_json or {}).get("rooms") is not None:
        reasons.append("количество комнат")
    if reasons:
        lines += ["", "Причина совпадения: " + ", ".join(reasons) + " соответствуют фильтрам."]
    return "\n".join(lines)


async def find_matches(db: AsyncSession, sub: SearchSubscription, since: datetime) -> list[Listing]:
    category_ids = await svc.category_subtree_ids(db, sub.category_id) if sub.category_id else None
    rooms = (sub.filters_json or {}).get("rooms")
    found = await svc.query_listings(
        db, statuses=[ListingStatus.ACTIVE], category_ids=category_ids,
        country_ids=[sub.country_id] if sub.country_id else None,
        city_ids=[sub.city_id] if sub.city_id else None,
        price_min=sub.price_min, price_max=sub.price_max, currency=sub.currency, rooms=rooms, limit=100)

    result = []
    for listing in found:
        published = billing.aware(listing.published_at or listing.created_at)
        if published > since and listing.owner_id != sub.user_id:  # свои объявления не присылаем
            result.append(listing)
    return result


# ---------- шаг 1-2: поиск новых объявлений ----------
async def create_notifications(db: AsyncSession, now: datetime) -> int:
    subs = (await db.scalars(select(SearchSubscription).where(SearchSubscription.is_active.is_(True))
                             .order_by(SearchSubscription.user_id, SearchSubscription.id))).all()
    created = 0
    plans: dict[int, tuple] = {}
    taken: dict[int, int] = {}  # сколько подписок пользователя уже взяли в работу

    for sub in subs:
        if sub.user_id not in plans:
            plans[sub.user_id] = await billing.get_current_plan(db, sub.user_id, now)
        plan = plans[sub.user_id][0]

        # лимиты тарифа: лишние подписки (после окончания Pro) просто молчат
        taken[sub.user_id] = taken.get(sub.user_id, 0) + 1
        if taken[sub.user_id] > plan.max_subscriptions or sub.channel not in (plan.channels or []):
            continue

        # частота не может быть чаще, чем разрешает тариф
        every = timedelta(minutes=max(sub.frequency_minutes, plan.min_frequency_minutes))
        if sub.last_checked_at and now < billing.aware(sub.last_checked_at) + every:
            continue

        since = billing.aware(sub.last_checked_at or sub.created_at)
        for listing in await find_matches(db, sub, since):
            try:
                async with db.begin_nested():  # при дубле откатывается только эта вставка
                    db.add(Notification(
                        user_id=sub.user_id, listing_id=listing.id, subscription_id=sub.id, channel=sub.channel,
                        # канал api — это «входящие» в приложении, отправлять некуда
                        status="sent" if sub.channel == "api" else "pending",
                        sent_at=now if sub.channel == "api" else None))
                created += 1
            except IntegrityError:
                pass  # такое уведомление уже есть
        sub.last_checked_at = now
    await db.commit()
    return created


# ---------- шаг 3: отправка ----------
async def deliver(db: AsyncSession, note: Notification, senders: dict[str, Sender], now: datetime) -> None:
    def fail(message: str, final: bool = False):
        note.status = "failed"
        note.attempts = MAX_ATTEMPTS if final else note.attempts + 1
        note.error_message = message[:500]

    listing = await db.get(Listing, note.listing_id)
    sub = await db.get(SearchSubscription, note.subscription_id)
    if listing is None or sub is None or listing.status != ListingStatus.ACTIVE:
        return fail("Объявление или подписка недоступны", final=True)

    plan, _ = await billing.get_current_plan(db, note.user_id, now)
    if note.channel not in (plan.channels or []):
        return fail(f"Тариф «{plan.name}» не включает канал {note.channel}", final=True)

    account = await db.scalar(select(ChannelAccount).where(
        ChannelAccount.user_id == note.user_id, ChannelAccount.channel == note.channel,
        ChannelAccount.is_verified.is_(True), ChannelAccount.is_active.is_(True)))
    if account is None:
        return fail("Канал не привязан или уведомления отключены", final=True)

    send = senders.get(note.channel)
    if send is None:
        return fail(f"Канал {note.channel} не настроен на сервере")

    category = await db.get(Category, listing.category_id)
    city = await db.get(City, listing.city_id) if listing.city_id else None
    text = build_text(listing, sub, category.name if category else None, city.name if city else None)
    try:
        await send(account.external_user_id, text)
    except Exception as e:
        log.warning("Не удалось отправить уведомление %s: %s", note.id, type(e).__name__)
        return fail(f"{type(e).__name__}: {e}")
    note.status = "sent"
    note.sent_at = now
    note.error_message = None


async def send_pending(db: AsyncSession, senders: dict[str, Sender], now: datetime) -> int:
    query = (select(Notification)
             .where(Notification.status.in_(["pending", "failed"]), Notification.attempts < MAX_ATTEMPTS)
             .order_by(Notification.id).limit(BATCH))
    sent = 0
    for note in (await db.scalars(query)).all():
        await deliver(db, note, senders, now)
        await db.commit()  # фиксируем по одному: сбой на одном уведомлении не откатывает остальные
        sent += note.status == "sent"
    return sent


async def run_cycle(maker: async_sessionmaker[AsyncSession], senders: dict[str, Sender],
                    now: datetime | None = None) -> dict:
    now = now or billing.now_utc()
    async with maker() as db:
        created = await create_notifications(db, now)
        sent = await send_pending(db, senders, now)
    return {"created": created, "sent": sent}


# ---------- уведомления о событиях (смена цены, снятие объявления) и о тарифе ----------
# Лежат отдельно от run_cycle, чтобы тот возвращал прежний результат; планировщик вызывает всё по очереди.
def mark_failed(note, message: str, final: bool = False) -> None:
    note.status = "failed"
    note.attempts = MAX_ATTEMPTS if final else note.attempts + 1
    note.error_message = message[:500]


async def send_note(db: AsyncSession, note, text: str, senders: dict[str, Sender], now: datetime, *,
                    check_plan: bool = True) -> None:
    """Отправляет готовый текст по уведомлению (EventNotification или PlanNotice) и записывает результат.
    check_plan=False для сообщений о самом тарифе: «Pro закончился» нужно доставить и тому, у кого Pro уже нет."""
    if check_plan:
        plan, _ = await billing.get_current_plan(db, note.user_id, now)
        if note.channel not in (plan.channels or []):
            return mark_failed(note, f"Тариф «{plan.name}» не включает канал {note.channel}", final=True)
    account = await db.scalar(select(ChannelAccount).where(
        ChannelAccount.user_id == note.user_id, ChannelAccount.channel == note.channel,
        ChannelAccount.is_verified.is_(True), ChannelAccount.is_active.is_(True)))
    if account is None:
        return mark_failed(note, "Канал не привязан или уведомления отключены", final=True)
    send = senders.get(note.channel)
    if send is None:
        return mark_failed(note, f"Канал {note.channel} не настроен на сервере")
    try:
        await send(account.external_user_id, text)
    except Exception as e:
        log.warning("Не удалось отправить уведомление %s: %s", type(note).__name__, type(e).__name__)
        return mark_failed(note, f"{type(e).__name__}: {e}")
    note.status = "sent"
    note.sent_at = now
    note.error_message = None


async def send_pending_events(db: AsyncSession, senders: dict[str, Sender], now: datetime) -> int:
    query = (select(EventNotification)
             .where(EventNotification.status.in_(["pending", "failed"]), EventNotification.attempts < MAX_ATTEMPTS,
                    EventNotification.channel != "api")
             .order_by(EventNotification.id).limit(BATCH))
    sent = 0
    for note in (await db.scalars(query)).all():
        event = await db.get(ListingEvent, note.event_id)
        if event is None:
            mark_failed(note, "Событие не найдено", final=True)
        else:
            await send_note(db, note, events.build_event_text(event), senders, now)
        await db.commit()
        sent += note.status == "sent"
    return sent


async def run_events_cycle(maker: async_sessionmaker[AsyncSession], senders: dict[str, Sender],
                           now: datetime | None = None) -> dict:
    now = now or billing.now_utc()
    async with maker() as db:
        return {"events_sent": await send_pending_events(db, senders, now)}
