# External Integrations

**Analysis Date:** 2026-04-07

## APIs & External Services

**Messaging — Meta WhatsApp Cloud API:**
- Service: Meta Graph API v19.0 (`https://graph.facebook.com/v19.0`)
- Purpose: Receive and send WhatsApp messages on behalf of the business number
- SDK/Client: `httpx` (async, custom `MetaAPIClient` class at `app/meta_api.py`)
- Auth: Bearer token via env var `WHATSAPP_TOKEN` (also referenced as `META_ACCESS_TOKEN`)
- Webhook verification: HMAC-SHA256 signature on `X-Hub-Signature-256` header, verified in `app/meta_api.py:verify_signature`
- Capabilities used:
  - `send_text` — plain text messages to patients
  - `send_template` — pre-approved WhatsApp templates for remarketing
  - Media download via `/{media_id}` endpoint (images, PDFs, audio files) in `app/media_handler.py`

**AI — Anthropic Claude:**
- Service: Anthropic Messages API
- Purpose: Two distinct uses —
  1. Intent classification (Orchestrator): `claude-haiku-4-5-20251001` classifies every inbound message into one of 8 intents, returns JSON (`app/agents/orchestrator.py`)
  2. Response generation fallback: when Gemini confidence < 0.6, Claude Haiku generates the reply (`app/ai_engine.py`)
- SDK/Client: `anthropic` Python SDK (`>= 0.50.0`)
- Auth: `ANTHROPIC_API_KEY` env var
- Max tokens: 100 (classification), 500 (response generation)

**AI — Google Gemini:**
- Service: Google Generative AI API
- Purpose: Primary response generator in `AIEngine` (`app/ai_engine.py`); uses `gemini-2.0-flash` with `response_mime_type: application/json`
- SDK/Client: `google-generativeai 0.8.6`
- Auth: `GEMINI_API_KEY` env var
- Note: Gemini is primary; Claude is the fallback when Gemini returns low confidence or fails

**AI — OpenAI Whisper (optional):**
- Service: OpenAI Audio Transcriptions API (`https://api.openai.com/v1/audio/transcriptions`)
- Purpose: Transcribe voice messages received via WhatsApp into text (`app/media_handler.py`)
- SDK/Client: `httpx` (direct HTTP, no SDK)
- Auth: `OPENAI_API_KEY` env var
- Model: `whisper-1`, language forced to `pt` (Portuguese)
- Note: Optional — if `OPENAI_API_KEY` is absent, audio messages are skipped silently

**Nutrition Platform — Dietbox:**
- Service: Dietbox REST API v2 (`https://api.dietbox.me/v2`)
- Purpose: Full patient lifecycle management (`app/agents/dietbox_worker.py`):
  - `GET /local-atendimento` — fetch clinic locations (presencial/online)
  - `GET /agenda` — fetch scheduled appointments to find free slots
  - `GET /patients`, `POST /patients` — search and register patients
  - `POST /agenda` — book appointments
  - `POST /finance/transactions` — record financial entries
  - `PATCH /finance/transactions/{id}` — mark payments as paid
- SDK/Client: `requests` (sync, called inside `ThreadPoolExecutor`)
- Auth: Bearer token obtained via Playwright browser automation (Azure AD B2C login at `https://dietbox.me/pt-BR/Account/LoginB2C?role=nutritionist`)
  - Token cached to `dietbox_token_cache.json` with 1-hour TTL (300s safety margin)
  - If cache is invalid, `_login_playwright()` re-authenticates
- Auth env vars: `DIETBOX_EMAIL`, `DIETBOX_SENHA`
- Optional overrides: `DIETBOX_ID_LOCAL_PRESENCIAL`, `DIETBOX_ID_LOCAL_ONLINE` (auto-detected from API on first call)

**Payment Gateway — Rede:**
- Service: Rede merchant portal (`https://meu.userede.com.br`)
- Purpose: Generate payment links for credit card installment payments (`app/agents/rede_worker.py`)
- SDK/Client: Playwright browser automation (no official API SDK available)
  - Portal requires `headless=False` — reCAPTCHA blocks headless Chromium
  - Flow: login → navigate to `/link-pagamento` → fill form → intercept API response to capture URL
  - Link created with 7-day expiry; installments set per plan (2x to 10x)
- Auth env vars: `REDE_EMAIL`, `REDE_SENHA`
- Merchant code `_PV = "101801637"` hardcoded in `app/agents/rede_worker.py`
- Note: `.env.example` also references `REDE_PV` and `REDE_TOKEN` for a potential official API path not yet implemented

**Payment — PIX (manual):**
- No API integration — PIX is handled by informing patients of the CPF key (`14994735670`, hardcoded in `app/knowledge_base.py`)
- Payment confirmation is tracked manually: patients send proof, agent marks `pago=True` in Dietbox via `confirmar_pagamento()` in `app/agents/dietbox_worker.py`

## Data Storage

**Databases:**
- PostgreSQL 15 (Docker: `postgres:15-alpine`)
  - Connection: `DATABASE_URL` env var (default: `postgresql://agente:agente123@postgres:5432/agente_ana`)
  - Client: SQLAlchemy 2.0 ORM + psycopg2-binary
  - Fallback: SQLite (`sqlite:///./test.db`) when `DATABASE_URL` is unset (used in tests)
  - Tables: `contacts`, `conversations`, `messages`, `remarketing_queue` (defined in `app/models.py`)
  - Also used as APScheduler job store via `SQLAlchemyJobStore`

**File Storage:**
- Local filesystem only
  - `knowledge_base/` directory (mounted read-only in Docker): JSON and Markdown files for agent context
  - `docs/` directory (mounted read-only in Docker): PDF and image files served as static media via `/media` endpoint
  - `dietbox_token_cache.json`: token cache file written at project root by `app/agents/dietbox_worker.py`
  - No cloud object storage (S3, GCS, etc.) detected

**Caching:**
- Redis 7 (Docker: `redis:7-alpine`)
  - Connection: `REDIS_URL` env var (default: `redis://redis:6379/0`)
  - Client: `redis` Python SDK 5.0.8
  - Current usage: rate-limiting Meta API remarketing dispatch (max 30 messages/minute), using minute-granularity keys (`meta:rate:YYYYMMDDHHMM`) in `app/remarketing.py`
  - Note: `app/router.py` has a comment marking in-memory agent state dict as a placeholder to be migrated to Redis in production

## Authentication & Identity

**Webhook Security:**
- Meta webhook endpoint (`POST /webhook`) validates `X-Hub-Signature-256` HMAC-SHA256 signature
- Env vars: `META_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN`
- Webhook verification handshake handled in `GET /webhook` (`app/webhook.py`)

**Contact Privacy:**
- Patient phone numbers are stored as SHA-256 hash (`phone_hash`) in the `contacts` table for lookups
- Raw `phone_e164` is stored separately (required to send messages via Meta API and for remarketing)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, or similar configured)

**Logs:**
- Python `logging` module, configured at INFO level in `app/main.py`
- Format: `%(asctime)s %(levelname)s %(message)s`
- Output to stdout (captured by Docker)
- No structured logging or log aggregation service configured

## CI/CD & Deployment

**Hosting:**
- Docker Compose stack (self-hosted; no cloud provider detected in codebase)
- Nginx handles TLS via Certbot — volume mounts for `certbot_www` and `certbot_conf` present in `docker-compose.yml`

**CI Pipeline:**
- None configured (no GitHub Actions, GitLab CI, or similar files found)
- Manual test command per `CLAUDE.md`: `python -m pytest tests/ -q`

## Webhooks & Callbacks

**Incoming:**
- `GET /webhook` — Meta webhook verification challenge (returns `hub.challenge`)
- `POST /webhook` — Meta incoming message events; processes immediately in background task via FastAPI `BackgroundTasks`
- Webhook payload structure: Meta Cloud API format with nested `entry` → `changes` → `value` → `messages`

**Outgoing:**
- `.env.example` references `MERCADOPAGO_WEBHOOK_URL` (optional) — no MercadoPago webhook handler found in current code
- No other outgoing webhook endpoints detected

## Environment Configuration

**Required env vars:**
- `WHATSAPP_TOKEN` / `META_ACCESS_TOKEN` — Meta Cloud API bearer token
- `WHATSAPP_PHONE_NUMBER_ID` / `META_PHONE_NUMBER_ID` — WhatsApp business number ID
- `META_APP_SECRET` — for webhook signature verification
- `WEBHOOK_VERIFY_TOKEN` — for webhook handshake
- `ANTHROPIC_API_KEY` — Claude AI
- `DATABASE_URL` — PostgreSQL connection string
- `REDIS_URL` — Redis connection string
- `DIETBOX_EMAIL`, `DIETBOX_SENHA` — Dietbox platform credentials
- `REDE_EMAIL`, `REDE_SENHA` — Rede merchant portal credentials

**Optional env vars:**
- `GEMINI_API_KEY` — Google Gemini (AI Engine primary; falls back to Claude if absent)
- `OPENAI_API_KEY` — OpenAI Whisper for audio transcription
- `DIETBOX_ID_LOCAL_PRESENCIAL`, `DIETBOX_ID_LOCAL_ONLINE` — pre-set Dietbox location IDs
- `SECRET_KEY` — application secret (not yet used in visible auth middleware)
- `PAYMENT_GATEWAY`, `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_WEBHOOK_URL`, `REDE_PV`, `REDE_TOKEN` — referenced in `.env.example` but not wired into current application code

**Secrets location:**
- `.env` file at project root (not committed; `.env.example` is the template)

---

*Integration audit: 2026-04-07*
