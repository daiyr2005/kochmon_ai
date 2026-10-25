from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.database.ai_models import User
from mysite.database.session import get_session
from mysite.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from mysite.services.errors import ServiceError
from mysite.services.security import (
    create_access_token,
    dummy_hash,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
async def register(data: RegisterIn, db: AsyncSession = Depends(get_session)):
    email = str(data.email).strip().lower()
    exists = await db.scalar(select(User.id).where(func.lower(User.email) == email))
    if exists is not None:
        raise ServiceError(409, "Пользователь с таким email уже зарегистрирован")

    user = User(
        full_name=data.full_name,
        email=email,
        password_hash=await asyncio.to_thread(hash_password, data.password),
        role="user",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
async def login(data: LoginIn, db: AsyncSession = Depends(get_session)):
    email = str(data.email).strip().lower()
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    password_hash = user.password_hash if user is not None else await asyncio.to_thread(dummy_hash)
    valid_password = await asyncio.to_thread(verify_password, data.password, password_hash)
    if user is None or not user.is_active or not valid_password:
        raise ServiceError(401, "Неверный email или пароль")
    return TokenOut(access_token=create_access_token(user.id))
