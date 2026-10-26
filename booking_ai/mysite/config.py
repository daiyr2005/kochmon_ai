"""Настройки приложения из переменных окружения / .env (секреты только там)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEV_JWT_SECRET = "dev-only-secret-change-me-0000000000"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore",
                                      populate_by_name=True)

    app_name: str = "Booking AI"
    app_env: str = "development"
    domain: str | None = None
    # SQLite используется по умолчанию; DATABASE_URL можно задать для другого окружения.
    database_url: str = "sqlite+aiosqlite:///./booking_ai.db"

    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    bcrypt_rounds: int = 12

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str | None = None
    google_frontend_redirect_url: str | None = None

    blocked_words_path: Path = BASE_DIR / "data" / "blocked_words.txt"

    # первый администратор создаётся командой `python -m mysite.database.seed`, если заданы оба значения
    admin_email: str | None = None
    admin_password: str | None = None

    ollama_base_url: str = Field("http://127.0.0.1:11434", validation_alias=AliasChoices("OLLAMA_BASE_URL", "OLLAMA_URL"))
    ollama_model: str = "llama3.2:latest"
    ollama_timeout_seconds: float = 120.0
    ai_pending_ttl_seconds: int = 300      # сколько ждём ответ «да/нет» на подтверждение удаления
    search_provider: str = "tavily"
    tavily_api_key: str | None = None
    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None      # без @, нужен для ссылки привязки аккаунта
    telegram_webhook_secret: str | None = None    # для webhook-режима; в polling не нужен
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_verify_token: str | None = None
    whatsapp_app_secret: str | None = None
    whatsapp_template_name: str | None = None   # одобренный шаблон Meta для уведомлений вне 24-часового окна
    whatsapp_template_lang: str = "ru"
    whatsapp_api_version: str = "v21.0"
    redis_url: str = "redis://localhost:6379/0"

    # оплата тарифов: dev (только для разработки, "оплата" одной кнопкой) или generic (внешняя платёжка по webhook)
    payment_provider: str = "dev"
    payment_webhook_secret: str | None = None
    payment_checkout_url: str | None = None     # шаблон ссылки на оплату: {payment_id} {amount} {currency}

    # автоотправка уведомлений по подпискам
    scheduler_enabled: bool = True
    scheduler_interval_seconds: int = 300

    # за сколько дней до конца тарифа напоминать и (если включено автопродление) выставлять счёт
    plan_remind_days_before: int = 3

    # поиск в интернете: суточный лимит запросов на пользователя (Tavily платный)
    web_search_daily_limit: int = 20
    web_search_max_results: int = 5

    @model_validator(mode="after")
    def _build_database_url(self):
        if not self.database_url:
            self.database_url = "sqlite+aiosqlite:///./booking_ai.db"
        return self


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.jwt_secret:  # пустое значение из .env не должно становиться ключом подписи
        s.jwt_secret = DEV_JWT_SECRET
    if s.app_env.lower() == "production" and (s.jwt_secret == DEV_JWT_SECRET or len(s.jwt_secret) < 32):
        raise RuntimeError("В production задайте JWT_SECRET длиной не менее 32 символов.")
    if s.app_env.lower() == "production" and s.payment_provider == "dev":
        raise RuntimeError("В production нельзя PAYMENT_PROVIDER=dev: Pro включался бы без оплаты.")
    return s
