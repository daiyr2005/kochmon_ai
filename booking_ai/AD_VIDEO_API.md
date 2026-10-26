# Advertising video API

Video files are uploaded through the authenticated backend endpoint:

```http
POST /api/advertising/videos
Authorization: Bearer <access-token>
Content-Type: multipart/form-data

file=<MP4 or WebM file>
```

The upload is limited to 18 MiB. Accepted MIME types are `video/mp4` and `video/webm`. A successful response contains `video_url`, `content_type`, and `size_bytes`. The URL is served by the existing Nginx `/media/` mapping.

Pass the returned `video_url` to `POST /api/advertising/campaigns` as an optional field. `PATCH /api/advertising/campaigns/{campaign_id}` can update it. Campaign responses, moderation responses, and `GET /api/advertising/placements/{placement}` include `video_url` (null for older/image-only campaigns).

`image_url` remains required and should be used as the still image/poster, preserving existing clients and placements. A video can be attached in addition to that poster. The server persists uploads under `media/ads` using generated filenames; the deployment's existing `/app/media` volume keeps them across container restarts. MP4 and WebM files are supported; this endpoint does not transcode video or generate posters.
