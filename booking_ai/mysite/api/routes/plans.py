from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, get_current_user_optional, require_admin
from mysite.database.ai_models import AutoRenewal, Payment, Plan, User
from mysite.database.session import get_session
from mysite.schemas.billing import AutoRenewIn, MyPlanOut, PlanCreate, PlanOut, PlanUpdate
from mysite.schemas.common import MessageOut
from mysite.services import billing

router = APIRouter(prefix="/plans", tags=["plans"])


async def get_or_404(db: AsyncSession, plan_id: int) -> Plan:
    obj = await db.get(Plan, plan_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    return obj


@router.get("/", response_model=list[PlanOut])
async def get_all(
    include_inactive: bool = False,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    if include_inactive and (user is None or user.role != "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    query = select(Plan).order_by(Plan.price, Plan.id)
    if not include_inactive:
        query = query.where(Plan.is_active.is_(True))
    return (await db.scalars(query)).all()


# /my стоит выше /{plan_id}, иначе "my" примется за id
@router.get("/my", response_model=MyPlanOut)
async def get_my(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    plan, expires_at = await billing.get_current_plan(db, user.id)
    used = await billing.count_active_subscriptions(db, user.id)
    renewal = await db.scalar(select(AutoRenewal).where(AutoRenewal.user_id == user.id))
    return MyPlanOut(plan=plan, expires_at=expires_at, is_paid=expires_at is not None, subscriptions_used=used,
                     auto_renew=bool(renewal and renewal.is_enabled))


# Автопродление: перед концом оплаченного периода система продлевает тариф (или выставляет счёт, если провайдер
# не умеет списывать сам). Включить можно только при действующем платном тарифе, выключить можно всегда.
@router.post("/my/auto-renew", response_model=MessageOut)
async def set_auto_renew(data: AutoRenewIn, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_session)):
    renewal = await db.scalar(select(AutoRenewal).where(AutoRenewal.user_id == user.id))
    if data.enabled:
        _, expires_at = await billing.get_current_plan(db, user.id)
        if expires_at is None:
            raise HTTPException(status_code=409, detail="Автопродление доступно только при действующем платном тарифе")
    if renewal is None:
        if data.enabled:
            db.add(AutoRenewal(user_id=user.id, is_enabled=True))
    else:
        renewal.is_enabled = data.enabled
    await db.commit()
    return MessageOut(message="Автопродление включено" if data.enabled else "Автопродление выключено")


@router.get("/{plan_id}", response_model=PlanOut)
async def get_one(plan_id: int, db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, plan_id)
    if not obj.is_active:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    return obj


@router.post("/", response_model=MessageOut[PlanOut], status_code=201)
async def create(data: PlanCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    if await db.scalar(select(Plan.id).where(Plan.code == data.code)):
        raise HTTPException(status_code=409, detail="Тариф с таким кодом уже есть")

    obj = Plan(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Тариф добавлен", data=obj)


@router.patch("/{plan_id}", response_model=MessageOut[PlanOut])
async def update(plan_id: int, data: PlanUpdate, admin: User = Depends(require_admin),
                 db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, plan_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    # бесплатный тариф должен остаться бесплатным
    if obj.code == billing.FREE_CODE and changes.get("price"):
        raise HTTPException(status_code=422, detail="Бесплатный тариф не может стоить денег")

    for field, value in changes.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Тариф изменён", data=obj)


@router.delete("/{plan_id}", response_model=MessageOut)
async def delete(plan_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, plan_id)
    if obj.code == billing.FREE_CODE:
        raise HTTPException(status_code=409, detail="Бесплатный тариф удалять нельзя")

    paid = await db.scalar(select(func.count()).select_from(Payment).where(Payment.plan_id == obj.id))
    if paid:
        raise HTTPException(status_code=409, detail="По тарифу были платежи, лучше отключите его (is_active=false)")

    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Тариф удалён")
