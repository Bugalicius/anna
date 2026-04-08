# Stack Research

**Domain:** WhatsApp AI scheduling agent — intelligence improvements, payment API migration, remarketing
**Researched:** 2026-04-07
**Confidence:** MEDIUM-HIGH (LLM layer: HIGH; payment gateway: MEDIUM; scheduling: HIGH)

---

## Context

This is a subsequent milestone. The existing stack (FastAPI 0.115, SQLAlchemy 2.0, APScheduler 3.10, Redis 5, Anthropic SDK, PostgreSQL 15) is NOT being replaced. This document covers only the **new additions and migrations** needed for:

1. LLM conversation intelligence (context tracking, intent classification, multi-turn dialog)
2. Payment API migration (Playwright + Rede portal → REST API)
3. Remarketing scheduler improvements

---

## Recommended Stack — New Additions

### LLM Conversation Intelligence

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `anthropic` Python SDK | `>=0.50.0` (already installed) | Claude API client | Already in project; supports prompt caching natively in current version |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` (already configured) | Primary LLM for all agents | Fastest current-generation model, 200k context window, $1/$5 per MTok — confirmed current as of April 2026 |
| Prompt caching (Anthropic feature) | Beta header `cache_control` | Cache system prompts across turns | Reduces Haiku 4.5 input costs to $0.10/MTok on cache hits (90% savings); minimum 4,096 tokens to activate |
| Context editing (Anthropic feature) | Beta header `context-management-2025-06-27` | Auto-clear stale tool results from long conversations | Server-side; client keeps full history, API strips old tool results before sending to model |

**Implementation pattern for conversation context:**
- Store full message history in Redis with 24h TTL (already using Redis)
- Pass history to Claude on each turn (Haiku 4.5's 200k context handles dozens of turns)
- Apply `cache_control: {"type": "ephemeral"}` to system prompt block — activates prompt caching when system prompt exceeds 4,096 tokens
- No LangChain, no vector store, no embedding layer needed — this is not RAG, it is a direct conversation with memory in Redis

### Payment Gateway — Asaas (recommended replacement for Rede Playwright)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Asaas REST API | v3 (current) | Generate credit card payment links with installments | Best-in-class developer API in Brazil; pure REST; no display server required; full sandbox; Pix + credit card + boleto |
| `httpx` | `0.27.0` (already installed) | HTTP client for Asaas API calls | Already in project; async-native; replaces requests for this module |

**Asaas key facts (HIGH confidence — verified from official docs):**
- Sandbox: `https://api-sandbox.asaas.com/v3`
- Production: `https://api.asaas.com/v3` (implied by sandbox pattern)
- Auth: `access_token` header with API key (format `$aact_prod_...` for production)
- Payment link endpoint: `POST /v3/paymentLinks`
- Installment support: up to 21x for Visa/Master, 12x for other brands
- `chargeType: "INSTALLMENT"` + `maxInstallmentCount: N` = payer chooses installments at checkout
- Pix: zero fee; credit card: R$ 0.49/transaction + 1.99% on installments
- Webhook for payment status updates
- Free sandbox account, no monthly fee, pay-per-use

**Why Asaas over alternatives:**
- **Over e-Rede REST API**: e-Rede's API processes transactions (requires card data) but does NOT natively generate hosted payment links the way Asaas does. The current Playwright automation logs into `meu.userede.com.br` to create links in the portal UI — the e-Rede REST API would replicate transaction processing, not the hosted link flow. Additionally, e-Rede is migrating from PV+key to OAuth 2.0 (deadline: January 5, 2026), adding integration complexity.
- **Over Efí Bank**: Both are comparable. Asaas has simpler API (v3 REST, single `access_token` header), better developer documentation, and the specific `paymentLinks` endpoint maps exactly to the current use case (generate shareable link, send via WhatsApp). Efí Bank has lower credit card rate (3.49%) but more complex OAuth 2.0 flow.
- **Over maintaining Playwright**: Playwright with `headless=False` requires a display server (Xvfb on VPS), takes ~180s per link, breaks on UI changes, and cannot run in standard Docker without special configuration. REST API takes <1s and has no UI dependency.

### Remarketing Scheduler

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| APScheduler | `3.10.4` (already installed) | Job scheduling for follow-up sequences | Stay on 3.x — APScheduler 4.x broke `BackgroundScheduler` API, renamed `add_job` to `add_schedule`, and requires migration effort for zero benefit in this project |
| `AsyncIOScheduler` | (part of apscheduler 3.x) | Async-compatible scheduler for FastAPI | Preferred over `BackgroundScheduler` in async FastAPI context — avoids threadpool overhead |

---

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic` v2 | Already present via FastAPI | Validate payment link request/response schemas | Model Asaas API request/response payloads for type safety |
| `redis` | `5.0.8` (already installed) | Store conversation history per phone number | Use `HSET phone:{number} history {json}` with TTL 24h — already configured |
| `python-dotenv` | `1.0.1` (already installed) | Load `ASAAS_API_KEY` env var | Already handles all secrets |

---

## Installation

```bash
# No new packages required for LLM intelligence improvements
# Anthropic SDK already supports prompt caching and context editing

# For Asaas payment API — httpx already installed, just add API key to .env
# Add to .env:
# ASAAS_API_KEY=$aact_hmlg_...  (sandbox)
# ASAAS_API_KEY=$aact_prod_...  (production)
# ASAAS_BASE_URL=https://api-sandbox.asaas.com  (switch to production URL when ready)

# If Playwright dependency can be removed after migration:
pip uninstall playwright
# Remove chromium install step from Dockerfile (saves ~300MB image size)
```

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Asaas API | e-Rede REST API | Only if business requirement is to keep Rede as payment processor. e-Rede REST processes transactions but requires PCI-compliant card data handling — not a hosted link solution. Requires OAuth 2.0 migration before Jan 5, 2026. |
| Asaas API | Efí Bank (Gerencianet) | If credit card rate matters: Efí charges 3.49% vs Asaas 1.99%+R$0.49 (break-even depends on ticket size). Efí has better Pix documentation and webhook reliability reputation. |
| Asaas API | Cielo Link de Pagamento | If client already has Cielo acquirer account. Cielo has a dedicated `/v1/paymentLinks` endpoint. More complex setup, larger enterprise-oriented. |
| Prompt caching (native) | LangChain memory | LangChain adds 500MB of dependencies, abstracts away Claude-specific optimizations, and adds latency. For a single-model, single-provider project, native Anthropic SDK is strictly better. |
| Redis for conversation state | PostgreSQL for conversation state | If conversation history needs to survive Redis flush or be queryable for analytics. Currently Redis is already deployed and 24h TTL matches the use case. |
| APScheduler 3.x | APScheduler 4.x | APScheduler 4.x only if starting fresh. Migration from 3.x to 4.x requires rewriting all `add_job` calls, changing scheduler initialization, and retesting persistence. Not worth it for remarketing-only changes. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| LangChain / LangGraph | Adds 500MB of dependencies for features already available natively in the Anthropic SDK (conversation history, tool use, multi-agent). Would require rewriting all 5 existing agents. | Anthropic SDK directly |
| Playwright `headless=False` for Rede | Requires display server (Xvfb) in Docker, takes ~180s, fragile to UI changes, blocks thread | Asaas REST API |
| Gemini SDK (`google-generativeai`) | Already identified in codebase STACK.md as present but the project decision is Claude Haiku 4.5 as primary. Gemini adds API key exposure risk and split-model complexity. Remove when possible. | Anthropic SDK exclusively |
| APScheduler 4.x | Breaking API change from 3.x with no feature benefit for this use case; `BackgroundScheduler` renamed, `add_job` semantics changed | APScheduler 3.x (keep current) |
| Vector database (Pinecone, Qdrant, etc.) | Ana does not need semantic search — the knowledge base is small (<5KB), static, and already injected as system prompt text | System prompt injection |
| OpenAI Whisper (via httpx) | Already in codebase stack but not confirmed needed for this milestone. Adds per-minute API cost and complexity. | Only add if voice message transcription is explicitly scoped |

---

## Stack Patterns by Variant

**For conversation context tracking (multi-turn dialog):**
- Store `List[dict]` message history in Redis key `conv:{phone_number}` with TTL 86400 (24h)
- On each incoming message: load history, append user message, call Claude with full history, append assistant response, save back to Redis
- Add `cache_control: {"type": "ephemeral"}` to system prompt — triggers caching after 4,096 tokens threshold
- Do NOT summarize or truncate history for typical WhatsApp consultations (10-30 turns easily fits in 200k context)

**For intent classification improvement:**
- Keep orchestrator as Claude Haiku 4.5 call with structured output (JSON)
- Pass last 3-5 turns of conversation to orchestrator, not just current message — prevents misclassification on follow-up messages like "sim" or "pode ser"
- Use explicit XML tags in system prompt for context blocks: `<conversation_history>`, `<current_message>`, `<patient_state>`

**For payment link generation via Asaas:**
- Create `app/agents/payment_worker.py` mirroring `rede_worker.py` structure
- Single async function `generate_payment_link(plan: str, modality: str, installments: int) -> str` that returns the Asaas link URL
- No Playwright, no threads, pure `httpx.AsyncClient` with `access_token` header

**For remarketing scheduler (APScheduler 3.x + AsyncIOScheduler):**
- Replace `BackgroundScheduler` with `AsyncIOScheduler` for FastAPI compatibility
- Job store already configured with SQLAlchemy — keep that
- Add three job templates per lead: 24h, 7d, 30d (cancel remaining on conversion)

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `anthropic>=0.50.0` | `fastapi 0.115.0` | No conflict; SDK is pure HTTP client |
| `apscheduler 3.10.4` | `sqlalchemy 2.0.35` | `SQLAlchemyJobStore` works with SQLAlchemy 2.0 in 3.10.x |
| `httpx 0.27.0` | Asaas API v3 | Async client; use `httpx.AsyncClient` with `headers={"access_token": key}` |
| `pydantic v2` (FastAPI) | Asaas response schemas | Pydantic v2 `model_validate` for parsing Asaas JSON responses |

---

## Sources

- [Claude Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview) — confirmed Haiku 4.5 model ID, pricing, context window (HIGH confidence)
- [Prompt Caching — Anthropic Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — confirmed Haiku 4.5 support, 4,096 token minimum, Python implementation (HIGH confidence)
- [Context Editing — Anthropic Docs](https://platform.claude.com/docs/en/build-with-claude/context-editing) — confirmed beta header, tool result clearing strategy (HIGH confidence)
- [Asaas Payment Links Reference](https://docs.asaas.com/reference/criar-um-link-de-pagamentos) — endpoint, auth header, installment fields (HIGH confidence)
- [Asaas Authentication Docs](https://docs.asaas.com/docs/autenticação) — `access_token` header, sandbox vs production key prefixes (HIGH confidence)
- [Efí Bank Payment Link Docs](https://dev.efipay.com.br/en/docs/api-cobrancas/link-de-pagamento/) — two-step vs one-step endpoint, required fields (MEDIUM confidence)
- [e-Rede OAuth 2.0 Migration](https://mayconbraga.com.br/blog/conteudo/mudancas-na-api-da-erede-migracao-obrigatoria-para-oauth-20-ate-05-01-2026) — OAuth 2.0 deadline Jan 5 2026, token renewal every 24 min (MEDIUM confidence)
- [APScheduler 4.x Migration Guide](https://apscheduler.readthedocs.io/en/master/migration.html) — confirmed breaking API changes in 4.x (HIGH confidence)
- [Agent State Management: Redis vs Postgres](https://www.sitepoint.com/state-management-for-long-running-agents-redis-vs-postgres/) — Redis for active session state recommendation (MEDIUM confidence)

---

## Open Questions (LOW confidence — need validation)

1. **Asaas production fee structure for Thaynara's ticket size**: Current info is R$0.49 + 1.99% per installment transaction. Verify actual take-home per R$350 consultation plan with 3x installments before committing.
2. **e-Rede native payment link endpoint**: Research could not confirm whether `developer.userede.com.br` offers a hosted payment link endpoint (vs transaction-only). If Thaynara is contractually required to use Rede as acquirer, deeper investigation of Rede portal API (after OAuth 2.0 migration) is needed.
3. **Asaas account opening requirements**: Requires Brazilian CNPJ/CPF. Verify Thaynara has the necessary registration for Asaas account creation before committing to this migration.

---

*Stack research for: WhatsApp AI agent — intelligence + payment migration + remarketing*
*Researched: 2026-04-07*
