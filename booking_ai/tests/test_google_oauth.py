import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from mysite.config import get_settings
from mysite.database.ai_models import AIBase, User
from mysite.database.session import get_session
from fastapi import FastAPI
from mysite.api.routes.auth import router as auth_router
app = FastAPI()
app.include_router(auth_router, prefix="/api")
from mysite.services.google_oauth import GoogleOAuthError
import mysite.api.routes.auth as auth_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'oauth.db'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(AIBase.metadata.create_all)
    asyncio.run(setup())

    async def session_dependency():
        async with maker() as db:
            yield db

    app.dependency_overrides[get_session] = session_dependency
    settings = get_settings()
    monkeypatch.setattr(settings, 'google_client_id', 'test-client')
    monkeypatch.setattr(settings, 'google_client_secret', 'test-secret')
    monkeypatch.setattr(settings, 'google_redirect_uri', 'http://testserver/api/auth/google/callback')
    monkeypatch.setattr(settings, 'google_frontend_redirect_url', 'http://localhost:3000/login')
    with TestClient(app) as test_client:
        yield test_client, maker
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def begin(client):
    response = client.get('/api/auth/google', follow_redirects=False)
    assert response.status_code == 302
    state = parse_qs(urlparse(response.headers['location']).query)['state'][0]
    return state


def test_google_start_redirects_and_sets_state_cookie(client):
    c, _ = client
    response = c.get('/api/auth/google', follow_redirects=False)
    assert response.status_code == 302
    assert 'google_oauth_state' in response.cookies
    assert 'openid+email+profile' in response.headers['location']


def test_google_callback_rejects_invalid_state(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(auth_routes, 'exchange_and_verify', lambda code: pytest.fail('must not call Google'))
    begin(c)
    response = c.get('/api/auth/google/callback?state=wrong&code=code', follow_redirects=False)
    assert 'error=invalid_state' in response.headers['location']


def test_google_callback_creates_user_and_returns_existing_jwt(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(auth_routes, 'exchange_and_verify', lambda code: asyncio.sleep(0, result={
        'email': 'person@example.com', 'email_verified': True, 'name': 'Person'}))
    state = begin(c)
    response = c.get(f'/api/auth/google/callback?state={state}&code=mock', follow_redirects=False)
    assert 'access_token=' in response.headers['location']
    assert 'token_type=bearer' in response.headers['location']


def test_google_callback_reuses_same_email_user(client, monkeypatch):
    c, maker = client
    async def seed():
        async with maker() as db:
            db.add(User(full_name='Existing', email='person@example.com', password_hash='old-hash'))
            await db.commit()
    asyncio.run(seed())
    monkeypatch.setattr(auth_routes, 'exchange_and_verify', lambda code: asyncio.sleep(0, result={
        'email': 'PERSON@example.com', 'email_verified': True, 'name': 'Google Name'}))
    state = begin(c)
    response = c.get(f'/api/auth/google/callback?state={state}&code=mock', follow_redirects=False)
    assert 'access_token=' in response.headers['location']
    async def count():
        async with maker() as db:
            from sqlalchemy import func, select
            return await db.scalar(select(func.count(User.id)).where(func.lower(User.email) == 'person@example.com'))
    assert asyncio.run(count()) == 1


@pytest.mark.parametrize('failure', ['invalid token', 'unverified email', 'Google API error'])
def test_google_callback_handles_google_failures(client, monkeypatch, failure):
    c, _ = client
    async def rejected(code):
        raise GoogleOAuthError(failure)
    monkeypatch.setattr(auth_routes, 'exchange_and_verify', rejected)
    state = begin(c)
    response = c.get(f'/api/auth/google/callback?state={state}&code=mock', follow_redirects=False)
    assert 'error=google_auth_failed' in response.headers['location']

import asyncio
from types import SimpleNamespace

import httpx
import jwt
import pytest

import mysite.services.google_oauth as google_oauth


class MockResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status
    def raise_for_status(self):
        if self.status >= 400:
            request = httpx.Request('POST', 'https://oauth2.googleapis.com/token')
            response = httpx.Response(self.status, request=request)
            raise httpx.HTTPStatusError('mock Google error', request=request, response=response)
    def json(self):
        return self.data


class MockGoogleClient:
    def __init__(self, *args, **kwargs):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    async def post(self, url, data):
        assert url == google_oauth.GOOGLE_TOKEN
        assert data['grant_type'] == 'authorization_code'
        assert data['client_secret'] == 'test-secret'
        return MockResponse({'id_token': 'mock.id.token'})
    async def get(self, url):
        assert url == google_oauth.GOOGLE_CERTS
        return MockResponse({'keys': [{'kid': 'mock-kid', 'kty': 'RSA'}]})


@pytest.mark.parametrize('claims, raises, expected_error', [
    ({'sub': '123', 'email': 'ok@example.com', 'email_verified': True}, None, None),
    ({}, jwt.InvalidSignatureError('bad signature'), GoogleOAuthError),
    ({'sub': '123', 'email': 'no@example.com', 'email_verified': False}, None, GoogleOAuthError),
])
def test_google_token_signature_and_claim_validation(monkeypatch, claims, raises, expected_error):
    settings = get_settings()
    monkeypatch.setattr(settings, 'google_client_id', 'test-client')
    monkeypatch.setattr(settings, 'google_client_secret', 'test-secret')
    monkeypatch.setattr(settings, 'google_redirect_uri', 'http://testserver/api/auth/google/callback')
    monkeypatch.setattr(google_oauth.httpx, 'AsyncClient', MockGoogleClient)
    monkeypatch.setattr(google_oauth.jwt, 'get_unverified_header', lambda token: {'kid': 'mock-kid'})
    monkeypatch.setattr(google_oauth.jwt.PyJWK, 'from_dict', lambda data: SimpleNamespace(key='mock-key'))
    def decode(token, key, **kwargs):
        assert key == 'mock-key'
        assert kwargs['algorithms'] == ['RS256']
        assert kwargs['audience'] == 'test-client'
        assert kwargs['issuer'] == ['https://accounts.google.com', 'accounts.google.com']
        if raises:
            raise raises
        return dict(claims, aud='test-client', iss='https://accounts.google.com')
    monkeypatch.setattr(google_oauth.jwt, 'decode', decode)
    if expected_error:
        with pytest.raises(expected_error):
            asyncio.run(google_oauth.exchange_and_verify('mock-code'))
    else:
        result = asyncio.run(google_oauth.exchange_and_verify('mock-code'))
        assert result['email'] == 'ok@example.com'
