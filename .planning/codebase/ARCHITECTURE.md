# Architecture

**Analysis Date:** 2026-04-07

## Pattern Overview

**Overall:** Multi-agent pipeline with centralized orchestration

**Key Characteristics:**
- Webhook-driven entry point; Meta Cloud API (WhatsApp Business API) as the message transport
- Stateless HTTP handlers — all conversation state held in-process (Python dict) or database
- Intent classification by LLM (Claude Haiku) routes messages to specialized agents
- Each agent owns a finite-state machine (FSM) for its domain; FSM state persists in `_AGENT_STATE` dict keyed by `phone_hash`
- External side-effects (Dietbox, payment portal) isolated in dedicated worker modules

## Layers

**HTTP Transport Layer:**
- Purpose: Receive and validate webhooks from Meta; return 200 immediately
- Location: `app/webhook.py`
- Contains: Signature verification, payload parsing, deduplication, `BackgroundTasks` dispatch
- Depends on: `app/meta_api.py` (signature check), `app/models.py` (Contact, Conversation, Message)
- Used by: Meta Cloud API (external)

**Routing Layer:**
- Purpose: Load contact state from DB, check for active agent, call orchestrator, dispatch to correct agent, send replies
- Location: `app/router.py`
- Contains: `route_message()`, `_AGENT_STATE` in-memory dict, helper functions
- Depends on: `app/agents/orchestrator.py`, `app/agents/atendimento.py`, `app/agents/retencao.py`, `app/meta_api.py`, `app/database.py`
- Used by: `app/webhook.py` (via `BackgroundTasks`)

**Orchestrator (Agent 0):**
- Purpose: Classify message intent via Claude Haiku; return routing instruction
- Location: `app/agents/orchestrator.py`
- Contains: `rotear()`, `_classificar_intencao()`, intent enum, prompt template
- Depends on: `anthropic` SDK (synchronous)
- Used by: `app/router.py`

**Agent 1 — Atendimento:**
- Purpose: Drive new patient through 10-step booking funnel
- Location: `app/agents/atendimento.py`
- Contains: `AgenteAtendimento` class, FSM with 10 stages, LLM fallback, helper extractors
- Depends on: `app/agents/dietbox_worker.py`, `app/agents/rede_worker.py`, `app/knowledge_base.py`
- Used by: `app/router.py`

**Agent 2 — Retencao:**
- Purpose: Handle rescheduling and cancellation; outbound remarketing message generation
- Location: `app/agents/retencao.py`
- Contains: `AgenteRetencao` class, `REMARKETING_SEQ` sequence definitions, lembrete builder
- Depends on: `app/agents/dietbox_worker.py`, `app/knowledge_base.py`
- Used by: `app/router.py`, `app/remarketing.py` (for message text)

**Worker — Dietbox (Agent 3):**
- Purpose: All Dietbox API interactions — slot lookup, patient CRUD, appointment booking, financial records
- Location: `app/agents/dietbox_worker.py`
- Contains: `consultar_slots_disponiveis()`, `processar_agendamento()`, `agendar_consulta()`, `lancar_financeiro()`, Playwright-based token login
- Depends on: `requests`, `playwright.sync_api`
- Used by: `app/agents/atendimento.py`, `app/agents/retencao.py`

**Worker — Rede (Agent 4):**
- Purpose: Generate card payment links via meu.userede.com.br portal automation
- Location: `app/agents/rede_worker.py`
- Contains: `gerar_link_pagamento()`, Playwright portal automation in `ThreadPoolExecutor`
- Depends on: `playwright.sync_api`
- Used by: `app/agents/atendimento.py`

**Persistence Layer:**
- Purpose: SQLAlchemy ORM models; single database session factory
- Location: `app/database.py`, `app/models.py`
- Contains: `Contact`, `Conversation`, `Message`, `RemarketingQueue` models
- Depends on: SQLAlchemy, PostgreSQL (production) / SQLite (dev/test)
- Used by: `app/webhook.py`, `app/router.py`, `app/remarketing.py`, `app/retry.py`

**Knowledge Base:**
- Purpose: Singleton providing all static business knowledge (plans, prices, policies, FAQ, system prompt) to agents
- Location: `app/knowledge_base.py`
- Contains: `KnowledgeBase` class, `kb` global instance; reads JSON/MD files from `knowledge_base/`
- Used by: `app/agents/atendimento.py`, `app/agents/retencao.py`

**Scheduler / Remarketing:**
- Purpose: APScheduler background jobs — remarketing dispatch and message retry
- Location: `app/remarketing.py`, `app/retry.py`
- Contains: `create_scheduler()`, `_dispatch_due_messages()`, `_retry_failed_messages()`
- Depends on: `apscheduler`, Redis (rate limiting), `app/meta_api.py`
- Used by: `app/main.py` (lifespan startup)

**Escalation:**
- Purpose: Forward clinical questions to the nutritionist's private number
- Location: `app/escalation.py`
- Contains: `escalar_para_humano()`, `build_contexto_escalacao()`
- Used by: `app/router.py`

**Tag / Stage Machine:**
- Purpose: Enforce valid `Contact.stage` transitions
- Location: `app/tags.py`
- Contains: `Tag` enum, `set_tag()`, transition rules dict
- Used by: `app/router.py`

## Data Flow

**Inbound Message Lifecycle:**

1. Meta delivers POST to `/webhook`; `app/webhook.py` validates HMAC signature
2. `process_message()` runs in `BackgroundTasks`: deduplicates by `meta_message_id`; upserts `Contact`, `Conversation`, `Message` in DB
3. `route_message()` in `app/router.py` loads contact from DB; cancels pending remarketing if appropriate
4. If an active agent FSM exists in `_AGENT_STATE`, message goes directly to that agent (bypasses orchestrator)
5. Otherwise `rotear()` calls Claude Haiku with intent classification prompt; returns routing dict
6. Router dispatches to the appropriate agent: `AgenteAtendimento`, `AgenteRetencao`, `escalar_para_humano`, or a static default reply
7. Agent FSM processes message, may call Dietbox/Rede workers synchronously, returns `list[str]`
8. `_enviar()` sends each string as a separate WhatsApp text message via `MetaAPIClient`

**Outbound Scheduler Flow:**

1. APScheduler runs `_dispatch_due_messages()` every 1 minute
2. Queries `RemarketingQueue` for due entries; enforces Redis rate limit (30/min)
3. Sends WhatsApp template via `MetaAPIClient.send_template()`
4. Updates `Contact.stage` to `archived` after `MAX_REMARKETING` (5) messages

**Retry Flow:**

1. APScheduler runs `_retry_failed_messages()` every 5 minutes
2. Messages with `processing_status = "retrying"` and `retry_count < 3` are reprocessed
3. Exponential backoff: 1s, 4s, 16s between attempts

## Key Abstractions

**Agent FSM:**
- Purpose: Maintains per-conversation stage and accumulated state (name, plan, slot, payment method)
- Examples: `app/agents/atendimento.py` (`AgenteAtendimento`), `app/agents/retencao.py` (`AgenteRetencao`)
- Pattern: `etapa: str` field drives a `_despachar()` dispatch method; each step returns `list[str]`

**KnowledgeBase Singleton:**
- Purpose: Single source of truth for all business rules loaded at import time
- Examples: `app/knowledge_base.py` — `kb.system_prompt()`, `kb.get_valor()`, `kb.get_plano()`
- Pattern: Module-level `kb = KnowledgeBase()` instance; agents import and read but never mutate

**MetaAPIClient:**
- Purpose: Async HTTP client for Meta Cloud API (send text, templates)
- Examples: `app/meta_api.py`
- Pattern: Instantiated per request in `route_message()` using env vars

**Playwright Workers:**
- Purpose: Browser automation to extract tokens and perform portal actions that lack a public API
- Examples: `app/agents/dietbox_worker.py` (`_login_playwright_sync`), `app/agents/rede_worker.py` (`_gerar_link_portal_sync`)
- Pattern: Sync Playwright wrapped in `ThreadPoolExecutor` to avoid blocking asyncio event loop

## Entry Points

**Webhook (primary):**
- Location: `app/webhook.py` — `POST /webhook`
- Triggers: Inbound WhatsApp messages from Meta
- Responsibilities: Validate, deduplicate, persist, enqueue for processing

**Health Check:**
- Location: `app/main.py` — `GET /health`
- Triggers: Load balancer / uptime monitor

**Test Chat:**
- Location: `app/test_chat.py` (router mounted in `app/main.py`)
- Triggers: Development/QA only, not intended for production

**Scheduler Jobs (background):**
- Location: Started in `app/main.py` lifespan `create_scheduler()`
- Triggers: APScheduler intervals (1 min remarketing, 5 min retry)

## Error Handling

**Strategy:** Log and continue — no exception should crash the event loop; agents return fallback LLM response when an expected path fails

**Patterns:**
- Dietbox/Rede workers: `try/except` around all HTTP calls; return `{"sucesso": False, "erro": ...}` or `LinkPagamento(sucesso=False)` on failure
- Orchestrator: falls back to `"novo_lead"` intent on any Claude API error
- Agent LLM fallback: `_gerar_resposta_llm()` called when no deterministic step matches
- Message delivery: per-message `try/except` in `_enviar()`; failures logged, other messages continue

## Cross-Cutting Concerns

**Logging:** `logging.basicConfig` at INFO level in `app/main.py`; each module gets its own `logger = logging.getLogger(__name__)`
**Validation:** HMAC-SHA256 signature on every webhook payload; `phone_hash` for contact privacy (SHA-256 of phone number)
**Authentication:** Meta webhook verify-token handshake on `GET /webhook`; Dietbox Bearer token from Playwright login with 1h cache; Rede portal via Playwright login
**State Storage:** Agent FSM state lives in `_AGENT_STATE` in-process dict (documented in `app/router.py` as needing Redis for production)
**Scheduling:** APScheduler `BackgroundScheduler` with `SQLAlchemyJobStore` pointing to same database

---

*Architecture analysis: 2026-04-07*
