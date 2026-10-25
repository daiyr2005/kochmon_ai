from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user
from mysite.database.ai_models import Favorite, Listing, ListingStatus, User
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.listing import ListingOut

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("/", response_model=list[ListingOut])
async def list_favorites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    query = (
        select(Listing)
        .join(Favorite, Favorite.listing_id == Listing.id)
        .where(Favorite.user_id == user.id, Listing.status == ListingStatus.ACTIVE)
        .order_by(Favorite.created_at.desc())
    )
    return (await db.scalars(query)).all()


@router.post("/{listing_id}", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
async def add_favorite(
    listing_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    listing = await db.get(Listing, listing_id)
    if listing is None or listing.status not in (ListingStatus.ACTIVE, ListingStatus.EXTERNAL):
        raise HTTPException(status_code=404, detail="?????????? ?? ???????")
    existing = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id)
    )
    if existing is not None:
        return MessageOut(message="??? ????????? ? ?????????")
    db.add(Favorite(user_id=user.id, listing_id=listing_id))
    await db.commit()
    return MessageOut(message="????????? ? ?????????")


@router.delete("/{listing_id}", response_model=MessageOut)
async def remove_favorite(
    listing_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    favorite = await db.scalar(
        select(Favorite).where(Favorite.user_id == user.id, Favorite.listing_id == listing_id)
    )
    if favorite is None:
        raise HTTPException(status_code=404, detail="? ????????? ?????? ?????????? ???")
    await db.delete(favorite)
    await db.commit()
    return MessageOut(message="??????? ?? ??????????")
