from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, get_payment_provider
from mysite.database.ai_models import Payment, Plan, User
from mysite.database.session import get_session
from mysite.schemas.billing import CheckoutIn, PaymentOut
from mysite.schemas.common import MessageOut
from mysite.services import billing

router = APIRouter(prefix="/payments", tags=["payments"])


async def get_or_404(db: AsyncSession, payment_id: int, user: User) -> Payment:
    obj = await db.get(Payment, payment_id)
    # чужие платежи не показываем
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Платёж не найден")
    return obj


@router.get("/", response_model=list[PaymentOut])
async def get_all(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    query = select(Payment).where(Payment.user_id == user.id).order_by(Payment.id.desc()).offset(skip).limit(limit)
    return (await db.scalars(query)).all()


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_one(payment_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, payment_id, user)


# 1. Пользователь выбирает тариф, мы создаём платёж и отдаём ссылку на оплату
@router.post("/", response_model=MessageOut[PaymentOut], status_code=201)
async def create(
    data: CheckoutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    provider=Depends(get_payment_provider),
):
    plan = await db.get(Plan, data.plan_id)
    if plan is None or not plan.is_active:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    if plan.price <= 0:
        raise HTTPException(status_code=422, detail="Бесплатный тариф оплачивать не нужно")

    obj = Payment(user_id=user.id, plan_id=plan.id, amount=plan.price, currency=plan.currency, provider=provider.name)
    db.add(obj)
    await db.flush()  # нужен id, он попадает в ссылку оплаты
    obj.checkout_url = provider.create_checkout(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Платёж создан, перейдите по ссылке для оплаты", data=obj)


# 2. Платёжная система сообщает об оплате. Подпись проверяет провайдер, пользователь тут не авторизуется.
@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: AsyncSession = Depends(get_session), provider=Depends(get_payment_provider)):
    event = provider.parse_webhook(request.headers, await request.body())

    if event.status == "paid":
        await billing.mark_paid(db, event.payment_id, amount=event.amount, currency=event.currency,
                                provider_payment_id=event.provider_payment_id)
    elif event.status == "failed":
        payment = await db.get(Payment, event.payment_id)
        if payment is not None and payment.status == "pending":
            payment.status = "failed"
            await db.commit()
    return {"ok": True}


# Только для разработки: «оплатить» свой платёж без банка. В production провайдер dev запрещён в настройках.
@router.post("/{payment_id}/dev-pay", response_model=MessageOut[PaymentOut])
async def dev_pay(
    payment_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    provider=Depends(get_payment_provider),
):
    if provider.name != "dev":
        raise HTTPException(status_code=404, detail="Not found")

    obj = await get_or_404(db, payment_id, user)
    obj = await billing.mark_paid(db, obj.id, amount=Decimal(obj.amount), currency=obj.currency)
    return MessageOut(message="Оплата прошла, тариф включён", data=obj)


# Отмена: платёж остаётся в истории, но оплатить его уже нельзя
@router.delete("/{payment_id}", response_model=MessageOut)
async def delete(payment_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, payment_id, user)
    if obj.status != "pending":
        raise HTTPException(status_code=409, detail="Отменить можно только неоплаченный платёж")

    obj.status = "cancelled"
    await db.commit()
    return MessageOut(message="Платёж отменён")
