from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user
from mysite.database.ai_models import User, WebSearchLog
from mysite.database.session import get_session
from mysite.schemas.listing import ListingOut
from mysite.schemas.search import SearchFilters
from mysite.services import listing_service as svc

router = APIRouter(prefix="/search", tags=["search"])


class SearchOut(BaseModel):
    items: list[ListingOut]
    warnings: list[str] = []
    applied_filters: dict


@router.post("/", response_model=SearchOut)
async def search(filters: SearchFilters, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
                 session: AsyncSession = Depends(get_session)):
    """Поиск по локальной базе. Поиск в интернете подключается отдельным этапом (SearchProvider)."""
    data = filters.model_dump(mode="json", exclude_none=True)
    items, warnings = await svc.search_listings(session, filters, limit=limit, offset=offset)
    return SearchOut(items=items, warnings=warnings, applied_filters=data)


class WebSearchLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    query: str
    results_count: int
    created_at: datetime


@router.get("/history", response_model=list[WebSearchLogOut])
async def history(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    """Ваши поиски в интернете через ассистента (по ним же считается суточный лимит)."""
    query = (select(WebSearchLog).where(WebSearchLog.user_id == user.id)
             .order_by(WebSearchLog.id.desc()).offset(skip).limit(limit))
    return (await db.scalars(query)).all()
