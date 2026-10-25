"""Напоминание «тариф скоро закончится» и автопродление.

За PLAN_REMIND_DAYS_BEFORE дней до конца оплаченного периода для каждого пользователя:
  - автопродление выключено: сообщение «тариф заканчивается»;
  - автопродление включено и провайдер умеет списывать сам (supports_recurring): списываем, пишем «продлён»;
    не вышло, пишем «не удалось списать» со ссылкой на ручную оплату;
  - автопродление включено, но провайдер списывать не умеет: выставляем счёт и шлём ссылку на оплату.
Одно напоминание на один срок окончания: если пользователь продлил, срок сдвинулся и напоминание придёт заново позже."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mysite.database.ai_models import (AutoRenewal, ChannelAccount, Payment, Plan, PlanNotice, PlanNoticeKind,
                                       User, UserPlan)
from mysite.services import billing
from mysite.tasks.notifier import BATCH, MAX_ATTEMPTS, Sender, send_note

log = logging.getLogger("booking_ai.plan_notices")

RENEW_KINDS = (PlanNoticeKind.RENEW_INVOICE, PlanNoticeKind.RENEWED, PlanNoticeKind.RENEW_FAILED)


def _date(dt: datetime) -> str:
    return billing.aware(dt).strftime("%d.%m.%Y")


def _money(amount, currency: str) -> str:
    text = f"{amount:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} {currency}"


def text_expiring(plan: Plan, expires_at: datetime, now: datetime) -> str:
    days = max((billing.aware(expires_at) - now).days, 0)
    left = "сегодня" if days == 0 else f"через {days} дн."
    return (f"Тариф «{plan.name}» заканчивается {_date(expires_at)} ({left}). После этого уведомления в Telegram и "
            f"WhatsApp перестанут приходить, останется бесплатный тариф. Чтобы продлить, оплатите тариф в приложении "
            f"или включите автопродление.")


def text_invoice(plan: Plan, expires_at: datetime, payment: Payment) -> str:
    return (f"Тариф «{plan.name}» заканчивается {_date(expires_at)}. Мы подготовили счёт на продление: "
            f"{_money(payment.amount, payment.currency)} за {plan.duration_days} дн. Оплатить: {payment.checkout_url}\n"
            f"Новый период начнётся после текущего.")


def text_renewed(plan: Plan, payment: Payment, new_expires: datetime) -> str:
    return (f"Тариф «{plan.name}» продлён до {_date(new_expires)}. "
            f"Списано {_money(payment.amount, payment.currency)}.")


def text_failed(plan: Plan, expires_at: datetime, payment: Payment) -> str:
    return (f"Не удалось автоматически списать оплату за тариф «{plan.name}», он заканчивается {_date(expires_at)}. "
            f"Оплатить вручную: {payment.checkout_url}")


async def find_expiring(db: AsyncSession, now: datetime, days_before: int) -> list[tuple[int, datetime, int]]:
    """(user_id, когда кончается всё оплаченное, plan_id последнего периода) для тех, у кого конец уже близко."""
    latest = (select(UserPlan.user_id.label("user_id"), func.max(UserPlan.expires_at).label("exp"))
              .where(UserPlan.expires_at > now).group_by(UserPlan.user_id).subquery())
    rows = (await db.execute(
        select(UserPlan.user_id, UserPlan.expires_at, UserPlan.plan_id)
        .join(latest, and_(UserPlan.user_id == latest.c.user_id, UserPlan.expires_at == latest.c.exp))
        .where(latest.c.exp <= now + timedelta(days=days_before))
        .order_by(UserPlan.user_id, UserPlan.id))).all()
    seen, result = set(), []
    for user_id, expires_at, plan_id in rows:
        if user_id not in seen:
            seen.add(user_id)
            result.append((user_id, expires_at, plan_id))
    return result


async def _channels(db: AsyncSession, user_id: int) -> list[str]:
    """«Входящие» в приложении всегда, плюс привязанные мессенджеры."""
    linked = (await db.execute(select(ChannelAccount.channel).where(
        ChannelAccount.user_id == user_id, ChannelAccount.is_verified.is_(True),
        ChannelAccount.is_active.is_(True)))).scalars().all()
    return ["api"] + sorted(c for c in set(linked) if c in ("telegram", "whatsapp"))


async def _add_notices(db: AsyncSession, user_id: int, kind: str, expires_at: datetime, text: str,
                       channels: list[str], now: datetime) -> int:
    added = 0
    for channel in channels:
        in_app = channel == "api"
        try:
            async with db.begin_nested():  # при дубле откатывается только эта вставка
                db.add(PlanNotice(user_id=user_id, kind=kind, channel=channel, expires_at=expires_at, text=text,
                                  status="sent" if in_app else "pending", sent_at=now if in_app else None))
            added += 1
        except IntegrityError:
            pass
    return added


async def _renew(db: AsyncSession, user_id: int, expires_at: datetime, plan: Plan, provider, channels: list[str],
                 now: datetime) -> int:
    # Сначала занимаем этот срок записью во «входящих» и коммитим. Если процесс упадёт посреди списания,
    # следующий цикл увидит запись и не выставит второй счёт и не спишет деньги повторно.
    taken = await db.scalar(select(PlanNotice.id).where(
        PlanNotice.user_id == user_id, PlanNotice.expires_at == expires_at, PlanNotice.channel == "api",
        PlanNotice.kind.in_(RENEW_KINDS)))
    if taken:
        return 0
    marker = PlanNotice(user_id=user_id, kind=PlanNoticeKind.RENEW_FAILED, channel="api", expires_at=expires_at,
                        text=f"Продление тарифа «{plan.name}» не завершено. Оплатите тариф в приложении.",
                        status="sent", sent_at=now)
    db.add(marker)
    await db.commit()

    payment = Payment(user_id=user_id, plan_id=plan.id, amount=plan.price, currency=plan.currency,
                      provider=provider.name)
    db.add(payment)
    await db.flush()  # нужен id, он попадает в ссылку оплаты
    payment.checkout_url = provider.create_checkout(payment)
    await db.commit()

    kind, text = PlanNoticeKind.RENEW_INVOICE, text_invoice(plan, expires_at, payment)
    if getattr(provider, "supports_recurring", False):
        try:
            provider_payment_id = await provider.charge_recurring(payment)
        except Exception as e:
            log.warning("Автосписание не прошло: %s", type(e).__name__)
            kind, text = PlanNoticeKind.RENEW_FAILED, text_failed(plan, expires_at, payment)
        else:
            await billing.mark_paid(db, payment.id, amount=payment.amount, currency=payment.currency,
                                    provider_payment_id=provider_payment_id)
            _, new_expires = await billing.get_current_plan(db, user_id, now)
            kind, text = PlanNoticeKind.RENEWED, text_renewed(plan, payment, new_expires or expires_at)

    marker.kind, marker.text = kind, text  # запись-«занято» становится итоговым сообщением
    added = await _add_notices(db, user_id, kind, expires_at, text, [c for c in channels if c != "api"], now)
    await db.commit()
    return added + 1


async def create_plan_notices(db: AsyncSession, provider, now: datetime, days_before: int) -> int:
    created = 0
    for user_id, expires_at, plan_id in await find_expiring(db, now, days_before):
        user = await db.get(User, user_id)
        plan = await db.get(Plan, plan_id)
        if user is None or not user.is_active or plan is None or plan.code == billing.FREE_CODE:
            continue
        channels = await _channels(db, user_id)
        renewal = await db.scalar(select(AutoRenewal).where(AutoRenewal.user_id == user_id,
                                                           AutoRenewal.is_enabled.is_(True)))
        if renewal is not None and plan.is_active and plan.price > 0:
            created += await _renew(db, user_id, expires_at, plan, provider, channels, now)
        else:
            created += await _add_notices(db, user_id, PlanNoticeKind.EXPIRING, expires_at,
                                          text_expiring(plan, expires_at, now), channels, now)
            await db.commit()
    return created


async def send_pending_plan_notices(db: AsyncSession, senders: dict[str, Sender], now: datetime) -> int:
    query = (select(PlanNotice)
             .where(PlanNotice.status.in_(["pending", "failed"]), PlanNotice.attempts < MAX_ATTEMPTS,
                    PlanNotice.channel != "api")
             .order_by(PlanNotice.id).limit(BATCH))
    sent = 0
    for note in (await db.scalars(query)).all():
        await send_note(db, note, note.text, senders, now, check_plan=False)
        await db.commit()
        sent += note.status == "sent"
    return sent


async def run_plan_cycle(maker: async_sessionmaker[AsyncSession], senders: dict[str, Sender], provider,
                         days_before: int, now: datetime | None = None) -> dict:
    now = now or billing.now_utc()
    async with maker() as db:
        created = await create_plan_notices(db, provider, now, days_before)
        sent = await send_pending_plan_notices(db, senders, now)
    return {"plan_notices_created": created, "plan_notices_sent": sent}
