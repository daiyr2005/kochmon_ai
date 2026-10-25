from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from mysite.services.security import MAX_PASSWORD_BYTES


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str = Field(min_length=1, max_length=255)

    @field_validator("password")
    @classmethod
    def _password_len(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(f"Пароль не должен превышать {MAX_PASSWORD_BYTES} байт")
        return v


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    email: str | None
    role: str
    is_active: bool
    created_at: datetime


def _check_password_len(v: str | None) -> str | None:
    if v is not None and len(v.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Пароль не должен превышать {MAX_PASSWORD_BYTES} байт")
    return v


class UserSelfUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str | None = Field(None, min_length=1, max_length=255)
    password: str | None = Field(None, min_length=8)

    _password_len = field_validator("password")(_check_password_len)


class UserAdminCreate(RegisterIn):
    role: str = Field("user", pattern="^(user|admin)$")


class UserAdminUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str | None = Field(None, pattern="^(user|admin)$")
    is_active: bool | None = None
