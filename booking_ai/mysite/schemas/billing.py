from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mysite.schemas.search import CURRENCIES

Channel = Literal["api", "telegram", "whatsapp"]


class PlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    code: str = Field(pattern="^[a-z0-9_]{2,32}$")
    name: str = Field(min_length=1, max_length=64)
    price: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    currency: str = "KGS"
    duration_days: int = Field(30, ge=1, le=366)
    max_subscriptions: int = Field(1, ge=0, le=1000)
    min_frequency_minutes: int = Field(1440, ge=5, le=10080)
    channels: list[Channel] = ["api"]
    is_active: bool = True

    @field_validator("currency")
    @classmethod
    def check_currency(cls, v: str) -> str:
        v = v.upper()
        if v not in CURRENCIES:
            raise ValueError(f"Неподдерживаемая валюта: {v}")
        return v


class PlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(None, min_length=1, max_length=64)
    price: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)
    duration_days: int | None = Field(None, ge=1, le=366)
    max_subscriptions: int | None = Field(None, ge=0, le=1000)
    min_frequency_minutes: int | None = Field(None, ge=5, le=10080)
    channels: list[Channel] | None = None
    is_active: bool | None = None


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str
    price: Decimal
    currency: str
    duration_days: int
    max_subscriptions: int
    min_frequency_minutes: int
    channels: list[str]
    is_active: bool


class MyPlanOut(BaseModel):
    plan: PlanOut
    expires_at: datetime | None      # None у бесплатного тарифа
    is_paid: bool
    subscriptions_used: int
    auto_renew: bool = False


class AutoRenewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: int


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    amount: Decimal
    currency: str
    provider: str
    status: str
    checkout_url: str | None
    created_at: datetime
    paid_at: datetime | None
