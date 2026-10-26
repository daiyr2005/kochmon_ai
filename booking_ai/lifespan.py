import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import inspect, text

from mysite.config import get_settings
from mysite.database.ai_models import AIBase
from mysite.database.session import get_engine, get_sessionmaker, close_database
from mysite.database.seed import seed_all
from mysite.integrations.telegram import TelegramClient
from mysite.integrations.whatsapp import WhatsAppClient
from mysite.agents.runtime import build_runtime
from mysite.services.moderation_service import ModerationService
from mysite.integrations.payment_providers import build_provider
from mysite.services.moderation_service import (
    sync_blocked_words,
    load_terms_from_db,
)
from mysite.tasks.scheduler import build_senders, run_forever

logger = logging.getLogger("booking_ai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    app.state.moderation = ModerationService(path=settings.blocked_words_path)
    app.state.telegram = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    app.state.whatsapp = None
    if settings.whatsapp_access_token and settings.whatsapp_phone_number_id:
        app.state.whatsapp = WhatsAppClient(
            settings.whatsapp_access_token,
            settings.whatsapp_phone_number_id,
            template_name=settings.whatsapp_template_name,
            template_lang=settings.whatsapp_template_lang,
            api_version=settings.whatsapp_api_version,
        )
    app.state.payment_provider = build_provider(settings)
    app.state.ai = build_runtime(settings, app.state.moderation)

    try:
        # 1. Подготовка базы данных
        async with get_engine().begin() as connection:
            await connection.run_sync(AIBase.metadata.create_all)
            columns = await connection.run_sync(
                lambda sync_connection: {column["name"] for column in inspect(sync_connection).get_columns("advertising_campaigns")}
            )
            if "video_url" not in columns:
                await connection.execute(text("ALTER TABLE advertising_campaigns ADD COLUMN video_url VARCHAR(2048)"))

        await seed_all()
        logger.info("База данных готова.")

        # 2. Загрузка запрещённых слов
        try:
            async with get_sessionmaker()() as session:
                await sync_blocked_words(
                    session,
                    app.state.moderation,
                )
                terms = await load_terms_from_db(session)
                app.state.moderation.set_terms(terms)

            logger.info("Модерация загружена.")

        except Exception:
            logger.exception(
                "Не удалось загрузить запрещённые слова из БД."
            )

        # 3. Запуск планировщика
        if settings.scheduler_enabled:
            senders = build_senders(
                app.state.telegram,
                app.state.whatsapp,
            )

            scheduler = asyncio.create_task(
                run_forever(
                    get_sessionmaker(),
                    senders,
                    settings.scheduler_interval_seconds,
                    provider=app.state.payment_provider,
                    days_before=settings.plan_remind_days_before,
                )
            )

            logger.info("Планировщик запущен.")

        logger.info("Booking AI запущен.")

        yield

    finally:
        # 4. Остановка фоновой задачи
        if scheduler is not None:
            scheduler.cancel()

            try:
                await scheduler
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Ошибка остановки планировщика.")

        # 5. Закрытие HTTP-клиентов
        for name in ("telegram", "whatsapp"):
            client = getattr(app.state, name, None)

            if client is not None:
                try:
                    await client.aclose()
                except Exception:
                    logger.exception(
                        "Не удалось закрыть клиент %s.", name
                    )

        # 6. Закрытие базы данных
        try:
            await close_database()
        except Exception:
            logger.exception("Ошибка закрытия базы данных.")

        logger.info("Booking AI остановлен.")
