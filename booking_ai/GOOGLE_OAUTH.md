# Google OAuth backend setup

## Google Cloud Console

1. Create/select a Google Cloud project and configure the OAuth consent screen (audience, application name, support email, and authorized domains as applicable).
2. Create an OAuth 2.0 Client ID of type **Web application**.
3. Add the deployed backend callback URL to **Authorized redirect URIs**. It must exactly match `GOOGLE_REDIRECT_URI`, including scheme, host, path, and trailing slash. For local development use `http://localhost:8000/api/auth/google/callback`.
4. Copy the client ID and client secret into the backend `booking_ai/.env`; never expose the secret to browser code.

## Backend environment

Set these variables in `booking_ai/.env`:

```dotenv
GOOGLE_CLIENT_ID=your-web-client-id
GOOGLE_CLIENT_SECRET=your-web-client-secret
GOOGLE_REDIRECT_URI=https://api.example.com/api/auth/google/callback
GOOGLE_FRONTEND_REDIRECT_URL=https://app.example.com/login
```

`GOOGLE_FRONTEND_REDIRECT_URL` is the fixed post-login frontend page. It must be configured by the backend operator; callback parameters cannot override it. Restart the backend after changing environment values.

## API flow

- `GET /api/auth/google`: redirects the browser to Google and sets a short-lived HttpOnly state cookie.
- Google returns the browser to `GET /api/auth/google/callback?code=…&state=…`. The backend checks state, exchanges the code, verifies the ID token signature using Google's published JWKS, and validates issuer, audience, expiry, and verified email.
- The backend creates or finds the local SQLite user by case-insensitive email and returns the browser to the configured frontend URL with `access_token` and `token_type=bearer` in the URL fragment. The fragment is not sent in HTTP requests or Referer headers. The frontend should read the fragment, persist/use the bearer token according to its existing session policy, then remove the fragment from browser history.
- OAuth failures return to the same frontend URL with `?error=invalid_state`, `?error=google_auth_failed`, or `?error=account_disabled` and do not include provider details or secrets.
- Existing `POST /api/auth/register` and `POST /api/auth/login` behavior is unchanged; all access tokens use the existing JWT format.

The OAuth client ID, secret, and redirect URI must belong to the same Google Web application client. Use HTTPS in production.
