# Frontend API guide

## Production connection

- API base URL: `https://api.kochmon.com.kg`
- OpenAPI / Swagger UI: `https://api.kochmon.com.kg/docs`
- OpenAPI JSON: `https://api.kochmon.com.kg/openapi.json`
- All application routes below are under `/api`.
- Use HTTPS. Do not append `/api` to `API_URL` if endpoint paths already start with `/api`.

```js
const API_URL = "https://api.kochmon.com.kg";
```

## Authentication and request format

Register and login are public. Login returns an access token; send it on protected requests:

```http
Authorization: Bearer <access_token>
Content-Type: application/json
```

Send JSON for normal create/update requests. For video upload send `FormData` and let the browser set the multipart content type and boundary. Timestamps use ISO 8601 with a timezone. JSON response models and exact request fields are defined in [openapi.json](openapi.json); `/docs` exposes the same live contract.

## Routes

### Auth

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/auth/google` | No | Google Start |
| `GET` | `/api/auth/google/callback` | No | Google Callback |
| `POST` | `/api/auth/register` | No | Register |
| `POST` | `/api/auth/login` | No | Login |

### Users

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/users/me` | Yes | Get Me |
| `DELETE` | `/api/users/me` | Yes | Delete Me |
| `PATCH` | `/api/users/me` | Yes | Update Me |
| `GET` | `/api/users/` | Yes | Get All |
| `POST` | `/api/users/` | Yes | Create |
| `GET` | `/api/users/{user_id}` | Yes | Get One |
| `PATCH` | `/api/users/{user_id}` | Yes | Update |
| `DELETE` | `/api/users/{user_id}` | Yes | Delete |

### Countries

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/countries/` | Yes | Get All |
| `POST` | `/api/countries/` | Yes | Create |
| `GET` | `/api/countries/{country_id}` | No | Get One |
| `PATCH` | `/api/countries/{country_id}` | Yes | Update |
| `DELETE` | `/api/countries/{country_id}` | Yes | Delete |

### Cities

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/cities/` | Yes | Get All |
| `POST` | `/api/cities/` | Yes | Create |
| `GET` | `/api/cities/{city_id}` | No | Get One |
| `PATCH` | `/api/cities/{city_id}` | Yes | Update |
| `DELETE` | `/api/cities/{city_id}` | Yes | Delete |

### Categories

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/categories/` | Yes | Get All |
| `POST` | `/api/categories/` | Yes | Create |
| `GET` | `/api/categories/tree` | No | Get Tree |
| `GET` | `/api/categories/{category_id}` | No | Get One |
| `PATCH` | `/api/categories/{category_id}` | Yes | Update |
| `DELETE` | `/api/categories/{category_id}` | Yes | Delete |

### Listings

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/listings/` | Yes | Get All |
| `POST` | `/api/listings/` | Yes | Create |
| `GET` | `/api/listings/{listing_id}` | Yes | Get One |
| `PATCH` | `/api/listings/{listing_id}` | Yes | Update |
| `DELETE` | `/api/listings/{listing_id}` | Yes | Delete |
| `POST` | `/api/listings/{listing_id}/publish` | Yes | Publish |
| `POST` | `/api/listings/{listing_id}/deactivate` | Yes | Deactivate |

### Favorites

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/favorites/` | Yes | List Favorites |
| `POST` | `/api/favorites/{listing_id}` | Yes | Add Favorite |
| `DELETE` | `/api/favorites/{listing_id}` | Yes | Remove Favorite |

### Search

| Method | Path | Token required | Description |
|---|---|---:|---|
| `POST` | `/api/search/` | No | Search |
| `GET` | `/api/search/history` | Yes | History |

### Subscriptions

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/subscriptions/` | Yes | Get All |
| `POST` | `/api/subscriptions/` | Yes | Create |
| `GET` | `/api/subscriptions/{subscription_id}` | Yes | Get One |
| `PATCH` | `/api/subscriptions/{subscription_id}` | Yes | Update |
| `DELETE` | `/api/subscriptions/{subscription_id}` | Yes | Delete |

### Notifications

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/notifications/` | Yes | Get All |
| `GET` | `/api/notifications/events` | Yes | Get Events |
| `GET` | `/api/notifications/plan` | Yes | Get Plan Notices |
| `GET` | `/api/notifications/{notification_id}` | Yes | Get One |
| `DELETE` | `/api/notifications/{notification_id}` | Yes | Delete |

### Advertising

| Method | Path | Token required | Description |
|---|---|---:|---|
| `POST` | `/api/advertising/videos` | Yes | Upload Ad Video |
| `POST` | `/api/advertising/campaigns/ai-draft` | Yes | Generate Campaign Draft |
| `POST` | `/api/advertising/campaigns` | Yes | Create Campaign |
| `GET` | `/api/advertising/campaigns/mine` | Yes | My Campaigns |
| `PATCH` | `/api/advertising/campaigns/{campaign_id}` | Yes | Update Campaign |
| `DELETE` | `/api/advertising/campaigns/{campaign_id}` | Yes | Delete Campaign |
| `POST` | `/api/advertising/campaigns/{campaign_id}/submit` | Yes | Submit Campaign |
| `GET` | `/api/advertising/campaigns/pending` | Yes | Pending Campaigns |
| `POST` | `/api/advertising/campaigns/{campaign_id}/approve` | Yes | Approve Campaign |
| `POST` | `/api/advertising/campaigns/{campaign_id}/reject` | Yes | Reject Campaign |
| `GET` | `/api/advertising/placements/{placement}` | No | Get Placement |

### Blocked-Words

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/blocked-words/` | Yes | Get All |
| `POST` | `/api/blocked-words/` | Yes | Create |
| `GET` | `/api/blocked-words/{word_id}` | Yes | Get One |
| `PATCH` | `/api/blocked-words/{word_id}` | Yes | Update |
| `DELETE` | `/api/blocked-words/{word_id}` | Yes | Delete |

### Plans

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/plans/` | Yes | Get All |
| `POST` | `/api/plans/` | Yes | Create |
| `GET` | `/api/plans/my` | Yes | Get My |
| `POST` | `/api/plans/my/auto-renew` | Yes | Set Auto Renew |
| `GET` | `/api/plans/{plan_id}` | No | Get One |
| `PATCH` | `/api/plans/{plan_id}` | Yes | Update |
| `DELETE` | `/api/plans/{plan_id}` | Yes | Delete |

### Payments

| Method | Path | Token required | Description |
|---|---|---:|---|
| `GET` | `/api/payments/` | Yes | Get All |
| `POST` | `/api/payments/` | Yes | Create |
| `GET` | `/api/payments/{payment_id}` | Yes | Get One |
| `DELETE` | `/api/payments/{payment_id}` | Yes | Delete |
| `POST` | `/api/payments/{payment_id}/dev-pay` | Yes | Dev Pay |

### Ai

| Method | Path | Token required | Description |
|---|---|---:|---|
| `POST` | `/api/ai/chat` | Yes | Chat |

### Channels

| Method | Path | Token required | Description |
|---|---|---:|---|
| `POST` | `/api/channels/telegram/link` | Yes | Telegram Link |
| `POST` | `/api/channels/whatsapp/link` | Yes | Whatsapp Link |
| `GET` | `/api/channels/` | Yes | My Channels |
| `DELETE` | `/api/channels/{account_id}` | Yes | Unlink Channel |

## Advertising video upload

1. Send `POST /api/advertising/videos` with the bearer token and `FormData` field named `file`.
2. The file must be MP4 or WebM and no larger than 18 MiB.
3. The response includes `video_url`; use that URL in the campaign JSON. `image_url` remains required as the poster image.
4. Accepted placement values: `home`, `internet_search`, `listings`, `category`, `listing`.

```js
const form = new FormData();
form.append("file", videoFile);
const uploaded = await fetch(`${API_URL}/api/advertising/videos`, {
  method: "POST",
  headers: { Authorization: `Bearer ${accessToken}` },
  body: form,
});
if (!uploaded.ok) throw new Error(`Upload failed: ${uploaded.status}`);
const { video_url } = await uploaded.json();
```

## Errors

Validation errors use HTTP `422`; authentication failures use `401`, access restrictions `403`, missing resources `404`, and conflicting state changes `409`. Error responses contain a `detail` field; validation errors may also include an `errors` array. Handle non-2xx responses before reading success data.

## Full machine-readable contract

The adjacent [openapi.json](openapi.json) contains all public frontend routes, request and response schemas, parameters, auth requirements, and the production server URL. Webhooks excluded from interactive OpenAPI are server-to-server integrations and should not be called by the browser.

For browser access, the deployed `CORS_ALLOW_ORIGINS` setting must include the frontend's exact origin (scheme and host, and port when non-default). The backend API origin is `https://api.kochmon.com.kg`; the frontend origin is a separate domain and should be supplied by the frontend deployment configuration.
