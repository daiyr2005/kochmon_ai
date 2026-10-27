from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user
from mysite.database.ai_models import EventNotification, ListingEvent, Notification, PlanNotice, User, UserNotification
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.subscription import EventNotificationOut, NotificationOut, PlanNoticeOut
from mysite.services.user_notifications import unread_count

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/inbox")
async def get_inbox(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    items = await db.scalars(select(UserNotification).where(UserNotification.user_id == user.id)
                              .order_by(UserNotification.id.desc()).offset(skip).limit(limit))
    return {"unread_count": await unread_count(db, user.id), "items": items.all()}


@router.get("/unread-count")
async def get_unread_count(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return {"count": await unread_count(db, user.id)}


@router.post("/inbox/{notification_id}/read")
async def mark_read(notification_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    item = await db.get(UserNotification, notification_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(404, "Notification not found")
    item.read_at = item.read_at or datetime.now(timezone.utc)
    await db.commit()
    return {"ok": True}


async def get_or_404(db: AsyncSession, notification_id: int, user: User) -> Notification:
    obj = await db.get(Notification, notification_id)
    # чужое уведомление не показываем, как будто его нет
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    return obj


@router.get("/", response_model=list[NotificationOut])
async def get_all(
    status: str | None = Query(None, pattern="^(pending|sent|failed)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    query = select(Notification).where(Notification.user_id == user.id)
    if status:
        query = query.where(Notification.status == status)
    query = query.order_by(Notification.id.desc()).offset(skip).limit(limit)
    return (await db.scalars(query)).all()


# /events и /plan стоят выше /{notification_id}, иначе слово примется за id
@router.get("/events", response_model=list[EventNotificationOut])
async def get_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Предупреждения о смене цены и снятии объявлений, которые вам раньше присылали."""
    query = (select(EventNotification, ListingEvent)
             .join(ListingEvent, ListingEvent.id == EventNotification.event_id)
             .where(EventNotification.user_id == user.id)
             .order_by(EventNotification.id.desc()).offset(skip).limit(limit))
    return [EventNotificationOut(
        id=n.id, kind=e.kind, listing_id=e.listing_id, title=e.title, old_price=e.old_price, new_price=e.new_price,
        old_currency=e.old_currency, currency=e.currency, source_url=e.source_url, channel=n.channel,
        status=n.status, created_at=n.created_at, sent_at=n.sent_at) for n, e in (await db.execute(query)).all()]


@router.get("/plan", response_model=list[PlanNoticeOut])
async def get_plan_notices(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
):
    """Сообщения о тарифе: скоро закончится, счёт на продление, продлён, не удалось списать."""
    query = (select(PlanNotice).where(PlanNotice.user_id == user.id)
             .order_by(PlanNotice.id.desc()).offset(skip).limit(limit))
    return (await db.scalars(query)).all()


@router.get("/{notification_id}", response_model=NotificationOut)
async def get_one(notification_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, notification_id, user)


# уведомления создаёт сама система, поэтому POST и PATCH тут не нужны
@router.delete("/{notification_id}", response_model=MessageOut)
async def delete(notification_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    obj = await get_or_404(db, notification_id, user)
    await db.delete(obj)
    await db.commit()
    return MessageOut(message="Уведомление удалено")
