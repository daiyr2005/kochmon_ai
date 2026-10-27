from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, get_payment_provider
from mysite.database.ai_models import (Listing, Payment, PaymentEvent, Plan, PromotionActivation, PromotionPayment,
                                      PromotionTariff, User)
from mysite.database.session import get_session
from mysite.schemas.billing import CheckoutIn, PaymentOut
from mysite.schemas.common import MessageOut
from mysite.services import billing
from mysite.services.user_notifications import notify_user

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/promotion-tariffs")
async def promotion_tariffs(db: AsyncSession = Depends(get_session)):
    return (await db.scalars(select(PromotionTariff).where(PromotionTariff.is_active.is_(True))
                             .order_by(PromotionTariff.price))).all()


@router.post("/listings/{listing_id}/promotion", status_code=201)
async def create_promotion_payment(listing_id: int, tariff_id: int, user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_session), provider=Depends(get_payment_provider)):
    listing = await db.get(Listing, listing_id)
    if listing is None or listing.owner_id != user.id:
        raise HTTPException(404, "Listing not found")
    if listing.status != "active":
        raise HTTPException(409, "Only published listings can be promoted")
    tariff = await db.get(PromotionTariff, tariff_id)
    if tariff is None or not tariff.is_active or tariff.price <= 0:
        raise HTTPException(404, "Promotion tariff not found")
    payment = PromotionPayment(user_id=user.id, listing_id=listing.id, tariff_id=tariff.id,
                               amount=tariff.price, currency=tariff.currency, provider=provider.name)
    db.add(payment)
    await db.flush()
    payment.checkout_url = (f"/api/payments/promotions/{payment.id}/dev-pay" if provider.name == "dev"
                            else provider.create_checkout(payment))
    await db.commit()
    await db.refresh(payment)
    return payment


@router.get("/promotions")
async def my_promotion_payments(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return (await db.scalars(select(PromotionPayment).where(PromotionPayment.user_id == user.id)
                             .order_by(PromotionPayment.id.desc()))).all()


@router.delete("/promotions/{payment_id}")
async def cancel_promotion_payment(payment_id: int, user: User = Depends(get_current_user),
                                   db: AsyncSession = Depends(get_session)):
    payment = await db.get(PromotionPayment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    if payment.status != "pending":
        raise HTTPException(409, "Only pending payments can be cancelled")
    payment.status = "cancelled"
    await notify_user(db, user.id, f"promotion-payment:{payment.id}:cancelled", "Платёж отменён",
                      "Продвижение не активировано", payment.listing_id)
    await db.commit()
    return {"ok": True, "status": payment.status}


async def confirm_promotion_payment(db: AsyncSession, payment: PromotionPayment, event_id: str,
                                   amount: Decimal | None, currency: str | None,
                                   provider_payment_id: str | None, status: str):
    if not event_id:
        raise HTTPException(400, "Provider event_id is required")
    if await db.scalar(select(PaymentEvent.id).where(PaymentEvent.event_id == event_id)):
        return payment
    db.add(PaymentEvent(event_id=event_id, payment_id=payment.id, status=status))
    if payment.status != "pending":
        await db.commit()
        return payment
    if status == "paid":
        if amount is not None and amount != payment.amount or currency and currency.upper() != payment.currency:
            raise HTTPException(400, "Payment amount or currency mismatch")
        listing = await db.get(Listing, payment.listing_id)
        tariff = await db.get(PromotionTariff, payment.tariff_id)
        if listing is None or tariff is None:
            raise HTTPException(409, "Promotion target is no longer available")
        payment.status = "paid"
        payment.paid_at = datetime.now(timezone.utc)
        payment.provider_payment_id = provider_payment_id
        db.add(PromotionActivation(payment_id=payment.id, listing_id=listing.id))
        listing.promotion_ends_at = max(listing.promotion_ends_at or datetime.now(timezone.utc),
                                        datetime.now(timezone.utc)) + timedelta(days=tariff.duration_days)
        await notify_user(db, payment.user_id, f"payment:{event_id}", "Платёж подтверждён", "Продвижение объявления активировано", listing.id)
        await notify_user(db, payment.user_id, f"promotion:{event_id}", "Реклама активирована", listing.title, listing.id)
    elif status in {"failed", "cancelled"}:
        payment.status = status
        await notify_user(db, payment.user_id, f"payment:{event_id}", "Платёж отклонён" if status == "failed" else "Платёж отменён",
                          "Продвижение не активировано", payment.listing_id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        current = await db.get(PromotionPayment, payment.id)
        if current is not None and current.status in {"paid", "failed", "cancelled"}:
            return current
        raise HTTPException(409, "Payment event was already processed")
    return payment


@router.post("/promotions/webhook", include_in_schema=False)
async def promotion_webhook(request: Request, db: AsyncSession = Depends(get_session), provider=Depends(get_payment_provider)):
    event = provider.parse_webhook(request.headers, await request.body())
    payment = await db.get(PromotionPayment, event.payment_id)
    if payment is None:
        raise HTTPException(404, "Payment not found")
    await confirm_promotion_payment(db, payment, event.event_id or "", event.amount, event.currency,
                                    event.provider_payment_id, event.status)
    return {"ok": True}


@router.post("/promotions/{payment_id}/dev-pay")
async def dev_pay_promotion(payment_id: int, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_session), provider=Depends(get_payment_provider)):
    if provider.name != "dev":
        raise HTTPException(404, "Not found")
    payment = await db.get(PromotionPayment, payment_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(404, "Payment not found")
    await confirm_promotion_payment(db, payment, f"dev-promotion-{payment.id}", payment.amount,
                                    payment.currency, None, "paid")
    return payment


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
