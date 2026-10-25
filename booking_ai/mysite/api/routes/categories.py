from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user_optional, require_admin
from mysite.database.ai_models import Category, Listing, User
from mysite.database.session import get_session
from mysite.schemas.catalog import CategoryCreate, CategoryOut, CategoryTree, CategoryUpdate
from mysite.schemas.common import MessageOut

router = APIRouter(prefix="/categories", tags=["categories"])


async def get_or_404(db: AsyncSession, category_id: int) -> Category:
    obj = await db.get(Category, category_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return obj


async def check_slug(db: AsyncSession, slug: str, skip_id: int | None = None):
    query = select(Category.id).where(Category.slug == slug)
    if skip_id:
        query = query.where(Category.id != skip_id)
    if await db.scalar(query):
        raise HTTPException(status_code=409, detail="Категория с таким slug уже есть")


async def check_parent(db: AsyncSession, parent_id: int | None, own_id: int | None = None):
    if parent_id is None:
        return
    if await db.get(Category, parent_id) is None:
        raise HTTPException(status_code=422, detail="Родительская категория не найдена")

    # идём вверх по родителям, чтобы категория не попала сама в себя
    current = parent_id
    visited = set()
    while current is not None and current not in visited:
        if current == own_id:
            raise HTTPException(status_code=422, detail="Категорию нельзя вложить саму в себя")
        visited.add(current)
        current = await db.scalar(select(Category.parent_id).where(Category.id == current))


@router.get("/", response_model=list[CategoryOut])
async def get_all(
    parent_id: int | None = None,
    include_inactive: bool = False,
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_session),
):
    if include_inactive and (user is None or user.role != "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

    query = select(Category).order_by(Category.name, Category.id)
    if parent_id:
        query = query.where(Category.parent_id == parent_id)
    if not include_inactive:
        query = query.where(Category.is_active.is_(True))
    return (await db.scalars(query)).all()


# должен стоять выше /{category_id}, иначе "tree" примется за id
@router.get("/tree", response_model=list[CategoryTree])
async def get_tree(db: AsyncSession = Depends(get_session)):
    query = select(Category).where(Category.is_active.is_(True)).order_by(Category.name, Category.id)
    categories = (await db.scalars(query)).all()

    nodes = {}
    for c in categories:
        nodes[c.id] = {"id": c.id, "name": c.name, "slug": c.slug, "description": c.description,
                       "is_active": c.is_active, "children": []}

    roots = []
    for c in categories:
        parent = nodes.get(c.parent_id)
        if parent:
            parent["children"].append(nodes[c.id])
        else:
            roots.append(nodes[c.id])
    return roots


@router.get("/{category_id}", response_model=CategoryOut)
async def get_one(category_id: int, db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, category_id)


@router.post("/", response_model=MessageOut[CategoryOut], status_code=201)
async def create(data: CategoryCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    await check_slug(db, data.slug)
    await check_parent(db, data.parent_id)

    obj = Category(**data.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Категория добавлена", data=obj)


@router.patch("/{category_id}", response_model=MessageOut[CategoryOut])
async def update(
    category_id: int,
    data: CategoryUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    obj = await get_or_404(db, category_id)
    changes = data.model_dump(exclude_unset=True)

    # эти поля нельзя обнулить
    for field in ("name", "slug", "is_active"):
        if field in changes and changes[field] is None:
            del changes[field]

    if "slug" in changes:
        await check_slug(db, changes["slug"], skip_id=obj.id)
    if "parent_id" in changes:
        await check_parent(db, changes["parent_id"], own_id=obj.id)

    for field, value in changes.items():
        setattr(obj, field, value)

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Категория изменена", data=obj)


@router.delete("/{category_id}", response_model=MessageOut)
async def delete(category_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, category_id)

    children = await db.scalar(select(func.count()).select_from(Category).where(Category.parent_id == obj.id))
    listings = await db.scalar(select(func.count()).select_from(Listing).where(Listing.category_id == obj.id))
    if children or listings:
        raise HTTPException(status_code=409, detail="В категории есть вложенные категории или объявления, лучше отключите её")

    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Категория удалена")
