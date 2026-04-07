# Technology Stack

**Analysis Date:** 2026-04-07

## Languages

**Primary:**
- Python 3.12 - All application code (runtime pinned via `FROM python:3.12-slim` in `Dockerfile`)

**Secondary:**
- None detected

## Runtime

**Environment:**
- CPython 3.12 (slim Debian image)
- Containerized via Docker + Docker Compose

**Package Manager:**
- pip (no lockfile; `requirements.txt` is the sole dependency spec)
- Lockfile: absent — only `requirements.txt` present

## Frameworks

**Core:**
- FastAPI 0.115.0 — HTTP server and routing (`app/main.py`, `app/webhook.py`)
- Uvicorn 0.30.6 (standard extras) — ASGI server, launched with `--reload` in development

**ORM / Database:**
- SQLAlchemy 2.0.35 — ORM using `DeclarativeBase` with type-mapped columns (`app/models.py`, `app/database.py`)
- Alembic 1.13.3 — database migrations (fallback `create_all` in lifespan if Alembic not run)

**Scheduling:**
- APScheduler 3.10.4 — `BackgroundScheduler` with `SQLAlchemyJobStore` for persistent jobs (`app/remarketing.py`, `app/main.py`)
  - Runs two recurring jobs: remarketing dispatcher (every 1 min), retry processor (every 5 min)

**Browser Automation:**
- Playwright >= 1.40.0 — Chromium-based automation for two purposes:
  1. Dietbox login via Azure AD B2C to capture Bearer token (`app/agents/dietbox_worker.py`)
  2. Rede payment portal automation at `meu.userede.com.br` (`app/agents/rede_worker.py`)
  - Dietbox login runs headless; Rede portal requires `headless=False` due to reCAPTCHA
  - Both use `ThreadPoolExecutor` to avoid asyncio event loop conflict with FastAPI

**Testing:**
- pytest 8.3.2 — test runner (`tests/`)
- pytest-asyncio 0.24.0 — async test support
- respx 0.22.0 — httpx mock library for HTTP client tests

## Key Dependencies

**Critical:**
- `anthropic >= 0.50.0` — Anthropic Python SDK; used in two places:
  1. Orchestrator (`app/agents/orchestrator.py`): Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for intent classification
  2. AI Engine fallback (`app/ai_engine.py`): Claude Haiku 4.5 for response generation when Gemini confidence is low
- `google-generativeai 0.8.6` — Google Gemini SDK; used in `app/ai_engine.py` as primary response generator (`gemini-2.0-flash` model)
- `httpx[test] 0.27.0` — async HTTP client for Meta Cloud API calls (`app/meta_api.py`, `app/media_handler.py`) and OpenAI Whisper calls
- `requests` (transitive, used explicitly) — sync HTTP client used in `app/agents/dietbox_worker.py` for Dietbox REST API calls
- `psycopg2-binary 2.9.9` — PostgreSQL adapter for SQLAlchemy
- `redis 5.0.8` — Redis client for rate-limiting remarketing dispatch (`app/remarketing.py`)
- `python-dotenv 1.0.1` — loads `.env` file in local development

**Infrastructure:**
- `apscheduler[sqlalchemy]` — job persistence via `SQLAlchemyJobStore` using the same Postgres connection

## Configuration

**Environment:**
- Configured via `.env` file (loaded by Docker Compose `env_file: .env`)
- Template: `.env.example` at project root
- Critical keys: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `META_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN`, `DIETBOX_EMAIL`, `DIETBOX_SENHA`, `REDE_EMAIL`, `REDE_SENHA`

**Build:**
- `Dockerfile` — multi-step: installs system libs for Playwright/Chromium, installs Python deps, runs `playwright install chromium`
- `docker-compose.yml` — defines four services: `app`, `postgres`, `redis`, `nginx`
- No `pyproject.toml` or `setup.py` present; project is not packaged

## Platform Requirements

**Development:**
- Docker + Docker Compose (recommended)
- Python 3.12 for local runs
- Playwright Chromium binaries (installed via `playwright install chromium`)
- For Rede portal automation: display server required (headless=False), which means a headless server needs Xvfb or similar in production

**Production:**
- Docker Compose stack with Postgres 15 and Redis 7
- Nginx (reverse proxy + TLS termination via Certbot/Let's Encrypt volumes configured)
- Port 8000 internal (app), 80/443 external (nginx)

---

*Stack analysis: 2026-04-07*
