# Listing promotion payments

Promotion tariffs are stored in `promotion_tariffs` and can be managed by an authenticated administrator at `/admin/promotion-tariffs`. The client sends only a tariff ID; the server reads the amount, currency, and duration from the database.

`PAYMENT_PROVIDER=dev` creates no external charge and is intended only for local testing. Application settings reject this provider when `APP_ENV=production`.

For a real Google Pay checkout, configure Google Pay in a supported processor (for example, an acquiring bank or PSP that accepts Google Pay) and implement that processor's checkout creation, status lookup, and webhook signature verification in `mysite/integrations/payment_providers.py`. Google Pay itself is a wallet/tokenization method, not a payment processor. This project deliberately does not invent processor endpoints or credentials. The current `generic` adapter is a signed webhook/checkout URL interface and is not a ready-made Google Pay processor integration.

Configure:

```env
PAYMENT_PROVIDER=generic
PAYMENT_WEBHOOK_SECRET=<processor webhook signing secret>
PAYMENT_CHECKOUT_URL=<processor checkout URL template with {payment_id}, {amount}, and {currency}>
```

The processor must send an HMAC-SHA256 `X-Signature` over the raw request body to `POST /api/payments/promotions/webhook`; the JSON event must include `payment_id`, unique `event_id`, `status`, `amount`, `currency`, and optionally `provider_payment_id`. A provider-specific adapter should replace this generic payload mapping where required. Never use the checkout return URL to confirm payment. Do not send card details to this application.

Before serving production traffic, use Alembic (`alembic upgrade head`) against the configured database. Startup also applies additive compatibility columns for the existing SQLite deployment path.
