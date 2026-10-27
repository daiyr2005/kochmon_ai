from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from mysite.database.ai_models import Listing
from mysite.services.user_notifications import notify_user


async def run_promotion_notice_cycle(maker) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    async with maker() as db:
        expiring = (await db.scalars(select(Listing).where(
            Listing.promotion_ends_at > now, Listing.promotion_ends_at <= now + timedelta(days=1)))).all()
        ended = (await db.scalars(select(Listing).where(
            Listing.promotion_ends_at.is_not(None), Listing.promotion_ends_at <= now,
            Listing.status != "external"))).all()
        for item in expiring:
            await notify_user(db, item.owner_id, f"promotion:{item.id}:soon:{item.promotion_ends_at.isoformat()}",
                              "Срок рекламы скоро закончится", item.title, item.id)
        for item in ended:
            await notify_user(db, item.owner_id, f"promotion:{item.id}:ended:{item.promotion_ends_at.isoformat()}",
                              "Срок рекламы завершился", item.title, item.id)
        await db.commit()
        return {"promotion_expiring": len(expiring), "promotion_ended": len(ended)}
