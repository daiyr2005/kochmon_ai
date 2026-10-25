"""Тарифы: какой план сейчас у пользователя, какие у него лимиты и что происходит после оплаты."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.database.ai_models import Payment, Plan, SearchSubscription, UserPlan
from mysite.services.errors import ServiceError

FREE_CODE = "free"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime) -> datetime:
    # SQLite отдаёт даты без часового пояса
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def get_free_plan(db: AsyncSession) -> Plan:
    plan = await db.scalar(select(Plan).where(Plan.code == FREE_CODE))
    if plan is None:
        # если сид не запускали, всё равно работаем с самыми строгими лимитами
        plan = Plan(code=FREE_CODE, name="Free", price=Decimal(0), currency="KGS", duration_days=30,
                    max_subscriptions=1, min_frequency_minutes=1440, channels=["api"], is_active=True)
    return plan


async def get_current_plan(db: AsyncSession, user_id: int, now: datetime | None = None) -> tuple[Plan, datetime | None]:
    """Возвращает (тариф, когда истекает). Если оплаченного периода нет — бесплатный тариф."""
    now = now or now_utc()
    row = (await db.execute(
        select(Plan, UserPlan.expires_at)
        .join(UserPlan, UserPlan.plan_id == Plan.id)
        .where(UserPlan.user_id == user_id, UserPlan.expires_at > now)
        .order_by(UserPlan.expires_at.desc())
        .limit(1)
    )).first()
    if row is None:
        return await get_free_plan(db), None
    return row[0], aware(row[1])


async def count_active_subscriptions(db: AsyncSession, user_id: int, skip_id: int | None = None) -> int:
    query = select(func.count()).select_from(SearchSubscription).where(
        SearchSubscription.user_id == user_id, SearchSubscription.is_active.is_(True))
    if skip_id:
        query = query.where(SearchSubscription.id != skip_id)
    return await db.scalar(query) or 0


async def check_subscription_allowed(db: AsyncSession, user_id: int, channel: str, skip_id: int | None = None):
    """Вызывается перед созданием или включением подписки."""
    plan, _ = await get_current_plan(db, user_id)

    if channel not in (plan.channels or []):
        raise ServiceError(403, f"Тариф «{plan.name}» не включает уведомления в {channel}. Оформите тариф выше.")

    used = await count_active_subscriptions(db, user_id, skip_id)
    if used >= plan.max_subscriptions:
        raise ServiceError(403, f"На тарифе «{plan.name}» можно иметь подписок: {plan.max_subscriptions}. Оформите тариф выше.")


async def activate_plan(db: AsyncSession, payment: Payment, now: datetime | None = None) -> UserPlan:
    """Включает оплаченный месяц. Если тариф ещё действует, новый период идёт после него."""
    now = now or now_utc()

    already = await db.scalar(select(UserPlan).where(UserPlan.payment_id == payment.id))
    if already:
        return already  # повторный webhook не продлевает тариф второй раз

    plan = await db.get(Plan, payment.plan_id)
    last_end = await db.scalar(select(func.max(UserPlan.expires_at)).where(
        UserPlan.user_id == payment.user_id, UserPlan.plan_id == plan.id, UserPlan.expires_at > now))
    start = aware(last_end) if last_end else now

    period = UserPlan(user_id=payment.user_id, plan_id=plan.id, payment_id=payment.id, started_at=start,
                      expires_at=start + timedelta(days=plan.duration_days))
    db.add(period)
    return period


async def mark_paid(db: AsyncSession, payment_id: int, *, amount: Decimal | None = None,
                    currency: str | None = None, provider_payment_id: str | None = None) -> Payment:
    """Отмечает платёж оплаченным и включает тариф. Безопасно вызывать повторно."""
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise ServiceError(404, "Платёж не найден")
    if payment.status == "paid":
        return payment
    if payment.status != "pending":
        raise ServiceError(409, f"Платёж в статусе {payment.status}, оплатить его нельзя")

    # сумма и валюта должны совпадать с тем, что мы выставляли
    if amount is not None and Decimal(amount) != payment.amount:
        raise ServiceError(400, "Сумма платежа не совпадает")
    if currency is not None and currency.upper() != payment.currency:
        raise ServiceError(400, "Валюта платежа не совпадает")

    payment.status = "paid"
    payment.paid_at = now_utc()
    if provider_payment_id:
        payment.provider_payment_id = provider_payment_id
    await activate_plan(db, payment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ServiceError(409, "Платёж уже обработан")
    return payment
