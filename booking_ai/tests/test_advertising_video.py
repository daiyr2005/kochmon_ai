from datetime import datetime, timezone, timedelta

from mysite.schemas.advertising import CampaignCreate, CampaignUpdate, SponsoredCampaignOut


def valid_campaign(**extra):
    start = datetime.now(timezone.utc)
    return {
        'title': 'Campaign', 'body': 'Ad text',
        'image_url': 'https://cdn.example.com/poster.jpg',
        'destination_url': 'https://example.com', 'placement': 'home',
        'budget': '10.00', 'starts_at': start,
        'ends_at': start + timedelta(days=1), **extra,
    }


def test_ad_campaign_keeps_image_only_payload_compatible():
    campaign = CampaignCreate.model_validate(valid_campaign())
    assert campaign.video_url is None


def test_ad_campaign_accepts_optional_video_url():
    campaign = CampaignCreate.model_validate(valid_campaign(video_url='https://cdn.example.com/ad.webm'))
    assert str(campaign.video_url) == 'https://cdn.example.com/ad.webm'
    update = CampaignUpdate.model_validate({'video_url': 'https://cdn.example.com/new.mp4'})
    assert str(update.video_url) == 'https://cdn.example.com/new.mp4'
    assert SponsoredCampaignOut.model_fields['video_url'].annotation == str | None
