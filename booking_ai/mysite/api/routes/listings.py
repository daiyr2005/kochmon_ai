from decimal import Decimal

import asyncio
from uuid import uuid4
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, get_current_user_optional, get_moderation
from mysite.database.ai_models import Category, Listing, ListingStatus, User
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.listing import ListingCreate, ListingOut, ListingUpdate
from mysite.schemas.search import normalize_currency
from mysite.services import listing_service
from mysite.services.moderation_service import ModerationService
from mysite.config import BASE_DIR, get_settings

router = APIRouter(prefix="/listings", tags=["listings"])
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.post("/photos", status_code=201)
async def upload_listing_photo(request: Request, file: UploadFile = File(...), user: User = Depends(get_current_user)):
    extension = PHOTO_TYPES.get((file.content_type or "").split(";", 1)[0].lower())
    if not extension:
        raise HTTPException(415, "Use JPEG, PNG, or WebP")
    content = await file.read(MAX_PHOTO_BYTES + 1)
    await file.close()
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(413 if content else 400, "Photo must be non-empty and at most 8 MiB")
    if not ((extension == ".jpg" and content.startswith(b"\xff\xd8\xff")) or
            (extension == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or
            (extension == ".webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP")):
        raise HTTPException(415, "Photo content does not match its media type")
    folder = BASE_DIR / "media" / "listings"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid4().hex}{extension}"
    await asyncio.to_thread((folder / name).write_bytes, content)
    settings = get_settings()
    origin = f"https://{settings.domain.strip().strip('/')}" if settings.app_env.lower() == "production" and settings.domain else str(request.base_url).rstrip("/")
    return {"photo_url": f"{origin}/media/listings/{name}"}


@router.post("/{listing_id}/photos", response_model=MessageOut[ListingOut])
async def attach_listing_photo(listing_id: int, photo_url: str, request: Request, user: User = Depends(get_current_user),
                               db: AsyncSession = Depends(get_session)):
    listing = await get_own_or_404(db, listing_id, user)
    filename = photo_url.rstrip("/").rsplit("/", 1)[-1]
    path = BASE_DIR / "media" / "listings" / filename
    parsed = urlparse(photo_url)
    settings = get_settings()
    trusted_origin = f"https://{settings.domain.strip().strip('/')}" if settings.app_env.lower() == "production" and settings.domain else str(request.base_url).rstrip("/")
    if (not filename or parsed.scheme not in {"http", "https"} or
            f"{parsed.scheme}://{parsed.netloc}" != trusted_origin or
            parsed.path != f"/media/listings/{filename}" or parsed.query or parsed.fragment or
            not path.is_file() or len(listing.photo_urls or []) >= 20):
        raise HTTPException(422, "Photo must be uploaded first; maximum is 20 photos")
    listing.photo_urls = [*(listing.photo_urls or []), photo_url]
    await db.commit()
    await db.refresh(listing)
    return MessageOut(message="Photo attached", data=listing)


async def get_own_or_404(db: AsyncSession, listing_id: int, user: User):
    """Берёт объявление и проверяет, что пользователь может его менять."""
    obj = await listing_service.get_listing_or_404(db, listing_id)
    listing_service.ensure_visible(obj, user)  # чужой черновик — 404, чужое публичное — 403 ниже
    listing_service.ensure_can_modify(obj, user)
    return obj


@router.get("/", response_model=list[ListingOut])
async def get_all(
    category_id: int | None = None,
    category: str | None = Query(None, max_length=128),
    country_id: int | None = None,
    country: str | None = Query(None, max_length=128),
    city_id: int | None = None,
    city: str | None = Query(None, max_length=128),
    q: str | None = Query(None, max_length=300),
    price_min: Decimal | None = Query(None, ge=0),
    price_max: Decimal | None = Query(None, ge=0),
    currency: str | None = None,
    rooms: int | None = Query(None, ge=0),
    mine: bool = False,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    offset: int | None = Query(None, ge=0),
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
    selected_category_id = category_id
    if selected_category_id is None and category:
        selected_category_id = await db.scalar(select(Category.id).where(or_(
            func.lower(Category.slug) == category.casefold(),
            func.lower(Category.name) == category.casefold(),
        )))
        if selected_category_id is None:
            category_ids = []
    if selected_category_id is not None:
        category_ids = await listing_service.category_subtree_ids(db, selected_category_id)

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
        search_text=q,
        city_name=city,
        country_name=country,
        limit=limit,
        offset=offset if offset is not None else skip,
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
