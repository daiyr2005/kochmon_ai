from decimal import Decimal
import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fastapi.testclient import TestClient

from mysite.api.dependencies import require_admin
from mysite.database.ai_models import (AIBase, Category, Listing, ListingStatus, PromotionPayment,
                                       PromotionTariff, User, UserNotification)
from mysite.services.errors import ServiceError
from mysite.services.listing_service import create_listing, publish_listing
from mysite.services.user_notifications import notify_user
from mysite.api.routes.payments import confirm_promotion_payment
from mysite.config import Settings, get_settings
from mysite.services.listing_service import ensure_can_modify
from mysite.integrations.payment_providers import GenericProvider
from mysite.api.router import api_router
from mysite.services.google_oauth import resolve_frontend_redirect_url


@pytest_asyncio.fixture
async def dbmaker(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(AIBase.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.mark.asyncio
async def test_notification_deduplicates_event(dbmaker):
    async with dbmaker() as db:
        user = User(full_name="Owner")
        db.add(user)
        await db.flush()
        await notify_user(db, user.id, "test-event", "Title", "Body")
        await notify_user(db, user.id, "test-event", "Title", "Body")
        await db.commit()
        assert len((await db.scalars(__import__("sqlalchemy").select(UserNotification))).all()) == 1


@pytest.mark.asyncio
async def test_promotion_payment_activates_once_and_replay_is_safe(dbmaker):
    async with dbmaker() as db:
        user = User(full_name="Owner")
        category = Category(name="Stay", slug="stay")
        db.add_all([user, category])
        await db.flush()
        listing = Listing(owner_id=user.id, category_id=category.id, title="Cabin", status=ListingStatus.ACTIVE)
        tariff = PromotionTariff(code="week", name="Week", price=Decimal("10"), currency="KGS", duration_days=7)
        db.add_all([listing, tariff])
        await db.flush()
        payment = PromotionPayment(user_id=user.id, listing_id=listing.id, tariff_id=tariff.id,
                                  amount=Decimal("10"), currency="KGS", provider="generic")
        db.add(payment)
        await db.flush()
        await confirm_promotion_payment(db, payment, "event-1", Decimal("10"), "KGS", "provider-1", "paid")
        expiry = listing.promotion_ends_at
        await confirm_promotion_payment(db, payment, "event-1", Decimal("10"), "KGS", "provider-1", "paid")
        assert payment.status == "paid"
        assert listing.promotion_ends_at == expiry


@pytest.mark.asyncio
async def test_pending_payment_cannot_activate_on_failed_event(dbmaker):
    async with dbmaker() as db:
        user = User(full_name="Owner")
        category = Category(name="Stay", slug="stay")
        db.add_all([user, category])
        await db.flush()
        listing = Listing(owner_id=user.id, category_id=category.id, title="Cabin", status=ListingStatus.ACTIVE)
        tariff = PromotionTariff(code="week", name="Week", price=Decimal("10"), currency="KGS", duration_days=7)
        db.add_all([listing, tariff])
        await db.flush()
        payment = PromotionPayment(user_id=user.id, listing_id=listing.id, tariff_id=tariff.id,
                                  amount=Decimal("10"), currency="KGS", provider="generic")
        db.add(payment)
        await db.flush()
        await confirm_promotion_payment(db, payment, "event-fail", Decimal("10"), "KGS", None, "failed")
        assert payment.status == "failed"
        assert listing.promotion_ends_at is None


@pytest.mark.asyncio
async def test_listing_submission_enters_moderation(dbmaker):
    async with dbmaker() as db:
        from mysite.database.ai_models import Country, City
        country = Country(name="Kyrgyzstan", code="KGZ")
        category = Category(name="Stay", slug="stay")
        user = User(full_name="Owner")
        db.add_all([country, category, user])
        await db.flush()
        city = City(name="Bishkek", country_id=country.id)
        db.add(city)
        await db.flush()
        listing = await create_listing(db, user, {"category_id": category.id, "city_id": city.id,
                                                   "title": "Nice apartment", "description": "A good place",
                                                   "price": Decimal("100"), "currency": "KGS"}, None)
        submitted = await publish_listing(db, listing, None)
        assert submitted.status == ListingStatus.PENDING
        assert await db.scalar(__import__("sqlalchemy").select(UserNotification.id)) is not None


@pytest.mark.asyncio
async def test_admin_dependency_rejects_regular_user():
    with pytest.raises(ServiceError) as exc:
        await require_admin(User(id=7, full_name="User", role="user"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_listing_owner_is_enforced(dbmaker):
    async with dbmaker() as db:
        owner = User(full_name="Owner")
        other = User(full_name="Other")
        category = Category(name="Stay", slug="stay")
        db.add_all([owner, other, category])
        await db.flush()
        listing = Listing(owner_id=owner.id, category_id=category.id, title="Cabin", status="draft")
        db.add(listing)
        await db.flush()
        with pytest.raises(ServiceError) as exc:
            ensure_can_modify(listing, other)
        assert exc.value.status_code == 403


def test_dev_provider_is_rejected_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setenv("PAYMENT_PROVIDER", "dev")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="PAYMENT_PROVIDER=dev"):
        get_settings()
    get_settings.cache_clear()


def test_ollama_default_uses_docker_host_when_running_in_container(monkeypatch):
    monkeypatch.setattr("os.path.exists", lambda path: path == "/.dockerenv")
    settings = Settings()
    assert settings.ollama_base_url == "http://host.docker.internal:11434"


def test_signed_webhook_requires_valid_signature_and_event_id():
    secret = "test-webhook-secret"
    provider = GenericProvider(secret, "https://processor.invalid/checkout/{payment_id}")
    body = json.dumps({"payment_id": 12, "event_id": "evt-12", "status": "paid",
                       "amount": "10.00", "currency": "KGS"}).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    event = provider.parse_webhook({"x-signature": signature}, body)
    assert event.event_id == "evt-12"
    with pytest.raises(ServiceError):
        provider.parse_webhook({"x-signature": "invalid"}, body)


def test_google_frontend_redirect_falls_back_to_request_origin():
    base = resolve_frontend_redirect_url({"origin": "http://localhost:5173", "referer": "http://localhost:5173/"}, None)
    assert base == "http://localhost:5173"


def test_logout_endpoint_exists_and_clears_state_cookie():
    from main import app as entry_app
    client = TestClient(entry_app)
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.headers.get("set-cookie") is not None
