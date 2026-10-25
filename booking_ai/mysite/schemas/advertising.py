from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Placement = Literal["home", "internet_search", "listings", "category", "listing"]


class CampaignCreate(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=1, max_length=1000)
    image_url: HttpUrl
    destination_url: HttpUrl
    placement: Placement
    budget: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="KGS", min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def validate_period(self):
        if self.starts_at.tzinfo is None or self.ends_at.tzinfo is None:
            raise ValueError("Даты кампании должны содержать часовой пояс")
        if self.ends_at <= self.starts_at:
            raise ValueError("Дата окончания должна быть позже даты начала")
        return self


class CampaignDraftGenerateIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class CampaignDraftFields(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    body: str | None = Field(default=None, max_length=1000)
    image_url: HttpUrl | None = None
    destination_url: HttpUrl | None = None
    placement: Placement | None = None
    budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    missing_fields: list[str]


class CampaignUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=1000)
    image_url: HttpUrl | None = None
    destination_url: HttpUrl | None = None
    placement: Placement | None = None
    budget: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class ModerationDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    title: str
    body: str
    image_url: str
    destination_url: str
    placement: str
    budget: Decimal
    currency: str
    starts_at: datetime
    ends_at: datetime
    status: str
    paid_at: datetime | None
    moderation_reason: str | None
    created_at: datetime
    updated_at: datetime


class SponsoredCampaignOut(BaseModel):
    id: int
    title: str
    body: str
    image_url: str
    destination_url: str
    placement: str
    label: Literal["\u0420\u0435\u043a\u043b\u0430\u043c\u0430"] = "\u0420\u0435\u043a\u043b\u0430\u043c\u0430"
