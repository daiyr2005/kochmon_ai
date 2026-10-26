from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_current_user, require_admin
from mysite.agents.advertising_draft import AdvertisingDraftError, generate_advertising_draft
from mysite.config import BASE_DIR, get_settings
from mysite.database.ai_models import AdvertisingCampaign, User
from mysite.database.session import get_session
from mysite.schemas.advertising import (
    CampaignCreate,
    CampaignDraftFields,
    CampaignDraftGenerateIn,
    CampaignOut,
    CampaignUpdate,
    ModerationDecision,
    Placement,
    SponsoredCampaignOut,
)

router = APIRouter(prefix="/advertising", tags=["advertising"])
log = logging.getLogger("booking_ai.advertising")

MAX_AD_VIDEO_BYTES = 18 * 1024 * 1024
VIDEO_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm"}


@router.post("/videos", status_code=201)
async def upload_ad_video(request: Request, file: UploadFile = File(...), user: User = Depends(get_current_user)):
    media_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    extension = VIDEO_TYPES.get(media_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Use an MP4 or WebM video")
    content = await file.read(MAX_AD_VIDEO_BYTES + 1)
    await file.close()
    if not content:
        raise HTTPException(status_code=400, detail="Video file is empty")
    if len(content) > MAX_AD_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="Video must be 18 MiB or smaller")
    filename = f"{uuid4().hex}{extension}"
    directory = BASE_DIR / "media" / "ads"
    directory.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread((directory / filename).write_bytes, content)
    settings = get_settings()
    if settings.app_env.lower() == "production" and settings.domain:
        origin = f"https://{settings.domain.strip().strip('/')}"
    else:
        origin = str(request.base_url).rstrip("/")
    video_url = f"{origin}/media/ads/{filename}"
    return {"video_url": video_url, "content_type": media_type,
            "size_bytes": len(content)}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/campaigns/ai-draft", response_model=CampaignDraftFields)
async def generate_campaign_draft(data: CampaignDraftGenerateIn, _: User = Depends(get_current_user)):
    text = data.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Текст для заполнения кампании не может быть пустым")
    try:
        return await generate_advertising_draft(text, get_settings())
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail="AI не успел обработать запрос") from exc
    except AdvertisingDraftError as exc:
        log.warning("AI returned invalid advertising draft")
        raise HTTPException(status_code=502, detail="AI не смог корректно заполнить черновик") from exc
    except Exception as exc:
        log.exception("Advertising draft model is unavailable")
        raise HTTPException(status_code=503, detail="AI-сервис временно недоступен") from exc


async def _owned_campaign(db: AsyncSession, campaign_id: int, owner_id: int) -> AdvertisingCampaign:
    campaign = await db.get(AdvertisingCampaign, campaign_id)
    if campaign is None or campaign.owner_id != owner_id:
        raise HTTPException(status_code=404, detail="РљР°РјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°")
    return campaign


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(data: CampaignCreate, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)):
    campaign = AdvertisingCampaign(
        **data.model_dump(exclude={"image_url", "video_url", "destination_url"}),
        image_url=str(data.image_url),
        video_url=str(data.video_url) if data.video_url else None,
        destination_url=str(data.destination_url),
        owner_id=user.id,
        status="draft",
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/campaigns/mine", response_model=list[CampaignOut])
async def my_campaigns(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_session)):
    result = await db.scalars(select(AdvertisingCampaign).where(
        AdvertisingCampaign.owner_id == user.id).order_by(AdvertisingCampaign.created_at.desc()))
    return result.all()


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: int, data: CampaignUpdate, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)):
    campaign = await _owned_campaign(db, campaign_id, user.id)
    if campaign.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Редактировать можно только черновик или отклонённую кампанию")
    changes = data.model_dump(exclude_unset=True)
    if "image_url" in changes and changes["image_url"] is not None:
        changes["image_url"] = str(changes["image_url"])
    if "video_url" in changes and changes["video_url"] is not None:
        changes["video_url"] = str(changes["video_url"])
    if "destination_url" in changes and changes["destination_url"] is not None:
        changes["destination_url"] = str(changes["destination_url"])
    for name, value in changes.items():
        if value is not None:
            setattr(campaign, name, value)
    campaign.status = "draft"
    campaign.moderation_reason = None
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/campaigns/{campaign_id}/submit", response_model=CampaignOut)
async def submit_campaign(campaign_id: int, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)):
    campaign = await _owned_campaign(db, campaign_id, user.id)
    if campaign.status not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="Кампания уже отправлена или обработана")
    campaign.status = "awaiting_payment" if campaign.paid_at is None else "pending_moderation"
    campaign.moderation_reason = None
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: int, user: User = Depends(get_current_user),
                          db: AsyncSession = Depends(get_session)):
    campaign = await _owned_campaign(db, campaign_id, user.id)
    if campaign.status not in {"draft", "rejected", "awaiting_payment"} or campaign.paid_at is not None:
        raise HTTPException(status_code=409, detail="Эту кампанию нельзя удалить")
    await db.delete(campaign)
    await db.commit()


@router.get("/campaigns/pending", response_model=list[CampaignOut])
async def pending_campaigns(_: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    result = await db.scalars(select(AdvertisingCampaign).where(
        AdvertisingCampaign.status == "pending_moderation").order_by(AdvertisingCampaign.created_at))
    return result.all()


@router.post("/campaigns/{campaign_id}/approve", response_model=CampaignOut)
async def approve_campaign(campaign_id: int, _: User = Depends(require_admin),
                           db: AsyncSession = Depends(get_session)):
    campaign = await db.get(AdvertisingCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="РљР°РјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°")
    if campaign.status != "pending_moderation" or campaign.paid_at is None:
        raise HTTPException(status_code=409, detail="Нужны подтверждённая оплата и статус ожидания модерации")
    campaign.status = "approved"
    campaign.moderation_reason = None
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.post("/campaigns/{campaign_id}/reject", response_model=CampaignOut)
async def reject_campaign(campaign_id: int, data: ModerationDecision, _: User = Depends(require_admin),
                          db: AsyncSession = Depends(get_session)):
    campaign = await db.get(AdvertisingCampaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="РљР°РјРїР°РЅРёСЏ РЅРµ РЅР°Р№РґРµРЅР°")
    if campaign.status != "pending_moderation":
        raise HTTPException(status_code=409, detail="Кампания не ожидает модерации")
    if not data.reason:
        raise HTTPException(status_code=422, detail="Укажите причину отклонения")
    campaign.status = "rejected"
    campaign.moderation_reason = data.reason
    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.get("/placements/{placement}", response_model=list[SponsoredCampaignOut])
async def get_placement(placement: Placement, limit: int = Query(default=5, ge=1, le=20),
                        db: AsyncSession = Depends(get_session)):
    now = _utcnow()
    result = await db.scalars(select(AdvertisingCampaign).where(
        AdvertisingCampaign.placement == placement,
        AdvertisingCampaign.status == "active",
        AdvertisingCampaign.paid_at.is_not(None),
        AdvertisingCampaign.starts_at <= now,
        AdvertisingCampaign.ends_at > now,
    ).order_by(AdvertisingCampaign.created_at.desc()).limit(limit))
    return [SponsoredCampaignOut.model_validate({
        "id": item.id, "title": item.title, "body": item.body,
        "image_url": item.image_url, "video_url": item.video_url, "destination_url": item.destination_url,
        "placement": item.placement,
    }) for item in result.all()]
