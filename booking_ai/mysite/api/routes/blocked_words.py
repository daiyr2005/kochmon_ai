from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mysite.api.dependencies import get_moderation, require_admin
from mysite.database.ai_models import BlockedWord, User
from mysite.database.session import get_session
from mysite.schemas.common import MessageOut
from mysite.schemas.subscription import BlockedWordCreate, BlockedWordOut, BlockedWordUpdate
from mysite.services import moderation_admin
from mysite.services.moderation_service import ModerationService

router = APIRouter(prefix="/blocked-words", tags=["blocked-words"])


async def get_or_404(db: AsyncSession, word_id: int) -> BlockedWord:
    obj = await db.get(BlockedWord, word_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="Слово не найдено")
    return obj


@router.get("/", response_model=list[BlockedWordOut])
async def get_all(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    query = select(BlockedWord).order_by(BlockedWord.id).offset(skip).limit(limit)
    return (await db.scalars(query)).all()


@router.get("/{word_id}", response_model=BlockedWordOut)
async def get_one(word_id: int, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    return await get_or_404(db, word_id)


@router.post("/", response_model=MessageOut[BlockedWordOut], status_code=201)
async def create(
    data: BlockedWordCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await moderation_admin.add_word(db, moderation, word=data.word, match_type=data.match_type,
                                          reason=data.reason)
    return MessageOut(message="Слово добавлено", data=obj)


@router.patch("/{word_id}", response_model=MessageOut[BlockedWordOut])
async def update(
    word_id: int,
    data: BlockedWordUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await get_or_404(db, word_id)
    obj = await moderation_admin.update_word(db, moderation, obj, data.model_dump(exclude_unset=True))
    return MessageOut(message="Слово изменено", data=obj)


@router.delete("/{word_id}", response_model=MessageOut)
async def delete(
    word_id: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    moderation: ModerationService = Depends(get_moderation),
):
    obj = await get_or_404(db, word_id)
    await moderation_admin.delete_word(db, moderation, obj)
    return MessageOut(message="Слово удалено")
