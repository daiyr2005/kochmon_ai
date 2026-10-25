from __future__ import annotations

from fastapi import APIRouter

from mysite.api.routes import (advertising, ai, auth, blocked_words, categories, channels, cities, countries, favorites, listings,
                               notifications, payments, plans, search, subscriptions, telegram, users, whatsapp)

api_router = APIRouter(prefix="/api")
for module in (auth, users, countries, cities, categories, listings, favorites, search, subscriptions, notifications,
               advertising,
               blocked_words, plans, payments, ai, channels, telegram, whatsapp):
    api_router.include_router(module.router)
