# Kochmon AI backend: audit map and implementation plan

## Existing project map

- Runtime: FastAPI intended in `main.py`; async SQLAlchemy engine/session in `mysite/database/session.py`; configuration in `mysite/config.py`.
- API: routers are grouped in `mysite/api/router.py` and are intended to live under `/api`. Existing route modules cover users/auth, catalog, listings, local search, subscriptions, notifications, payments/plans, AI chat, and Telegram/WhatsApp webhooks.
- Business logic: listing, billing, AI chat, moderation, notifications, and provider adapters live under `mysite/services`; Ollama and Tavily clients are in `mysite/clients`.
- Database: `AIBase` currently defines users, catalog, listings, search subscriptions, basic notifications, moderation words, channel accounts, and link codes. The Alembic `versions` directory is empty.
- Tests: no test files were found in the project. Dependency manifest includes pytest/pytest-asyncio/aiosqlite, but there is no migration history or working test suite.

## Blocking inconsistencies found

1. `main.py` referenced an unrelated GoodsLogistics application and routers absent from this project.
2. `lifespan.py` and `seed.py` referenced missing `mysite.db` modules.
3. `mysite/api/routes/auth.py` referenced missing modules and passlib, which is not in the dependency manifest.
4. Several existing routers/services import model types absent from `ai_models.py` (including payment/plan and event types), so the API cannot import as a whole.
5. Current lifecycle uses `metadata.create_all` and seeding rather than Alembic migrations; no revision exists to safely upgrade a deployed database.
6. Payments default to a development provider with a client-callable success endpoint; no concrete external provider is configured.
7. Required domains such as advertising campaigns, booking inventory/availability, favorites, and persisted user preferences are not present in the current model layer.
8. Search implementation currently covers local listings; there is no general accommodation inventory provider configured.

## Safe implementation sequence

1. Establish the canonical schema from the intended deployed database and make an initial Alembic baseline without dropping existing data. Repair runtime imports and verify the API can load.
2. Repair and test auth, user profile, role enforcement, token/session lifecycle, and account recovery; preserve existing frontend contracts where they are actually in use.
3. Add missing domain models and migrations for favorites, settings, bookings/availability, and advertisement campaigns/payments only after checking the deployed schema.
4. Wire actual external providers from credentials/configuration, disable any success paths that do not represent a provider-confirmed transaction, and test webhook idempotency/signatures.
5. Implement and test real integrations/search sources; keep unsupported fields/results explicitly absent.
6. Add critical scenario tests, deployment configuration docs, and run migrations/tests against an isolated copy of the database.

## Changes made in this audit pass

- Replaced the unrelated `main.py` wiring with the Kochmon API router and lifecycle entry point.
- Corrected the seed module's sessionmaker import to the existing database package.
- Added startup construction of the app-scoped integrations/services in `lifespan.py`.

These repairs are not a production-ready completion: API import is still blocked by missing model classes and there is not enough schema history to create safe migrations for an existing database.
