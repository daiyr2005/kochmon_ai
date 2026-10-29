# Standalone Telegram, AI, and search API

This service runs the copied route modules in `routes/` as a separate FastAPI
application. It reuses the parent project's models, integrations, settings,
and shared application lifespan, so build it from the `booking_ai` directory
as configured in `docker-compose.yml`.

## Run with Docker Compose

From this directory:

```powershell
docker compose up -d --build
```

The API listens on port `8001` by default. Set `ROUTES_API_PORT` to change the
host port. The service reads `booking_ai/.env` and stores its separate SQLite
database under this directory's `data/` folder.

Endpoints include `/health`, `/api/ai/chat`, `/api/search/`,
`/api/search/history`, and `/api/telegram/webhook`.
