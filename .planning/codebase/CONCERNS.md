# Codebase Concerns

**Analysis Date:** 2026-04-07

---

## 1. Critical — Scalability / Production Blockers

### In-Memory Agent State Will Break Under Horizontal Scaling or Restarts

- Issue: `_AGENT_STATE` in `app/router.py` (line 23) is a plain Python dict keyed by `phone_hash`. All conversation state (current stage, chosen plan, slot, payment status) lives exclusively in this dict. A process restart wipes it. Two workers serving the same patient simultaneously corrupt state silently.
- Files: `app/router.py`, `app/agents/atendimento.py`, `app/agents/retencao.py`
- Impact: Any deploy, container restart, or load-balanced second instance loses all active conversations mid-flow, leaving patients stranded at any payment or scheduling stage.
- Fix approach: Serialize agent state to JSON and store in Redis (already present in docker-compose). The `AgenteAtendimento` docstring already acknowledges this gap: "O estado é serializado para ser armazenado no banco/Redis entre mensagens."

### `_retry_failed_messages` Calls `asyncio.run()` Inside an APScheduler Thread

- Issue: `app/retry.py` lines 58-67 call `asyncio.run(route_message(...))` from inside an APScheduler background thread. `asyncio.run()` creates a new event loop, which is fragile and may conflict with the running FastAPI/uvicorn loop depending on the execution model.
- Files: `app/retry.py`
- Impact: Silent failures or `RuntimeError: This event loop is already running` on some uvicorn configurations; retried messages may never actually re-route.
- Fix approach: Use `asyncio.get_event_loop().run_until_complete()` or schedule via a queue consumed by the async app; alternatively, make `route_message` sync-compatible.

### `_dispatch_due_messages` Uses Sync Redis Client Inside APScheduler Job

- Issue: `app/remarketing.py` line 104 imports and uses the synchronous `redis` client inside a BackgroundScheduler job. This runs on a thread pool, which is fine for sync Redis, but the job also calls `meta.send_template(...)` which is an `async def` method (`app/meta_api.py` line 33) without `await`.
- Files: `app/remarketing.py` lines 104-158, `app/meta_api.py`
- Impact: `send_template` returns a coroutine object that is never awaited; remarketing messages are never actually sent.
- Fix approach: Make the dispatcher either fully sync (use a sync HTTP client for Meta API calls) or run inside an async task.

---

## 2. High — Security

### PIX Key (CPF) Hardcoded in Source Code

- Issue: The PIX CPF key `14994735670` appears verbatim in `app/knowledge_base.py` lines 126, 158, and 208 as a hardcoded string constant in the `CONTATOS` dict and in FAQ answers. Changes to the payment key require a code deploy.
- Files: `app/knowledge_base.py`
- Impact: Key is committed to version control; must be changed in code rather than environment if it ever needs to rotate.
- Fix approach: Move `pix_chave` to an environment variable; reference via `os.environ`.

### Dietbox Financial UUIDs Hardcoded in Source

- Issue: `app/agents/dietbox_worker.py` lines 508-509 hardcode two Dietbox account UUIDs: `idCategoria = "89867901-A5B8-4B61-89DA-5A24BAE39952"` and `idConta = "71D0DE53-96C5-4AFA-A144-98039B264031"`. These are specific to one Dietbox account and will silently send financial entries to the wrong category/account if the account changes.
- Files: `app/agents/dietbox_worker.py`
- Fix approach: Move to environment variables `DIETBOX_ID_CATEGORIA` and `DIETBOX_ID_CONTA`.

### Rede Merchant Code (`_PV`) Hardcoded

- Issue: `app/agents/rede_worker.py` line 53 hardcodes `_PV = "101801637"` (the Rede establishment code). This is embedded in API calls to the payment portal.
- Files: `app/agents/rede_worker.py`
- Fix approach: Move to `REDE_PV` environment variable.

### Test Chat Endpoint Exposed in Production App

- Issue: `app/test_chat.py` is registered in `app/main.py` (line 8 and 35) with no authentication or environment guard. Routes `/test/chat` and `/test/reset` are reachable in any deployment, allowing anyone to simulate conversations and reset contact state in the live database.
- Files: `app/main.py`, `app/test_chat.py`
- Impact: Unauthorized state manipulation; potential DoS via repeated resets.
- Fix approach: Guard with `if os.environ.get("ENABLE_TEST_CHAT") == "1"` or remove from production build.

### Signature Verification Bypassed When `META_APP_SECRET` Is Empty

- Issue: `app/webhook.py` line 9 reads `APP_SECRET = os.environ.get("META_APP_SECRET", "")`. `app/meta_api.py` `verify_signature` returns `False` when the signature header is missing, but if `APP_SECRET` is empty, `hmac.new(b"", body, ...)` still produces a valid HMAC that could match an attacker's request with an empty key. The webhook becomes trivially forgeable in any environment where this env var is not set.
- Files: `app/webhook.py`, `app/meta_api.py`
- Fix approach: Fail closed: if `APP_SECRET` is empty, reject all webhook calls with 500 at startup or return 403 unconditionally.

---

## 3. High — Correctness / Business Logic

### Payment Confirmation Is Based on Message Length, Not Actual Verification

- Issue: `app/agents/atendimento.py` lines 540-541 confirm payment if `len(msg) > 30`, treating any long message (including an image caption or a complaint) as proof of payment. The condition `confirmado or len(msg) > 30` means any message longer than 30 characters automatically advances to scheduling.
- Files: `app/agents/atendimento.py`
- Impact: Patients who send long messages for other reasons (e.g., questions, complaints) may be incorrectly advanced to the Dietbox scheduling step without having paid.
- Fix approach: Require explicit keyword match or a dedicated image/document receipt detection step.

### Dietbox Birthdate Uses Fake Placeholder `1990-01-01`

- Issue: `app/agents/dietbox_worker.py` line 330: `birthdate = dados.get("data_nascimento") or "1990-01-01T00:00:00"`. The agent never collects `data_nascimento` from patients, so every registered patient receives a fake birth date of January 1, 1990 in Dietbox.
- Files: `app/agents/dietbox_worker.py`, `app/agents/atendimento.py`
- Impact: All patient records in Dietbox are created with incorrect birth dates, breaking any age-based filtering and clinical records.
- Fix approach: Add a birth date collection step in the atendimento flow, or mark the field optional in Dietbox if the API allows it.

### Confidence Score from Orchestrator Is Computed but Never Used for Routing

- Issue: `app/agents/orchestrator.py` computes and returns a `confianca` (confidence) score, but `app/router.py` ignores it entirely. There is no fallback or human escalation for low-confidence classifications.
- Files: `app/agents/orchestrator.py`, `app/router.py`
- Impact: Low-confidence mis-classifications (e.g., a patient saying "cancel my Netflix" being routed to the retention agent) are silently acted upon.
- Fix approach: Add a minimum confidence threshold (e.g., 0.6); route to LLM free-text response or escalation for anything below.

### Remarcação Confirms Slot Without Actually Updating Dietbox

- Issue: `app/agents/retencao.py` lines 286-292: when a patient chooses a new slot during remarcação, `MSG_CONFIRMACAO_REMARCACAO` is returned and `etapa` is set to `"concluido"`, but no call to `app/agents/dietbox_worker.py` is made to cancel the old appointment and create a new one.
- Files: `app/agents/retencao.py`
- Impact: Patients receive confirmation of rescheduling, but the old appointment remains in Dietbox unchanged.
- Fix approach: Call `agendar_consulta` and optionally a cancellation endpoint for the previous appointment after slot selection.

### Upsell Logic Uses Vague Keyword Matching

- Issue: `app/agents/atendimento.py` line 408 accepts an upsell with: `any(w in msg.lower() for w in ["premium", "sim", "pode", "vamos", "upgrade", "esse"])`. The word "sim" is extremely broad — a patient saying "sim, entendi os termos" in a different context would trigger an unwanted plan upgrade.
- Files: `app/agents/atendimento.py`
- Impact: Accidental plan upgrades; patients charged for a higher plan they did not intentionally select.

---

## 4. Medium — Technical Debt

### Playwright Scraping for Payment Link Generation Is Fragile

- Issue: `app/agents/rede_worker.py` generates payment links by automating a browser against `meu.userede.com.br` using hardcoded CSS selectors, JS evaluation snippets, and fixed `wait_for_timeout` delays (ranging from 500ms to 12,000ms). The file docstring explicitly warns: "Se a Rede alterar o HTML, ajuste a função."
- Files: `app/agents/rede_worker.py`
- Impact: Any UI change in the Rede portal silently breaks payment link generation; the 180-second timeout per operation means each failed link attempt blocks a thread for 3 minutes. Requires `headless=False` (a visible browser window) which is incompatible with most cloud/container environments.
- Fix approach: Use the Rede official REST API or checkout API if available; otherwise implement retry with exponential backoff and a shorter hard timeout.

### Dietbox Authentication Also Uses Playwright Browser Scraping

- Issue: `app/agents/dietbox_worker.py` lines 62-149 authenticate by launching a Chromium browser, filling in a login form, and intercepting Bearer tokens from network requests. The token cache path is a JSON file on disk (`dietbox_token_cache.json`) at the project root, not in a secure store.
- Files: `app/agents/dietbox_worker.py`
- Impact: Fragile to Azure AD B2C UI changes; token stored unencrypted on disk; 90-second timeout per login blocks a thread.
- Fix approach: Request a Dietbox API token via their OAuth2 endpoint directly with `requests`; avoid browser automation for auth.

### `create_engine` Uses SQLite as Default in Production Path

- Issue: `app/database.py` line 5: `DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")`. If `DATABASE_URL` is ever missing from the environment, the app silently falls back to SQLite and creates `test.db` in the working directory. The `test.db` file is present in the repository root (untracked), confirming this fallback has been triggered.
- Files: `app/database.py`
- Impact: Data loss risk; SQLite does not support concurrent writes from multiple workers.
- Fix approach: Fail at startup with a clear error if `DATABASE_URL` is not set in non-test environments.

### Duplicate Pricing Tables in Two Modules

- Issue: Plan prices are defined twice: once in `app/knowledge_base.py` (the `PLANOS` dict, lines 19-121) and again in `app/agents/rede_worker.py` (`VALORES_PLANOS_PIX`, `PARCELA_PLANOS`, `PARCELAS_PLANOS`, lines 24-47). The two tables must be kept manually in sync; a price change requires edits in both files.
- Files: `app/knowledge_base.py`, `app/agents/rede_worker.py`
- Fix approach: Import from `app/knowledge_base.py` in `rede_worker.py` and derive the Rede-specific values dynamically.

### Outbound Message Routing Tag Update Has a Logic Error

- Issue: `app/router.py` lines 158-165: the `set_tag(db, contact, Tag.OK, force=True)` call is inside the condition `if agent.etapa in ("cadastro_dietbox", "confirmacao", "finalizacao")`, not inside the separate `elif agent.etapa == "finalizacao" and agent.pagamento_confirmado` branch. Because of Python's `elif` chain, the `OK` tag is never set — the first matching branch is for stages `cadastro_dietbox/confirmacao/finalizacao`, and the `elif` for finalizacao+pagamento_confirmado is reached only if the first condition is False.
- Files: `app/router.py` lines 158-165

### `google-generativeai` Dependency Is Unused

- Issue: `requirements.txt` line 9 includes `google-generativeai==0.8.6`. No import of this package appears anywhere in `app/`. The project description notes a previous migration from Gemini to Claude.
- Files: `requirements.txt`
- Impact: Unused dependency increases image size and attack surface.
- Fix approach: Remove from `requirements.txt`.

---

## 5. Medium — Missing Features / Incomplete Flows

### Remarketing Templates Referenced but Never Defined

- Issue: `app/remarketing.py` lines 11-24 reference Meta message templates by name (`follow_up_geral`, `objecao_preco`, `urgencia_vagas`, `depoimento`, `oferta_especial`, `opcoes_pagamento`, `diferenciacao`). These must be pre-approved in Meta Business Manager. No evidence of these templates being created; if missing, all remarketing dispatches will return a Meta API error.
- Files: `app/remarketing.py`
- Impact: Entire remarketing system is non-functional until templates are approved by Meta.

### Patient Email Is Always Empty in Dietbox Registration

- Issue: `app/agents/atendimento.py` line 563 passes `"email": ""` when calling `processar_agendamento`. The atendimento flow never collects the patient's email address, so every Dietbox patient record has a blank email field.
- Files: `app/agents/atendimento.py`, `app/agents/dietbox_worker.py`

### `confirmar_pagamento` in Dietbox Worker Is Never Called

- Issue: `app/agents/dietbox_worker.py` lines 582-594 define `confirmar_pagamento(id_transacao)`, which marks a transaction as paid in Dietbox. This function is never called anywhere in the codebase. Financial entries are always created with `pago=False`.
- Files: `app/agents/dietbox_worker.py`
- Impact: Dietbox financial records always show payment as pending regardless of PIX confirmation received.

### Media/Document Sending Is Stubbed with Placeholder Strings

- Issue: `app/agents/atendimento.py` lines 325-328 return literal strings like `"[PDF: Thaynara - Nutricionista.pdf]"` and `"[IMG: COMO-SE-PREPARAR---ONLINE.jpg]"` instead of actually sending files via the Meta API. The `app/media_handler.py` module exists but is not invoked from the atendimento flow.
- Files: `app/agents/atendimento.py`, `app/media_handler.py`
- Impact: Patients receive bracket-notation text placeholders instead of actual PDF/image attachments.

---

## 6. Low — Code Smells / Minor Issues

### `import re` and `import asyncio` Inside Functions

- Issue: `app/agents/retencao.py` lines 195, 205 and `app/agents/atendimento.py` line 647 import standard library modules (`re`, `datetime.date`, `datetime.timedelta`) inside function bodies rather than at module level, incurring a lookup cost on every call.
- Files: `app/agents/retencao.py`, `app/agents/atendimento.py`

### `time.sleep()` Inside APScheduler Remarketing Job

- Issue: `app/remarketing.py` line 155: `import time; time.sleep(2)` is called inside `_dispatch_due_messages()` after each remarketing send. Because this runs in a BackgroundScheduler thread, this sleep blocks the thread for 2 seconds per message, meaning dispatching 30 messages takes at least 60 seconds per scheduler tick.
- Files: `app/remarketing.py`

### Anthropic Client Instantiated Per Call

- Issue: `app/agents/orchestrator.py` line 78, `app/agents/atendimento.py` line 195, and `app/agents/retencao.py` line 402 each instantiate `anthropic.Anthropic(api_key=...)` inside the function body on every LLM call. The client should be a module-level singleton.
- Files: `app/agents/orchestrator.py`, `app/agents/atendimento.py`, `app/agents/retencao.py`

### Meta API Version Pinned to `v19.0`

- Issue: `app/meta_api.py` line 5: `META_API_BASE = "https://graph.facebook.com/v19.0"`. Meta Graph API versions are deprecated on a rolling 2-year schedule; v19.0 was released in early 2024 and will eventually be retired.
- Files: `app/meta_api.py`
- Fix approach: Move the API version to a constant or env var so it can be updated without touching business logic.

---

*Concerns audit: 2026-04-07*
