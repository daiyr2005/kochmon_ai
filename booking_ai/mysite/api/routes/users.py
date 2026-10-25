import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, require_admin
from mysite.database.ai_models import User
from mysite.database.session import get_session
from mysite.schemas.auth import UserAdminCreate, UserAdminUpdate, UserOut, UserSelfUpdate
from mysite.schemas.common import MessageOut
from mysite.services.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


async def get_or_404(db: AsyncSession, user_id: int) -> User:
    obj = await db.get(User, user_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return obj


# /me стоит выше /{user_id}, иначе "me" примется за id
@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=MessageOut[UserOut])
async def update_me(
    data: UserSelfUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    changes = data.model_dump(exclude_unset=True)
    if changes.get("full_name"):
        user.full_name = changes["full_name"]
    if changes.get("password"):
        user.password_hash = await asyncio.to_thread(hash_password, changes["password"])

    await db.commit()
    await db.refresh(user)
    return MessageOut(message="Данные изменены", data=user)


@router.delete("/me", response_model=MessageOut)
async def delete_me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    await db.delete(user)
    await db.commit()
    return MessageOut(message="Аккаунт удалён")


@router.get("/", response_model=list[UserOut])
async def get_all(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    return (await db.scalars(select(User).order_by(User.id).offset(skip).limit(limit))).all()


@router.get("/{user_id}", response_model=UserOut)
async def get_one(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, user_id)


@router.post("/", response_model=MessageOut[UserOut], status_code=201)
async def create(data: UserAdminCreate, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    email = data.email.lower()
    if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже есть")

    obj = User(
        full_name=data.full_name,
        email=email,
        role=data.role,
        password_hash=await asyncio.to_thread(hash_password, data.password),
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Пользователь добавлен", data=obj)


@router.patch("/{user_id}", response_model=MessageOut[UserOut])
async def update(
    user_id: int,
    data: UserAdminUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    obj = await get_or_404(db, user_id)

    # админ не должен случайно отключить или понизить сам себя
    if obj.id == admin.id and (data.role == "user" or data.is_active is False):
        raise HTTPException(status_code=409, detail="Нельзя понизить или отключить самого себя")

    if data.role is not None:
        obj.role = data.role
    if data.is_active is not None:
        obj.is_active = data.is_active

    await db.commit()
    await db.refresh(obj)
    return MessageOut(message="Пользователь изменён", data=obj)


@router.delete("/{user_id}", response_model=MessageOut)
async def delete(user_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, user_id)
    if obj.id == admin.id:
        raise HTTPException(status_code=409, detail="Нельзя удалить самого себя")

    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Пользователь удалён")
