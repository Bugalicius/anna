# AGENTS.md

## Scope that matters
- Prioritize the current conversation stack in `app/conversation/` and `app/tools/`; `legacy/` and `legacy_tests/` are historical.
- Real production path is `WhatsApp webhook -> app/webhook.py -> app/router.py -> ConversationEngine -> Meta API`.
- `app/router.py` should stay thin (I/O/orchestration); conversational logic belongs in `app/conversation/*`.

## Fast local run
- Python target is 3.12 (Dockerfile base: `python:3.12-slim`).
- Install deps with `pip install -r requirements.txt`.
- Run app with `uvicorn app.main:app --host 0.0.0.0 --port 8000` (same entrypoint used in Docker).
- `ENABLE_TEST_CHAT=true` is required to mount the test chat router in `app/main.py`.

## Required environment (startup hard-fails)
- `app/config.py::validate_required_env()` enforces: `GEMINI_API_KEY`, (`META_ACCESS_TOKEN` or `WHATSAPP_TOKEN`), (`META_PHONE_NUMBER_ID` or `WHATSAPP_PHONE_NUMBER_ID`), `DATABASE_URL`, `REDIS_URL`.
- Webhook signature verification is always enforced in `app/webhook.py`; missing/invalid `META_APP_SECRET` will cause 403 on inbound webhook calls.
- Keep `DASHBOARD_KEY` set when using `/dashboard`.

## Testing workflow (verified from repo configs/docs)
- Pytest is configured via `pytest.ini` with `pythonpath = .` and `testpaths = tests`.
- Run a focused test: `pytest tests/test_router.py -q` (swap file as needed).
- For conversation-flow changes, run the maintained focused suites first:
  - `pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py -q`
  - `pytest tests/test_bug_fixes.py tests/test_remarcacao_humana.py -q`

## Operational guardrails to preserve
- Do not expose internal phone numbers to patients; escalation must stay internal-only.
- Do not answer clinical questions directly; route via escalation flow.
- Preserve deterministic handling for unsupported media, off-hours behavior, and safety blocks (pregnant users / under 16).
- Sanitize long inbound texts before LLM use (2000-char cap is part of current safety behavior).

## Deployment notes used by this repo
- Main deploy flow documented in `CLAUDE.md`: `git push` then remote `docker compose up --build -d app` on VPS.
- Local `docker-compose.yml` mounts source directories (`./app`, `./tests`, `./docs`, `./knowledge_base`) into the container; changes are live-mounted during local compose runs.
