from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from mysite.api.dependencies import get_current_user
from mysite.api.routes.advertising import MAX_AD_VIDEO_BYTES, router
from mysite.database.ai_models import User
import mysite.api.routes.advertising as advertising_routes


@pytest.fixture
def video_client(tmp_path, monkeypatch):
    monkeypatch.setattr(advertising_routes, 'BASE_DIR', tmp_path)
    app = FastAPI()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[get_current_user] = lambda: User(
        id=1, full_name='Uploader', email='uploader@example.com', role='user', is_active=True)
    return TestClient(app), tmp_path


def test_upload_ad_video_saves_file_and_returns_public_url(video_client):
    client, root = video_client
    response = client.post('/api/advertising/videos', files={
        'file': ('campaign.webm', b'video-bytes', 'video/webm;codecs=vp9')})
    assert response.status_code == 201
    payload = response.json()
    assert payload['video_url'].startswith('http://testserver/media/ads/')
    saved_file = root / 'media' / 'ads' / payload['video_url'].rsplit('/', 1)[-1]
    assert saved_file.read_bytes() == b'video-bytes'


def test_upload_ad_video_rejects_unsupported_content_type(video_client):
    client, _ = video_client
    response = client.post('/api/advertising/videos', files={
        'file': ('campaign.mov', b'video-bytes', 'video/quicktime')})
    assert response.status_code == 415


def test_upload_ad_video_rejects_oversized_file(video_client):
    client, _ = video_client
    response = client.post('/api/advertising/videos', files={
        'file': ('campaign.mp4', b'0' * (MAX_AD_VIDEO_BYTES + 1), 'video/mp4')})
    assert response.status_code == 413

def test_upload_ad_video_uses_configured_https_domain_in_production(video_client, monkeypatch):
    from mysite.config import get_settings
    client, _ = video_client
    settings = get_settings()
    monkeypatch.setattr(settings, 'app_env', 'production')
    monkeypatch.setattr(settings, 'domain', 'api.example.com')
    response = client.post('/api/advertising/videos', files={
        'file': ('campaign.mp4', b'video-bytes', 'video/mp4')})
    assert response.status_code == 201
    assert response.json()['video_url'].startswith('https://api.example.com/media/ads/')
