from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, get_current_user_optional, get_moderation
from mysite.database.ai_models import ListingStatus, User
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.listing import ListingCreate, ListingOut, ListingUpdate
from mysite.schemas.search import normalize_currency
from mysite.services import listing_service
from mysite.services.moderation_service import ModerationService

router = APIRouter(prefix="/listings", tags=["listings"])


async def get_own_or_404(db: AsyncSession, listing_id: int, user: User):
    """Берёт объявление и проверяет, что пользователь может его менять."""
    obj = await listing_service.get_listing_or_404(db, listing_id)
    listing_service.ensure_visible(obj, user)  # чужой черновик — 404, чужое публичное — 403 ниже
    listing_service.ensure_can_modify(obj, user)
    return obj


@router.get("/", response_model=list[ListingOut])
async def get_all(
    category_id: int | None = None,
    country_id: int | None = None,
    city_id: int | None = None,
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    currency: str | None = None,
    rooms: int | None = Query(None, ge=0),
    mine: bool = False,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    if price_min is not None and price_max is not None and price_min > price_max:
        raise HTTPException(status_code=422, detail="Минимальная цена больше максимальной")

    if currency:
        try:
            currency = normalize_currency(currency)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # без mine показываем только опубликованные, со своими — все (или по статусу)
    owner_id = None
    statuses = listing_service.PUBLIC_STATUSES
    if mine:
        if user is None:
            raise HTTPException(status_code=401, detail="Требуется авторизация")
        if status and status not in ListingStatus.ALL:
            raise HTTPException(status_code=422, detail="Неизвестный статус")
        owner_id = user.id
        statuses = [status] if status else None

    category_ids = None
    if category_id is not None:
        category_ids = await listing_service.category_subtree_ids(db, category_id)

    return await listing_service.query_listings(
        db,
        owner_id=owner_id,
        statuses=statuses,
        category_ids=category_ids,
        country_ids=[country_id] if country_id is not None else None,
        city_ids=[city_id] if city_id is not None else None,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        rooms=rooms,
        limit=limit,
        offset=skip,
    )


@router.get("/{listing_id}", response_model=ListingOut)
async def get_one(
    listing_id: int,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    obj = await listing_service.get_listing_or_404(db, listing_id)
    listing_service.ensure_visible(obj, user)
    return obj


@router.post("/", response_model=MessageOut[ListingOut], status_code=201)
async def create(
    data: ListingCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await listing_service.create_listing(db, user, data.model_dump(), moderation)
    return MessageOut(message="Объявление добавлено", data=obj)


@router.patch("/{listing_id}", response_model=MessageOut[ListingOut])
async def update(
    listing_id: int,
    data: ListingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await get_own_or_404(db, listing_id, user)
    obj = await listing_service.update_listing(db, obj, data.model_dump(exclude_unset=True), moderation)
    return MessageOut(message="Объявление изменено", data=obj)


@router.delete("/{listing_id}", response_model=MessageOut)
async def delete(listing_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    obj = await get_own_or_404(db, listing_id, user)
    await listing_service.delete_listing(db, obj)
    return MessageOut(message="Объявление удалено")


@router.post("/{listing_id}/publish", response_model=MessageOut[ListingOut])
async def publish(
    listing_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await get_own_or_404(db, listing_id, user)
    obj = await listing_service.publish_listing(db, obj, moderation)
    return MessageOut(message="Объявление опубликовано", data=obj)


@router.post("/{listing_id}/deactivate", response_model=MessageOut[ListingOut])
async def deactivate(listing_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    obj = await get_own_or_404(db, listing_id, user)
    obj = await listing_service.deactivate_listing(db, obj)
    return MessageOut(message="Объявление снято с публикации", data=obj)
