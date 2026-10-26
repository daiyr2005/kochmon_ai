from __future__ import annotations

import asyncio
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.database.ai_models import User
from mysite.database.session import get_session
from mysite.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut
from mysite.config import get_settings
from mysite.services.errors import ServiceError
from mysite.services.google_oauth import GoogleOAuthError, exchange_and_verify, make_authorization_url, new_state
from mysite.services.security import (
    create_access_token,
    dummy_hash,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/google")
async def google_start():
    state = new_state()
    try:
        url = make_authorization_url(state)
    except GoogleOAuthError as exc:
        raise ServiceError(503, "Google OAuth is not configured") from exc
    response = RedirectResponse(url, status_code=302)
    response.set_cookie("google_oauth_state", state, httponly=True,
                        secure=get_settings().app_env.lower() == "production", samesite="lax",
                        max_age=600, path="/api/auth/google/callback")
    return response


@router.get("/google/callback")
async def google_callback(request: Request, state: str | None = None, code: str | None = None,
                         error: str | None = None, db: AsyncSession = Depends(get_session)):
    frontend = get_settings().google_frontend_redirect_url
    if not frontend:
        raise ServiceError(503, "Google OAuth frontend redirect is not configured")
    response = RedirectResponse(frontend, status_code=303)
    response.delete_cookie("google_oauth_state", path="/api/auth/google/callback")
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    cookie_state = request.cookies.get("google_oauth_state")
    if not state or not cookie_state or not secrets.compare_digest(state, cookie_state):
        response.headers["location"] = frontend + "?" + urlencode({"error": "invalid_state"})
        return response
    if error or not code:
        response.headers["location"] = frontend + "?" + urlencode({"error": "google_auth_failed"})
        return response
    try:
        claims = await exchange_and_verify(code)
    except GoogleOAuthError:
        response.headers["location"] = frontend + "?" + urlencode({"error": "google_auth_failed"})
        return response
    email = claims["email"].strip().lower()
    user = await db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None:
        user = User(full_name=(claims.get("name") or email.split("@")[0])[:255], email=email,
                    password_hash=None, role="user", is_active=True)
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except Exception:
            await db.rollback()
            user = await db.scalar(select(User).where(func.lower(User.email) == email))
            if user is None:
                raise
    if not user.is_active:
        response.headers["location"] = frontend + "?" + urlencode({"error": "account_disabled"})
    else:
        response.headers["location"] = frontend + "?" + urlencode({"token": create_access_token(user.id)})
    return response


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
