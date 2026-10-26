from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from langchain_core.tools import tool

Placement = Literal["home", "internet_search", "listings", "category", "listing"]

_REQUIRED = (
    "title",
    "body",
    "image_url",
    "destination_url",
    "placement",
    "budget",
    "starts_at",
    "ends_at",
)


@tool("fill_advertising_campaign_fields")
def fill_advertising_campaign_fields(
    title: str | None = None,
    body: str | None = None,
    image_url: str | None = None,
    video_url: str | None = None,
    destination_url: str | None = None,
    placement: Placement | None = None,
    budget: Decimal | None = None,
    currency: str | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> dict:
    """Validate extracted ad draft fields and list information the user must supply.

    This tool only returns a draft. It never writes to the database, initiates
    payment, approves a campaign, or changes its publication status.
    """
    values = {
        "title": title,
        "body": body,
        "image_url": image_url,
        "video_url": video_url,
        "destination_url": destination_url,
        "placement": placement,
        "budget": str(budget) if budget is not None else None,
        "currency": currency.upper() if currency else None,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "ends_at": ends_at.isoformat() if ends_at else None,
    }
    missing = [name for name in _REQUIRED if values[name] is None]
    return {**values, "missing_fields": missing}
