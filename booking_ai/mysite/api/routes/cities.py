from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user_optional, require_admin
from mysite.database.ai_models import City, Country, Listing, User
from mysite.database.session import get_session
from mysite.schemas.catalog import CityCreate, CityOut, CityUpdate
from mysite.schemas.common import MessageOut

router = APIRouter(prefix="/cities", tags=["cities"])


async def get_or_404(db: AsyncSession, city_id: int) -> City:
    obj = await db.get(City, city_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Город не найден")
    return obj


async def check_country(db: AsyncSession, country_id: int):
    if await db.get(Country, country_id) is None:
        raise HTTPException(status_code=422, detail="Страна не найдена")


async def check_unique(db: AsyncSession, name: str, country_id: int, skip_id: int | None = None):
    # одинаковое название можно в разных странах, в одной стране нельзя
    query = select(City.id).where(City.country_id == country_id, func.lower(City.name) == func.lower(name))
    if skip_id:
        query = query.where(City.id != skip_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail="Такой город уже есть в этой стране")


@router.get("/", response_model=list[CityOut])
async def get_all(
    country_id: int | None = None,
    q: str | None = Query(None, max_length=128),
    include_inactive: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    if include_inactive and (user is None or user.role != "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    query = select(City).order_by(City.name, City.id)
    if country_id:
        query = query.where(City.country_id == country_id)
    if q:
        query = query.where(func.lower(City.name).contains(func.lower(q), autoescape=True))
    if not include_inactive:
        query = query.where(City.is_active.is_(True))
    return (await db.scalars(query.offset(skip).limit(limit))).all()


@router.get("/{city_id}", response_model=CityOut)
async def get_one(city_id: int, db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, city_id)


@router.post("/", response_model=MessageOut[CityOut], status_code=201)
async def create(data: CityCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    await check_country(db, data.country_id)
    await check_unique(db, data.name, data.country_id)

    obj = City(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Город добавлен", data=obj)


@router.patch("/{city_id}", response_model=MessageOut[CityOut])
async def update(
    city_id: int,
    data: CityUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    obj = await get_or_404(db, city_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    if "country_id" in changes:
        await check_country(db, changes["country_id"])
    await check_unique(db, changes.get("name", obj.name), changes.get("country_id", obj.country_id), skip_id=obj.id)

    for field, value in changes.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Город изменён", data=obj)


@router.delete("/{city_id}", response_model=MessageOut)
async def delete(city_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, city_id)

    used = await db.scalar(select(func.count()).select_from(Listing).where(Listing.city_id == obj.id))
    if used:
        raise HTTPException(status_code=409, detail="Город есть в объявлениях, лучше отключите его (is_active=false)")

    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Город удалён")
