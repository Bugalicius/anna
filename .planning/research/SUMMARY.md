# Project Research Summary

**Project:** Agente Ana — WhatsApp AI Scheduling Agent (Next Milestone)
**Domain:** Conversational AI scheduling agent for single-practitioner health clinic
**Researched:** 2026-04-07
**Confidence:** HIGH (codebase confirmed), MEDIUM (external API behavior), LOW (scale thresholds)

## Executive Summary

Agente Ana is a multi-agent WhatsApp bot for nutritionist Thaynara Teixeira, with Phases 1-3 already implemented (FastAPI backbone, 5 agents, 104 tests passing). The next milestone is not a greenfield build — it is a precision improvement sprint on a partially broken but structurally sound foundation. The core architecture (Orchestrator → Router → FSM Agents → Workers) is correct and must not be replaced; the failures are at specific wiring points: the FSM ignores LLM-extracted state updates, the rescheduling flow sends confirmation before the Dietbox API call is made, and the in-memory agent state dict is wiped on every process restart. Fixing these three issues — context-aware FSM dispatch, correct rescheduling action sequencing, and Redis state persistence — unblocks production deployment.

The recommended approach builds in a strict dependency order: conversation intelligence improvements first (unblocks everything), then payment gateway migration away from Playwright/Rede (hard production blocker), then remarketing scheduler validation (deferred until the booking flow it depends on is reliable), and finally Meta Cloud API hardening (idempotency, HMAC enforcement, LGPD audit). No new dependencies are required for the intelligence improvements — the Anthropic SDK already supports prompt caching and context editing. The only new external service needed is Asaas (REST payment links), which replaces the broken Playwright/Rede automation with a sub-1-second API call and eliminates the need for a display server on the VPS.

The highest risk is the technical debt cluster that "looks done but isn't": rescheduling confirmation without Dietbox write, APScheduler remarketing with an unawaited coroutine, payment receipt detection via message length, and hardcoded PIX/Rede credentials in source. Each item individually is a medium fix, but deployed together unchecked they would result in corrupt Dietbox data, zero remarketing delivery, and a security audit failure. The roadmap must include a "verification pass" on all "looks done but isn't" items before any phase is marked complete.

---

## Key Findings

### Recommended Stack

The existing stack (FastAPI 0.115, SQLAlchemy 2.0, APScheduler 3.10, Redis 5, Anthropic SDK, PostgreSQL 15) is not being replaced. Zero new packages are required for conversation intelligence improvements — the Anthropic SDK already supports prompt caching (`cache_control: {"type": "ephemeral"}` on system prompt, activates at 4,096 token threshold, reduces Haiku 4.5 input costs 90%) and context editing (beta header `context-management-2025-06-27`, strips stale tool results server-side). For the payment gateway, Asaas REST API v3 replaces the Playwright/Rede automation entirely — `httpx` is already installed, only an `ASAAS_API_KEY` env var is needed, and the `POST /v3/paymentLinks` endpoint generates shareable links in under 1 second. APScheduler must stay on 3.x (`3.10.4`); APScheduler 4.x has breaking API changes with no feature benefit for this project. `AsyncIOScheduler` (not `BackgroundScheduler`) is required for correct FastAPI event loop integration.

**Core technologies:**
- Claude Haiku 4.5 (`claude-haiku-4-5-20251001`): Primary LLM — 200k context, $1/$5/MTok, already configured
- Anthropic prompt caching: Reduces system prompt costs to $0.10/MTok on cache hits; requires >4,096 tokens system prompt
- Asaas REST API v3: Payment links via `POST /v3/paymentLinks`; replaces Playwright/Rede; Pix zero-fee, card R$0.49+1.99%
- `httpx.AsyncClient`: Already installed; used for Asaas HTTP calls with `access_token` header
- APScheduler 3.10 + `AsyncIOScheduler`: Stay on 3.x; switch from BackgroundScheduler to AsyncIOScheduler for FastAPI compatibility
- Redis 5: Already deployed; use for FSM state serialization (`agent:{phone_hash}`, 24h TTL) and webhook deduplication (`msg:{message_id}`, 4h TTL)

### Expected Features

Research identified 5 features that must ship for any real patient to use Ana reliably, 3 features ready for the same milestone once the core is stable, and 3 features deferred to v2+.

**Must have (P1 — blocks production):**
- Inline FAQ during active flow — patient asking "qual o endereço?" mid-payment currently resets the flow; most impactful fix
- Corrected rescheduling rules — 7-day window logic is wrong; return patients lose entitlement incorrectly
- Return vs. new patient distinction — `status_paciente` collected but not propagated to rescheduling branch
- Waiting indicator before slow operations — "Um instante, por favor" before Dietbox/payment calls; patients believe bot crashed without it
- Human escalation relay — when Ana cannot resolve, notify internal number and relay; prevents dead-end conversations

**Should have (P2 — same milestone, after P1 stable):**
- APScheduler drip trigger validation end-to-end — the coroutine is unawaited; zero messages are currently sent
- Payment receipt acknowledgment improvement — replace `len(msg) > 30` heuristic with keyword/LLM classification
- Actual media sends at confirmation — wire PDF/image sends to Meta API; currently sends `[IMG: placeholder]` strings

**Defer (v2+):**
- Family discount detection and flow — niche use case; implement after reliability is proven
- Post-booking satisfaction check — high retention value; defer until booking flow is stable
- Objection handling at FSM checkpoints — wire `objections.json` into plan/payment stages; low risk but non-critical

### Architecture Approach

The existing Orchestrator-as-pure-classifier + FSM-per-agent + Router-as-state-owner architecture is correct and must be preserved. The problems are not structural — they are at three specific implementation gaps. First, the FSM dispatch (`_despachar`) routes only by current stage name with no visibility into accumulated slots or conversation history; the fix is to replace `_gerar_resposta_llm()` with a `_processar_com_contexto()` method that returns structured JSON `{nova_etapa, slots_atualizados, resposta}`, which the FSM then applies before the next dispatch. Second, `_AGENT_STATE` is an in-process Python dict that is wiped on restart; the fix is to serialize agent instances to Redis with `to_dict()/from_dict()` on every state write. Third, the Router's interrupt detection uses only hard-coded keyword lists; the fix is a lightweight LLM interrupt check (separate from the full orchestrator classification) that returns one of three codes: stage-compatible, answerable-from-KB, or intent-change.

**Major components and build order:**
1. `app/agents/atendimento.py` + `app/agents/retencao.py` — Context-aware FSM (Step 1 & 2): replace stateless LLM fallback with structured context injection; fix rescheduling action sequencing
2. `app/router.py` — Interrupt detection (Step 3): add lightweight LLM interrupt classifier; add confidence threshold check for orchestrator routing
3. `app/router.py` + both agent classes — Redis state serialization (Step 4): `to_dict()/from_dict()` pairs; replace in-memory dict; prerequisite for production
4. `app/agents/rede_worker.py` → `app/agents/payment_worker.py` — Asaas migration (Step 5): isolated behind `gerar_link_pagamento()` signature; no other component changes
5. `app/webhook.py` + `app/remarketing.py` — Meta API hardening (Step 6): webhook deduplication, HMAC enforcement, template pre-approval, remarketing coroutine fix

### Critical Pitfalls

Research identified 6 critical pitfalls confirmed directly from codebase analysis, not from external sources.

1. **Rescheduling confirms without Dietbox API write** — `AgenteRetencao` sends `MSG_CONFIRMACAO_REMARCACAO` and advances to `etapa = "concluido"` without calling `dietbox_worker.agendar_consulta()`. Prevention: enforce sequence — call external system, verify success, then send confirmation and advance state; never optimistic advance.

2. **In-memory FSM state wiped on restart** — `_AGENT_STATE` is a module-level Python dict; any process restart (deploy, OOM, reboot) silently wipes mid-conversation state; patient who already paid gets sent back to `boas_vindas`. Prevention: serialize to Redis with 24h TTL before any real patient touches the system.

3. **Playwright Rede automation broken on VPS** — `rede_worker.py` uses `headless=False` which requires a display server; VPS has none; generates 180s timeouts or Chromium launch failures. Prevention: migrate to Asaas REST API; this is a hard production blocker that cannot be worked around.

4. **Duplicate webhook delivery causes double-booking** — Meta Cloud API delivers webhooks at-least-once by design; without deduplication, the same patient message is processed twice, creating two Dietbox appointments. Prevention: store `message_id` in Redis with 4h TTL; check before any agent invocation; return HTTP 200 immediately on duplicate.

5. **Meta remarketing templates not pre-approved** — Template names in `app/remarketing.py` do not exist in Meta Business Manager; Meta returns 132000/132001 errors silently; zero messages are sent. Prevention: submit all templates and wait for APPROVED status before writing any dispatch code; allow 72h minimum for approval.

6. **Orchestrator confidence score ignored by Router** — `confianca` field is returned by the orchestrator but `router.py` never reads it; out-of-domain messages (e.g., "quero remarcar minha Netflix") get routed to specialist agents and trigger incorrect flows. Prevention: add minimum confidence threshold (0.55); below threshold → clarifying question or human escalation.

---

## Implications for Roadmap

Based on the dependency graph confirmed by architecture research, 4 phases are sufficient and the order is non-negotiable: each phase is a prerequisite for the next.

### Phase 1: Conversation Intelligence

**Rationale:** Everything else (rescheduling, remarketing, payment) depends on the FSM correctly handling context. Fixing the FSM first means all subsequent phases are built on a reliable foundation. Redis state persistence is also Phase 1 because it is a prerequisite for production deployment, not a "nice to have." This phase is entirely self-contained — zero external API dependencies.

**Delivers:** Ana handles multi-turn conversations correctly, doesn't reset on unexpected input, distinguishes return vs. new patients, persists state across restarts, routes low-confidence messages to human escalation.

**Addresses (P1 features):**
- Inline FAQ during active flow (intent-over-state routing)
- Return vs. new patient distinction
- Waiting indicator before slow operations
- Human escalation relay
- Confidence threshold check on orchestrator routing

**Avoids:**
- Pitfall 1: Rescheduling confirms without Dietbox write — fix action sequencing in retencao.py
- Pitfall 2: In-memory state lost on restart — Redis serialization
- Pitfall 6: Confidence score ignored — add threshold check in router.py

**"Looks done but isn't" items to verify in this phase:**
- `etapa = "concluido"` in retencao must not precede Dietbox API call
- `confianca` field in orchestrator response must be read by router
- `Tag.OK` routing condition (currently unreachable due to elif chain) must be fixed
- `/test/chat` endpoint must be guarded by `ENABLE_TEST_CHAT` env var
- PIX key and Dietbox UUIDs must be moved to env vars (security prerequisite)

**Research flag:** Standard patterns — context-aware FSM with structured LLM output is well-documented; no additional research phase needed.

---

### Phase 2: Payment Gateway Migration

**Rationale:** The Rede/Playwright integration is a hard production blocker — it cannot run on the VPS. This phase is independent of Phase 1's FSM changes (it is isolated behind the `gerar_link_pagamento()` function signature) but depends on Phase 1 completing because the corrected atendimento FSM is what calls the payment worker. Migration to Asaas requires account setup (CNPJ/CPF verification) which may add lead time.

**Delivers:** Payment link generation via REST API (<1s, no display server, sandbox-to-production path); Playwright dependency removed from Dockerfile (saves ~300MB image size); Rede PV merchant code moved to env var.

**Addresses (P2 features):**
- Payment receipt acknowledgment improvement — replace `len(msg) > 30` with LLM/keyword classification

**Avoids:**
- Pitfall 3 (partial): Playwright VPS incompatibility — fully eliminated
- Technical debt: `headless=False` server-side code, hardcoded `REDE_PV` in source

**Research flag:** Needs validation on one open question — Thaynara must have a Brazilian CNPJ/CPF for Asaas account creation. Verify before committing to Asaas; if blocked, evaluate Efí Bank (same REST pattern, slightly more complex OAuth 2.0 flow). Asaas fee structure for Thaynara's ticket size (R$350 consultation, 3x installments) should be calculated before committing.

---

### Phase 3: Remarketing Scheduler Validation

**Rationale:** The remarketing code exists but has never delivered a real message — the APScheduler job dispatches an unawaited coroutine, so the `send_template` call is silently dropped. This phase fixes the async dispatch and validates the end-to-end sequence (scheduler fires → Meta API receives call → template delivered). Must come after Phase 1 (FSM state must be reliable to check patient stage before dispatching) and after Meta templates are approved in Business Manager (72h lead time).

**Delivers:** Working 24h/7d/30d drip sequence for cold leads; remarketing correctly skipped when patient has an active conversation; APScheduler using `AsyncIOScheduler` not `BackgroundScheduler`.

**Addresses (P2 features):**
- APScheduler drip triggers end-to-end
- Actual media sends at confirmation (wire PDF/image to Meta API)

**Avoids:**
- Pitfall 4: Meta templates not pre-approved — submit templates before coding dispatch; verify APPROVED status programmatically at startup
- Performance trap: `time.sleep(2)` inside scheduler job blocks thread at scale
- Integration gotcha: APScheduler with gunicorn multi-process spawns duplicate jobs — use single scheduler process or external queue

**Research flag:** Needs pre-flight business process: Meta template submission and approval (72h minimum) must be initiated before Phase 3 coding begins. Template content must use "utility/service" category, not "marketing", to avoid higher costs and lower delivery rates.

---

### Phase 4: Meta Cloud API Hardening

**Rationale:** This phase addresses the production security and reliability properties of the inbound webhook channel. Deferred to last because the system must be functionally correct before adding hardening — fixing idempotency on a broken booking flow would mask bugs. Also includes LGPD compliance audit (patient data in LLM prompts) and test endpoint security.

**Delivers:** Idempotent webhook processing (duplicate Meta deliveries cannot create duplicate bookings); HMAC enforcement fails closed (empty secret → reject all webhooks at startup); LGPD-aware LLM prompt construction (no raw CPF/phone in Claude API calls); prompt injection protection.

**Avoids:**
- Pitfall 3: Duplicate webhook double-booking — `message_id` deduplication in Redis
- Security mistake: `META_APP_SECRET` empty → forged webhooks accepted
- Security mistake: Patient CPF/phone sent to external Claude API in violation of LGPD
- Security mistake: Prompt injection via patient WhatsApp messages revealing internal escalation number

**Research flag:** LGPD compliance scope needs legal validation — the current approach (pseudonymize before LLM calls, omit CPF/phone from prompts) is technically sound but the specific fields to redact and the consent language for WhatsApp opt-in should be reviewed by a Brazilian data protection specialist if Thaynara's practice scales. For current single-practitioner scale, the technical controls are sufficient.

---

### Phase Ordering Rationale

- **Phase 1 before Phase 2:** The corrected FSM is what calls `gerar_link_pagamento()`. A broken FSM calling a correct payment API is worse than a broken FSM calling a broken one — it would create orphaned Asaas payment links without confirmed bookings.
- **Phase 1 before Phase 3:** Remarketing must check patient FSM stage before dispatching to avoid interrupting active conversations. The stage check requires reliable state, which requires Redis persistence from Phase 1.
- **Phase 2 before Phase 4:** Webhook hardening should cover the complete inbound-to-outbound flow including the payment confirmation path. Having the real payment worker in place first means hardening tests are meaningful.
- **Phase 3 before Phase 4:** Meta template approval (Phase 3 prerequisite) must be verified as part of Phase 4's startup checks. Logically, templates must exist before the startup validator can check them.

### Research Flags

Phases needing deeper investigation during planning:
- **Phase 2:** Asaas account eligibility and fee verification — open question requiring Thaynara to confirm CNPJ/CPF availability before Asaas account can be opened. If Asaas is blocked, Efí Bank is the fallback (same pattern, higher fee, more complex OAuth 2.0).
- **Phase 4:** LGPD audit scope — the technical controls (pseudonymization) are clear; the compliance boundary (which fields, what consent language) may need specialist input as patient volume grows.

Phases with standard patterns (no additional research needed):
- **Phase 1:** Context-aware FSM + Redis state serialization + LLM interrupt detection are all well-documented patterns with direct code references in ARCHITECTURE.md.
- **Phase 3:** APScheduler 3.x async dispatch patterns are confirmed in official docs; the fix is mechanical (add `await`, switch to `AsyncIOScheduler`).

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Anthropic SDK features confirmed from official docs; Asaas API confirmed from official reference; APScheduler migration risk confirmed from changelog |
| Features | HIGH | Primary source is the existing codebase plus PROJECT.md; feature gaps confirmed from direct code reading, not inference |
| Architecture | HIGH | Patterns confirmed from codebase structure; build order reflects actual dependency graph; anti-patterns identified from confirmed bugs |
| Pitfalls | HIGH (codebase), MEDIUM (external) | Codebase pitfalls confirmed from direct source analysis; Meta API behavior from official docs; scale thresholds estimated |

**Overall confidence:** HIGH for scope, decisions, and phase order. MEDIUM for two specific external unknowns (Asaas account eligibility, LGPD specialist scope).

### Gaps to Address

- **Asaas account opening:** Requires Thaynara's CNPJ or CPF. Must be confirmed before Phase 2 coding begins. If unavailable, evaluate Efí Bank (comparable API, higher card rate). Contact Asaas support to confirm requirements — address during Phase 2 planning kickoff.
- **e-Rede hosted payment link via REST:** Research could not confirm whether a hosted payment link (shareable URL, not card processing) exists in the e-Rede REST API. The decision to use Asaas is correct, but if a business requirement forces keeping Rede as acquirer, this needs a dedicated investigation of `developer.userede.com.br` post-OAuth 2.0 migration.
- **Asaas fee calculation for Thaynara's ticket:** R$0.49 + 1.99% per transaction. For a R$350 plan at 3x installments, each installment is R$116.67; fee = R$0.49 + R$2.32 = R$2.81 per installment = R$8.42 total vs. R$350 revenue (2.4%). Confirm Thaynara accepts this before committing to Asaas.
- **Meta template content for remarketing:** Template names exist in code (`follow_up_geral`, `objecao_preco`, `urgencia_vagas`). The actual template text must be drafted and submitted to Meta before Phase 3 begins. Template content must avoid promotional language in service/utility category to prevent reclassification.

---

## Sources

### Primary (HIGH confidence)
- Existing codebase: `app/agents/atendimento.py`, `app/agents/retencao.py`, `app/router.py`, `app/remarketing.py`, `app/agents/rede_worker.py` — direct source analysis
- `.planning/codebase/CONCERNS.md` — existing concern audit
- [Claude Models Overview](https://platform.claude.com/docs/en/about-claude/models/overview) — Haiku 4.5 model ID, pricing, context window
- [Anthropic Prompt Caching Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — Haiku 4.5 support, 4,096 token minimum
- [Anthropic Context Editing Docs](https://platform.claude.com/docs/en/build-with-claude/context-editing) — beta header, tool result clearing
- [Asaas Payment Links Reference](https://docs.asaas.com/reference/criar-um-link-de-pagamentos) — endpoint, auth header, installment fields
- [Asaas Authentication Docs](https://docs.asaas.com/docs/autenticacao) — access_token header, sandbox vs production key prefixes
- [APScheduler 4.x Migration Guide](https://apscheduler.readthedocs.io/en/master/migration.html) — confirmed breaking API changes in 4.x
- [OWASP LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/) — prompt injection production patterns

### Secondary (MEDIUM confidence)
- [e-Rede OAuth 2.0 Migration](https://mayconbraga.com.br/blog/conteudo/mudancas-na-api-da-erede-migracao-obrigatoria-para-oauth-20-ate-05-01-2026) — OAuth 2.0 deadline confirmed
- [Efí Bank Payment Link Docs](https://dev.efipay.com.br/en/docs/api-cobrancas/link-de-pagamento/) — fallback gateway comparison
- [Guide to WhatsApp Webhooks (Hookdeck)](https://hookdeck.com/webhooks/platforms/guide-to-whatsapp-webhooks-features-and-best-practices) — at-least-once delivery, idempotency patterns
- [WhatsApp Template Approval Checklist (Wuseller)](https://www.wuseller.com/blog/whatsapp-template-approval-checklist-27-reasons-meta-rejects-messages/) — 27 Meta rejection reasons
- [APScheduler + FastAPI multi-process pitfall](https://github.com/fastapi/fastapi/discussions/9143) — duplicate job execution in gunicorn
- [LGPD health data compliance (IBA)](https://www.ibanet.org/protections-health-data-brazilds) — sensitive data classification, consent requirements
- [Rasa: LLM Chatbot Architecture](https://rasa.com/blog/llm-chatbot-architecture) — FSM + LLM hybrid patterns
- [Anthropic: Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — context injection patterns for agents

### Tertiary (LOW confidence)
- Scale thresholds (10/200/1000 concurrent patients) — estimated from architecture patterns, not measured
- LGPD pseudonymization sufficiency — reasonable technical interpretation, not legal opinion

---

*Research completed: 2026-04-07*
*Ready for roadmap: yes*
