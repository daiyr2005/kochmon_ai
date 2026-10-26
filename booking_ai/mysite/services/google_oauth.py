from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
import jwt

from mysite.config import get_settings

GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"


class GoogleOAuthError(Exception):
    pass


def make_authorization_url(state: str) -> str:
    settings = get_settings()
    if not all((settings.google_client_id, settings.google_redirect_uri)):
        raise GoogleOAuthError("Google OAuth is not configured")
    return GOOGLE_AUTHORIZE + "?" + urlencode({
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })


async def exchange_and_verify(code: str) -> dict:
    settings = get_settings()
    if not all((settings.google_client_id, settings.google_client_secret, settings.google_redirect_uri)):
        raise GoogleOAuthError("Google OAuth is not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(GOOGLE_TOKEN, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            })
            response.raise_for_status()
            id_token = response.json()["id_token"]
            header = jwt.get_unverified_header(id_token)
            jwks_response = await client.get(GOOGLE_CERTS)
            jwks_response.raise_for_status()
            keys = jwks_response.json()["keys"]
        key_data = next(key for key in keys if key.get("kid") == header.get("kid"))
        key = jwt.PyJWK.from_dict(key_data).key
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"], audience=settings.google_client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
            options={"require": ["exp", "iat", "iss", "aud", "sub", "email", "email_verified"]},
        )
        if claims.get("email_verified") is not True:
            raise GoogleOAuthError("Google email is not verified")
        if not isinstance(claims.get("email"), str) or not claims["email"].strip():
            raise GoogleOAuthError("Google token has no email")
        return claims
    except GoogleOAuthError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, StopIteration, jwt.PyJWTError) as exc:
        raise GoogleOAuthError("Google authorization failed") from exc


def new_state() -> str:
    return secrets.token_urlsafe(32)
