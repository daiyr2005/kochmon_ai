from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user_optional, require_admin
from mysite.database.ai_models import Country, Listing, User
from mysite.database.session import get_session
from mysite.schemas.catalog import CountryCreate, CountryOut, CountryUpdate
from mysite.schemas.common import MessageOut

router = APIRouter(prefix="/countries", tags=["countries"])


async def get_or_404(db: AsyncSession, country_id: int) -> Country:
    obj = await db.get(Country, country_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Страна не найдена")
    return obj


async def check_unique(db: AsyncSession, name: str | None, code: str | None, skip_id: int | None = None):
    if name:
        query = select(Country.id).where(Country.name == name)
        if skip_id:
            query = query.where(Country.id != skip_id)
        if await db.scalar(query):
            raise HTTPException(status_code=409, detail="Страна с таким названием уже есть")
    if code:
        query = select(Country.id).where(Country.code == code)
        if skip_id:
            query = query.where(Country.id != skip_id)
        if await db.scalar(query):
            raise HTTPException(status_code=409, detail="Страна с таким кодом уже есть")


@router.get("/", response_model=list[CountryOut])
async def get_all(
    include_inactive: bool = False,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    # отключённые страны видит только админ
    if include_inactive and (user is None or user.role != "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    query = select(Country).order_by(Country.name)
    if not include_inactive:
        query = query.where(Country.is_active.is_(True))
    return (await db.scalars(query)).all()


@router.get("/{country_id}", response_model=CountryOut)
async def get_one(country_id: int, db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, country_id)


@router.post("/", response_model=MessageOut[CountryOut], status_code=201)
async def create(data: CountryCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    await check_unique(db, data.name, data.code)

    obj = Country(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Страна добавлена", data=obj)


@router.patch("/{country_id}", response_model=MessageOut[CountryOut])
async def update(
    country_id: int,
    data: CountryUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    obj = await get_or_404(db, country_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    await check_unique(db, changes.get("name"), changes.get("code"), skip_id=obj.id)

    for field, value in changes.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Страна изменена", data=obj)


@router.delete("/{country_id}", response_model=MessageOut)
async def delete(country_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, country_id)

    used = await db.scalar(select(func.count()).select_from(Listing).where(Listing.country_id == obj.id))
    if used:
        raise HTTPException(status_code=409, detail="Страна есть в объявлениях, лучше отключите её (is_active=false)")

    await db.delete(obj)  # города удалятся вместе со страной
    await db.commit()
    return MessageOut(message="Страна удалена")
