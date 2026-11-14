# Event Registration System

A Django REST Framework backend for event publishing, ticket inventory holds, Paystack payments, and attendee registrations.

## MVP scope

- JWT authentication and organizer-controlled event management.
- Published events with ticket tiers and inventory validation.
- PostgreSQL persistence and Redis-backed temporary ticket holds (10-minute default).
- Paystack payment initialization, signed webhook validation, server-side verification, and reconciliation.
- Registration confirmation is performed by the successful-payment confirmation service.
- Registration listing, ownership checks, and cancellation of eligible pending registrations.

## Technology

- Python 3.13+
- Django 5.2 and Django REST Framework
- PostgreSQL 16
- Redis 7
- Paystack (NGN)

## Local setup (PowerShell)

1. Clone the repository and enter the backend directory:

   ```powershell
   cd backend
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   ```

2. Copy the root environment template and edit the placeholders:

   ```powershell
   Copy-Item ..\.env.example ..\.env
   ```

   Set a strong `DJANGO_SECRET_KEY`, local PostgreSQL password, and Paystack test secret. The Compose PostgreSQL port is 5433. The root `.env` is read by Django and Compose.

3. Start PostgreSQL and Redis from the repository root:

   ```powershell
   docker compose up -d db redis
   ```

4. From `backend`, run migrations and checks:

   ```powershell
   python manage.py migrate
   python manage.py check
   python manage.py test
   python manage.py runserver
   ```

The API is available at `http://127.0.0.1:8000/`.

## Main API routes

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/accounts/register/` | Create an account |
| POST | `/api/token/` | Obtain JWT access and refresh tokens |
| POST | `/api/token/refresh/` | Refresh an access token |
| GET/POST | `/api/events/` | List published events / create an event |
| GET/PATCH/DELETE | `/api/events/{id}/` | Retrieve or manage an event subject to organizer permissions |
| POST | `/api/ticketing/holds/` | Reserve ticket inventory temporarily |
| GET | `/api/ticketing/holds/{reference}/` | Retrieve the caller's hold |
| POST | `/api/ticketing/holds/{reference}/release/` | Release the caller's active hold |\n| GET | `/api/ticketing/tickets/{reference}/` | Retrieve the caller's issued ticket and QR SVG |\n| POST | `/api/ticketing/check-in/` | Organizer/staff scans and validates a signed QR token |
| POST | `/api/payments/initialize/` | Initialize Paystack for an owned hold |
| POST | `/api/payments/webhook/paystack/` | Receive signed Paystack webhooks |\n| POST | `/api/payments/refunds/{payment_reference}/issue/` | Staff-only initiation of a Paystack refund for a `REFUND_REQUIRED` payment |
| GET | `/api/registrations/` | List the caller's registrations |
| POST | `/api/registrations/{id}/cancel/` | Cancel an eligible pending registration |

All routes except public event reads, account registration, token endpoints, and the Paystack webhook require JWT authentication. Event mutation is restricted to the organizer or staff. Registrations cannot be created directly through the registration API; successful payment confirmation creates them.

## Payment reconciliation

Unresolved initialized or pending payments can be checked using:

```powershell
python manage.py reconcile_payments --minutes 1 --limit 100
```

Configure the Paystack webhook URL in the Paystack dashboard as:

`https://YOUR_PUBLIC_API_HOST/api/payments/webhook/paystack/`

Use HTTPS and a Paystack test key during development. Never commit `.env`, live API keys, database passwords, or production secrets.

## Email

The current repository does not yet include a durable queued email/outbox with retry handling. The environment template uses Django's console email backend for local development; do not treat this as production email delivery.

## Known MVP limitations

- Staff can initiate an actual Paystack refund for a `REFUND_REQUIRED` payment through `POST /api/payments/refunds/{payment_reference}/issue/`. The API records the provider response and marks a payment `REFUNDED` only when Paystack reports the refund as processed. Pending or uncertain refunds must be reconciled against the Paystack dashboard before any retry; the endpoint intentionally avoids duplicate submissions.
- QR ticket issuance and check-in are not yet implemented.
- Durable queued email delivery and retry handling are not yet implemented.
- Waitlists, advanced analytics, exports, and attendee self-service are outside this MVP.
- Production deployment, TLS termination, monitoring, backups, restore drills, and provider credentials must be configured and verified separately.

## Production configuration

Set `DJANGO_SETTINGS_MODULE=config.settings.production` and provide production values for `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, and `PAYSTACK_SECRET_KEY`. Serve only behind correctly configured HTTPS. Run:

```powershell
python manage.py check --deploy
```

Resolve all deployment warnings for the actual hosting environment before exposing the service publicly.
