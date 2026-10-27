from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.database.ai_models import UserNotification


async def notify_user(db: AsyncSession, user_id: int | None, event_key: str, title: str, body: str,
                      listing_id: int | None = None) -> None:
    if user_id is None:
        return
    exists = await db.scalar(select(UserNotification.id).where(UserNotification.event_key == event_key))
    if exists is None:
        db.add(UserNotification(user_id=user_id, event_key=event_key, title=title, body=body, listing_id=listing_id))


async def unread_count(db: AsyncSession, user_id: int) -> int:
    return await db.scalar(select(func.count()).select_from(UserNotification).where(
        UserNotification.user_id == user_id, UserNotification.read_at.is_(None))) or 0
