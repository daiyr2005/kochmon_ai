from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user
from mysite.database.ai_models import Category, ChannelAccount, City, Country, SearchSubscription, User
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.search import SearchFilters
from mysite.schemas.subscription import SubscriptionCreate, SubscriptionOut, SubscriptionUpdate
from mysite.services import billing

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


async def get_or_404(db: AsyncSession, sub_id: int, user: User) -> SearchSubscription:
    obj = await db.get(SearchSubscription, sub_id)
    # чужие подписки не раскрываем
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    return obj


async def check_refs(db: AsyncSession, data: dict):
    """Категория, страна и город должны существовать."""
    for field, model, name in (("category_id", Category, "Категория"),
                               ("country_id", Country, "Страна"),
                               ("city_id", City, "Город")):
        if data.get(field) is not None and await db.get(model, data[field]) is None:
            raise HTTPException(status_code=422, detail=f"{name} не найдена")


def clean_filters(raw: dict | None) -> dict:
    # filters_json проверяем той же схемой, что и поиск
    if not raw:
        return {}
    try:
        return SearchFilters.model_validate(raw).model_dump(mode="json", exclude_none=True)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Некорректные фильтры подписки: {e}")


@router.get("/", response_model=list[SubscriptionOut])
async def get_all(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    query = (select(SearchSubscription).where(SearchSubscription.user_id == user.id)
             .order_by(SearchSubscription.id).offset(skip).limit(limit))
    return (await db.scalars(query)).all()


@router.get("/{subscription_id}", response_model=SubscriptionOut)
async def get_one(subscription_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, subscription_id, user)


@router.post("/", response_model=MessageOut[SubscriptionOut], status_code=201)
async def create(data: SubscriptionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    values = data.model_dump()

    # для telegram/whatsapp сначала нужно привязать и подтвердить аккаунт
    if data.channel != "api":
        linked = await db.scalar(select(ChannelAccount.id).where(
            ChannelAccount.user_id == user.id,
            ChannelAccount.channel == data.channel,
            ChannelAccount.is_verified.is_(True),
            ChannelAccount.is_active.is_(True),
        ))
        if not linked:
            raise HTTPException(status_code=400, detail=f"Сначала привяжите и подтвердите канал {data.channel}")

    await check_refs(db, values)
    values["filters_json"] = clean_filters(values["filters_json"])

    # лимиты тарифа проверяем в самом конце, после остальных проверок
    await billing.check_subscription_allowed(db, user.id, data.channel)

    obj = SearchSubscription(user_id=user.id, **values)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Подписка добавлена", data=obj)


@router.patch("/{subscription_id}", response_model=MessageOut[SubscriptionOut])
async def update(
    subscription_id: int,
    data: SubscriptionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    obj = await get_or_404(db, subscription_id, user)
    changes = data.model_dump(exclude_unset=True)

    # эти поля нельзя обнулить
    for field in ("frequency_minutes", "is_active"):
        if field in changes and changes[field] is None:
            del changes[field]

    await check_refs(db, changes)
    if "filters_json" in changes:
        changes["filters_json"] = clean_filters(changes["filters_json"])

    # проверяем итоговые значения: то, что изменили, плюс то, что уже было
    price_min = changes.get("price_min", obj.price_min)
    price_max = changes.get("price_max", obj.price_max)
    currency = changes.get("currency", obj.currency)
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(status_code=422, detail="Минимальная цена больше максимальной")
    if (price_min is not None or price_max is not None) and not currency:
        raise HTTPException(status_code=422, detail="Укажите валюту для фильтра по цене")

    # повторное включение подписки тоже должно уложиться в тариф
    if changes.get("is_active") and not obj.is_active:
        await billing.check_subscription_allowed(db, user.id, obj.channel, skip_id=obj.id)

    for field, value in changes.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Подписка изменена", data=obj)


@router.delete("/{subscription_id}", response_model=MessageOut)
async def delete(subscription_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, subscription_id, user)
    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Подписка удалена")
