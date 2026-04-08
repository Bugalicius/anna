# Architecture Research

**Domain:** Multi-agent WhatsApp scheduling assistant with hybrid FSM + LLM dialog management
**Researched:** 2026-04-07
**Confidence:** HIGH

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Transport Layer                               │
│   Meta Cloud API (WhatsApp) ──► POST /webhook ──► app/webhook.py     │
│                                  (HMAC verify, dedup, BackgroundTask) │
└──────────────────────────────────────┬───────────────────────────────┘
                                       │ route_message()
┌──────────────────────────────────────▼───────────────────────────────┐
│                         Routing Layer                                 │
│                        app/router.py                                  │
│                                                                       │
│   ┌─────────────────────────────────────────────────────────────┐    │
│   │  Interrupt Check (mid-FSM intent change detection)          │    │
│   │  → if active agent + redirect keywords → drop state, re-route│   │
│   └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│   ┌──────────────────────────────────────────────────────────┐       │
│   │  Active Agent Check (bypass orchestrator if mid-flow)    │       │
│   └──────────────────────────────────────────────────────────┘       │
│                         │ (if no active agent)                        │
│   ┌─────────────────────▼────────────────────────────────────┐       │
│   │         Orchestrator — Intent Classifier                  │       │
│   │              app/agents/orchestrator.py                   │       │
│   │   Claude Haiku → JSON {intencao, confianca}              │       │
│   └──────┬─────────────────────────────────────┬─────────────┘       │
│          │ atendimento                         │ retencao             │
└──────────┼─────────────────────────────────────┼─────────────────────┘
           │                                     │
┌──────────▼──────────┐              ┌───────────▼────────────────┐
│   Agent 1           │              │   Agent 2                  │
│   Atendimento       │              │   Retencao                 │
│   (10-step FSM)     │              │   (FSM: remarcar/cancelar) │
│  app/agents/        │              │   app/agents/retencao.py   │
│  atendimento.py     │              │                            │
│                     │              │   + Remarketing sequences  │
│  Per-turn context   │              │   + Lembretes (scheduler)  │
│  injection into     │              └───────────┬────────────────┘
│  LLM system prompt  │                          │
└──────────┬──────────┘                          │
           │                                     │
     ┌─────▼──────────────────────────┐          │
     │      Worker Layer              │          │
     │  Dietbox Worker ◄──────────────┼──────────┘
     │  app/agents/dietbox_worker.py  │
     │  (slots, CRUD, agendamento)    │
     │                                │
     │  Rede Worker                   │
     │  app/agents/rede_worker.py     │
     │  (link pagamento — migrar API) │
     └────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────────────────────┐
│                    Persistence + Scheduling                       │
│  SQLite/PostgreSQL (Contact, Conversation, Message,              │
│                      RemarketingQueue)     app/database.py       │
│  Redis (FSM state — planned)               _AGENT_STATE (dict)  │
│  APScheduler (remarketing, retry)          app/remarketing.py   │
│  KnowledgeBase singleton                   app/knowledge_base.py│
└──────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Boundary Rule |
|-----------|----------------|---------------|
| `app/webhook.py` | Validate HMAC, deduplicate, persist raw message, enqueue | Never produces LLM output; never touches agent state |
| `app/router.py` | Load contact, run interrupt check, optionally call orchestrator, dispatch to agent, send replies | Only place that reads/writes `_AGENT_STATE`; owns tag updates |
| `app/agents/orchestrator.py` | Classify single message into intent; return routing struct | No side effects; no agent state access; pure classifier |
| `app/agents/atendimento.py` | Drive new-patient booking funnel (10-step FSM + LLM fallback) | Never sends messages directly; returns `list[str]`; calls workers |
| `app/agents/retencao.py` | Rescheduling, cancellation, remarketing message text generation | Never sends messages; never touches Rede worker |
| `app/agents/dietbox_worker.py` | All Dietbox API interactions: slot lookup, patient CRUD, appointment booking | No conversation logic; returns structured dicts |
| `app/agents/rede_worker.py` | Payment link generation (currently Playwright; target: REST API) | No conversation logic; returns `LinkPagamento` dataclass |
| `app/knowledge_base.py` | Singleton providing all static business rules, prices, FAQ | Read-only; agents import but never mutate |
| `app/escalation.py` | Forward clinical question + history to nutritionist's private number | Never exposed to patient; internal routing only |
| `app/tags.py` | Enforce valid `Contact.stage` transitions | Transition table is the single source of valid stage progressions |
| `app/remarketing.py` + `app/retry.py` | APScheduler jobs: dispatch due remarketing, retry failed sends | No in-band conversation; purely scheduler-driven |

---

## Architectural Patterns

### Pattern 1: FSM-with-LLM-Fallback (current — partially broken)

**What:** Each agent owns a deterministic FSM. Named stages (`etapa` field) dispatch to step-specific handler methods. When a step cannot deterministically handle the user input (objection, unexpected question), it falls back to `_gerar_resposta_llm()` passing the current stage name and conversation history.

**When to use:** Structured funnels where each step has a clear expected input (choose plan, choose slot, confirm payment). Deterministic paths are fast, cheap, and predictable; LLM fallback handles edge cases only.

**Current problem:** The FSM dispatch (`_despachar`) only checks `self.etapa` — it has no visibility into what the patient actually said in the last turn or what data was accumulated. If the LLM fallback produces a reply that logically moves the conversation forward, the FSM does not transition. The stage stays the same on the next message.

**Trade-offs:**
- Pro: Predictable, testable, cheap (most paths skip LLM)
- Con (as-implemented): LLM responses are fire-and-forget — they do not update state, so the FSM diverges from the actual conversation

**Recommended fix (Pattern 3 below).**

---

### Pattern 2: Orchestrator-as-Intent-Classifier-Only (current — good)

**What:** The Orchestrator (Agent 0) is a pure classifier: single LLM call, returns `{intencao, confianca}`, no side effects. The Router owns all routing decisions. Once an agent is active (mid-FSM), the Orchestrator is bypassed entirely for subsequent turns.

**When to use:** Always. The Orchestrator's single-message view is deliberately narrow — it does not see conversation history. This makes classification cheap and fast (100-token response, 200-token prompt).

**Trade-offs:**
- Pro: Stateless, testable, fast, costs under 0.001 USD per classification
- Con: Cannot reclassify intent based on accumulated context (e.g., if patient says "ok" mid-funnel, the orchestrator cannot know whether "ok" means "confirmed payment" or "confirmed plan")
- Mitigation: The Router's active-agent-bypass correctly suppresses the Orchestrator while a funnel is active. The Orchestrator only re-runs when no active agent exists.

---

### Pattern 3: Context-Injected FSM (recommended — milestone target)

**What:** Replace the current stage-only dispatch with context-aware dispatch. On each turn, before calling either the deterministic handler or the LLM fallback, inject into the system prompt: current stage, accumulated slots (name, plan, modality, chosen slot, payment method), last N turns of conversation history, and any active business rules for this stage.

The LLM sees the full picture and is asked to do one of:
1. Extract/update any newly provided slot values from the current message
2. Detect if the user is implicitly advancing (e.g., "ok pix" means payment_method = pix AND advance to pagamento)
3. Detect if the user is making an off-flow request (intent interrupt) that the deterministic layer missed

The return from the LLM is structured JSON, not free-form text, when a slot extraction is needed. Free-form text is only used for the actual WhatsApp reply.

**When to use:** Replace the current `_gerar_resposta_llm()` with a `_processar_com_contexto()` method that takes the full agent state and returns `{nova_etapa: str, slots_atualizados: dict, resposta: str}`. The FSM then applies `nova_etapa` and `slots_atualizados` before returning `resposta`.

**Example structure:**
```python
# Inside each FSM agent — replaces ad-hoc _gerar_resposta_llm calls
def _processar_com_contexto(self, msg: str) -> tuple[str, dict, str]:
    """
    Returns (nova_etapa, slot_updates, resposta_para_paciente).
    The FSM applies the returned etapa and slots before next dispatch.
    """
    payload = {
        "etapa_atual": self.etapa,
        "slots": {
            "nome": self.nome,
            "plano": self.plano_escolhido,
            "modalidade": self.modalidade,
            "slot_escolhido": self.slot_escolhido,
            "forma_pagamento": self.forma_pagamento,
        },
        "historico_recente": self.historico[-6:],
        "mensagem": msg,
    }
    # LLM call with structured output prompt
    # Returns structured JSON + reply text
```

**Trade-offs:**
- Pro: FSM stays deterministic for happy-path flows; LLM handles context only when needed
- Pro: Slot updates are explicit and auditable, not implicit
- Pro: One additional LLM call per ambiguous turn, not per every turn
- Con: Slightly more complex prompt engineering for the structured extraction
- Con: Adds one LLM call on ambiguous turns (but most turns follow the happy path, so cost impact is low)

---

### Pattern 4: Interrupt Detection at Router (current — partial, needs strengthening)

**What:** The Router currently checks for hard-coded keyword lists (`_REMARCAR_KW`, `_CANCELAR_KW`) mid-FSM to redirect the patient to Agente 2. This is the right pattern but needs to extend beyond just rescheduling/cancellation.

**When to use:** Any time the patient's message is semantically incompatible with the current FSM stage. Examples: "actually I want to pay by PIX" while at the plan-selection stage; "what's the price again?" during the slot-selection stage.

**Recommended extension:** Add a lightweight interrupt-check prompt (separate from the full orchestrator classification) that runs only when the deterministic FSM handler returns no match. This check asks: "Is this message a stage-compatible response, a question answerable with current KB, or an intent change?" and returns one of three codes. Only an intent-change code triggers re-routing; questions are answered inline via the KB; compatible responses pass through.

**Trade-offs:**
- Pro: Eliminates the current behavior where patients get "stuck" because a single unexpected word (e.g., "espera" / "wait") doesn't match any pattern in the deterministic handler
- Con: One extra LLM call on ambiguous messages (mitigated by cheap Haiku 4.5 cost)

---

### Pattern 5: Structured State Serialization (planned, not yet implemented)

**What:** `_AGENT_STATE` is currently an in-process Python dict. If the process restarts, all mid-conversation state is lost and patients get sent back to `boas_vindas`. The documented plan is to serialize FSM state to Redis.

**When to use:** Required before production deployment. Each `AgenteAtendimento` and `AgenteRetencao` instance must have a `to_dict() / from_dict()` pair. The Router uses `phone_hash` as the Redis key with a 24h TTL.

**Recommended implementation:**
```python
# In router.py — replace in-memory dict access
agent_data = redis_client.get(f"agent:{phone_hash}")
if agent_data:
    agent = AgenteAtendimento.from_dict(json.loads(agent_data))
else:
    agent = AgenteAtendimento(phone, phone_hash)
# ... process ...
redis_client.setex(f"agent:{phone_hash}", 86400, json.dumps(agent.to_dict()))
```

**Trade-offs:**
- Pro: Survives process restart, deployments, and horizontal scale
- Con: Adds Redis as a required dependency (already planned in architecture docs)
- Con: `historico` list may grow large — apply sliding window (last 20 messages max) before serializing

---

## Data Flow

### Inbound Message — Full Lifecycle

```
Patient sends WhatsApp message
    │
    ▼
Meta Cloud API → POST /webhook
    │ (HMAC-SHA256 verify, dedup by meta_message_id)
    │ (upsert Contact + Message in DB)
    │
    ▼ BackgroundTask
route_message(phone, phone_hash, text, meta_message_id)
    │
    ├─► Load Contact from DB (stage, collected_name)
    │
    ├─► If stage = cold_lead/remarketing → cancel pending remarketing jobs
    │
    ├─► Check _AGENT_STATE[phone_hash]
    │       │
    │       ├─ Active AgenteAtendimento (mid-funnel):
    │       │     ├─ Run interrupt check (rescheduling/cancel keywords)
    │       │     │     └─ If interrupt → drop state, fall through to orchestrator
    │       │     └─ If no interrupt → agent.processar(text) → list[str]
    │       │
    │       └─ Active AgenteRetencao (mid-reschedule):
    │             └─ agent.processar_remarcacao(text) or processar_cancelamento(text)
    │
    ├─► (No active agent) → Orchestrator: rotear(text, stage, primeiro_contato)
    │       └─ Returns {agente, intencao, confianca}
    │
    ├─► Dispatch:
    │     "atendimento" → AgenteAtendimento.processar(text)
    │     "retencao"    → AgenteRetencao.processar_remarcacao/cancelamento(text)
    │     "escalacao"   → escalar_para_humano() (sends to internal number, NOT exposed)
    │     "padrao"      → static reply from orchestrator
    │
    ├─► Agent may call workers synchronously:
    │     dietbox_worker.consultar_slots_disponiveis()  [HTTP + Playwright token]
    │     dietbox_worker.processar_agendamento()        [HTTP POST]
    │     rede_worker.gerar_link_pagamento()            [Playwright — target: REST API]
    │
    ├─► Update Contact.stage tag via tags.py (deterministic transition table)
    │
    └─► _enviar(meta, phone, list[str]) → MetaAPIClient.send_text() × N messages
```

### Outbound Scheduler Flow

```
APScheduler (every 1 min)
    │
    ▼
remarketing.py: _dispatch_due_messages()
    │
    ├─► Query RemarketingQueue WHERE due_at <= now AND status = pending
    ├─► Enforce Redis rate limit (30/min)
    ├─► MetaAPIClient.send_template(phone, template_name, variables)
    └─► After MAX_REMARKETING (5): set Contact.stage = archived

APScheduler (every 5 min)
    │
    ▼
retry.py: _retry_failed_messages()
    └─► Exponential backoff retry for messages with status = retrying
```

### State Management — Per-Conversation

```
Contact (DB, persistent)
  └─ stage: Tag enum value — current lifecycle position
  └─ collected_name, push_name
  └─ last_message_at

_AGENT_STATE (in-process dict — planned: Redis)
  └─ phone_hash → AgenteAtendimento | AgenteRetencao instance
       └─ etapa: str — current FSM stage
       └─ slots: nome, plano, modalidade, slot_escolhido, forma_pagamento
       └─ historico: list[{role, content}] — last N turns

KnowledgeBase (in-process singleton — loaded at startup)
  └─ plans, prices, FAQ, system_prompt — all static, never mutated by agents
```

---

## Component Boundaries

### What Talks to What

| From | To | Via | Notes |
|------|----|-----|-------|
| `webhook.py` | `router.py` | `BackgroundTasks` call | Only passes phone, phone_hash, text, message_id |
| `router.py` | `orchestrator.py` | Direct function call | Only when no active agent in state |
| `router.py` | `atendimento.py` | Direct method call (`agent.processar()`) | Returns `list[str]` only |
| `router.py` | `retencao.py` | Direct method call | Returns `list[str]` only |
| `router.py` | `escalation.py` | Async function call | Passes patient phone + history summary |
| `router.py` | `meta_api.py` | Async HTTP | Sends each string as separate WA message |
| `router.py` | `database.py` | SQLAlchemy session | Read Contact; write stage/name |
| `atendimento.py` | `dietbox_worker.py` | Sync function call | Returns dict `{sucesso, id_paciente, ...}` |
| `atendimento.py` | `rede_worker.py` | Sync function call | Returns `LinkPagamento` dataclass |
| `retencao.py` | `dietbox_worker.py` | Sync function call | Slot lookup for rescheduling |
| `atendimento.py` | `knowledge_base.py` | Import singleton `kb` | Read-only: prices, plans, system_prompt |
| `retencao.py` | `knowledge_base.py` | Import singleton `kb` | Read-only |
| `orchestrator.py` | Anthropic SDK | Sync HTTP | Single classification call |
| `atendimento.py` | Anthropic SDK | Sync HTTP | LLM fallback per ambiguous turn |
| `remarketing.py` | `meta_api.py` | Async HTTP | Template sends |
| `remarketing.py` | `database.py` | SQLAlchemy session | Read/update RemarketingQueue |

### What Must NOT Talk to What

| Source | Must NOT Call | Reason |
|--------|---------------|--------|
| `orchestrator.py` | Agent state (`_AGENT_STATE`) | Orchestrator is a pure classifier; state belongs to router |
| Any agent | `meta_api.py` directly | Agents return `list[str]`; only the router sends messages |
| Any agent | `database.py` directly | Persistence is the router's and scheduler's responsibility |
| `webhook.py` | Any agent directly | Routing logic belongs in `router.py` |
| `escalation.py` | Patient WhatsApp directly with the internal number | Internal number is never exposed to patients |
| `dietbox_worker.py` / `rede_worker.py` | Any other agent | Workers are leaf nodes — no upward calls |

---

## Build Order Implications

The milestone goal is improving conversation intelligence. Based on component dependencies, the correct build order is:

**Step 1 — Context-aware processing (no external dependencies)**
Modify `AgenteAtendimento._despachar()` to pass accumulated state into the LLM prompt on every step, not just the fallback. Add structured slot extraction. Change `_gerar_resposta_llm()` into `_processar_com_contexto()` that returns `(nova_etapa, slot_updates, resposta)`. This change is fully self-contained inside `atendimento.py`.

**Step 2 — Rescheduling rules fix (depends on Step 1 pattern)**
Apply the same context-aware pattern to `AgenteRetencao`. Fix the "7-day window" logic: the rule is communicated as 7 days, but the offered slots span the entire following week (Mon-Fri). Add priority ordering: nearest to preference → next nearest → furthest available. This is self-contained inside `retencao.py` + `dietbox_worker.py` (slot filtering).

**Step 3 — Interrupt detection strengthening (depends on Step 1 + 2)**
Extend the Router's keyword-based interrupt check with a lightweight LLM interrupt classifier. This is a small addition to `router.py` with no dependency on external systems.

**Step 4 — State serialization to Redis (prerequisite for production)**
Add `to_dict()/from_dict()` to both agent classes. Replace `_AGENT_STATE` in `router.py` with Redis reads/writes. This change requires Redis running but no changes to agent logic.

**Step 5 — Payment worker migration (parallel, independent)**
Migrate `rede_worker.py` from Playwright to e-Rede REST API. This is fully isolated behind the `gerar_link_pagamento()` function signature. No other component changes.

---

## Integration Points

### External Services

| Service | Integration Pattern | Current Status | Notes |
|---------|---------------------|----------------|-------|
| Meta Cloud API (WhatsApp Business) | Inbound: webhook POST; Outbound: REST (send_text, send_template) | Functional | Signature verification in `webhook.py` |
| Dietbox | REST API (slots, patient CRUD, appointments) + Playwright token refresh | Functional | Token cached 1h; Playwright headless works on VPS |
| Rede (userede.com.br) | Playwright browser automation | Broken on VPS (headless=False) | Must migrate to e-Rede REST API; ~180s latency |
| Anthropic Claude Haiku 4.5 | Sync HTTP via `anthropic` SDK | Functional | Used by Orchestrator, Atendimento, Retencao |
| Redis | Not yet integrated | Planned | Required for FSM state persistence before production |
| APScheduler + SQLAlchemyJobStore | In-process background scheduler | Configured, not battle-tested | Remarketing dispatch logic needs testing |

### Internal Boundaries — Key Conventions

| Boundary | Convention | Rationale |
|----------|------------|-----------|
| Agent → Router | Return `list[str]`; never call MetaAPI | Agents are pure domain logic; delivery is transport concern |
| Worker → Agent | Return typed dataclass or `dict {sucesso, ...}` | Agents must handle `sucesso=False` gracefully; never crash |
| LLM prompt → Agent state | System prompt must include current stage + accumulated slots | Without this, LLM "forgets" what was collected and repeats questions |
| Router → DB | Minimal writes only (stage tag, collected_name, last_message_at) | Conversation data lives in agent state, not normalized DB tables |

---

## Anti-Patterns

### Anti-Pattern 1: Stateless LLM Fallback

**What people do:** Call the LLM with only the last N messages and the current stage name. The LLM generates a reply. The FSM never updates because the reply content is never parsed for state changes.

**Why it's wrong:** The patient says "I prefer online" during slot selection. The LLM reply correctly acknowledges this. But `self.modalidade` is never set because the deterministic handler didn't match the string. Next turn, the bot asks for modality again. Patient experience breaks.

**Do this instead:** The LLM response must be structured: it returns both the conversational reply AND any slot updates. The FSM applies slot updates before returning the reply. Use Haiku's structured output (JSON) for the state part and free-form text for the reply.

---

### Anti-Pattern 2: Orchestrator Running Mid-Conversation

**What people do:** Call the Orchestrator on every message, even when a patient is in the middle of the 10-step booking funnel.

**Why it's wrong:** The Orchestrator sees only the current message without history. "Ok" from a patient confirming payment looks like `novo_lead` or `tirar_duvida` to the Orchestrator. Re-routing destroys active FSM state and confuses the patient.

**Do this instead:** The Router bypasses the Orchestrator when `_AGENT_STATE[phone_hash]` contains an active agent with a non-terminal stage. The Orchestrator only runs on fresh conversations or after a completed/dropped flow.

---

### Anti-Pattern 3: Hard-Coded String Matching for Slot Extraction

**What people do:** Check `if "pix" in msg_lower` to detect payment choice. If the patient writes "eu prefiro pagar via pix mesmo" the match works. If they write "pode ser pelo PIX" the match works. If they write "boleto não, melhor o pix" it should work but edge cases accumulate.

**Why it's wrong:** The accumulation of keyword lists becomes a maintenance burden. Complex real-world inputs (abbreviated words, mixed case, typos, ellipsis) inevitably slip through. The FSM stays stuck; the bot repeats the question.

**Do this instead:** Use hard-coded matching only for the clearest 1-word signals (`pix`, `cartao`). For anything else, delegate to the LLM with a structured extraction prompt. The cost of one Haiku call (~$0.0002) is trivially less than a confused patient abandoning the funnel.

---

### Anti-Pattern 4: In-Process State for Production

**What people do:** Keep `_AGENT_STATE` as a module-level dict in `router.py`.

**Why it's wrong:** Process restarts (deploys, crashes, OOM) silently wipe all mid-conversation state. On restart, the patient's next message goes back to `boas_vindas`. If the service ever needs two processes, state is split.

**Do this instead:** Serialize FSM agent state to Redis with a 24h TTL. The agent classes need `to_dict()/from_dict()`. All other code stays the same.

---

## Scaling Considerations

This system serves a single nutritionist. Scale targets are modest:

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Current (~10 concurrent patients) | In-process dict state is fine for testing; Playwright workers run sequentially |
| Production (< 200 concurrent) | Redis state required; Playwright workers need thread pool limit (already `ThreadPoolExecutor`); Rede worker replaced with REST API |
| Growth (200-1000 concurrent) | Dietbox token refresh may bottleneck — add distributed cache; separate APScheduler to its own process; add DB connection pool |
| Never needed | Microservices split, message queues between agents — this is a single-tenant single-nutritionist system |

**First bottleneck:** The Rede Playwright worker (~180s, blocks thread) will fail under concurrent payment requests before anything else. The REST API migration eliminates this entirely.

**Second bottleneck:** In-process `_AGENT_STATE` dict on process restart. Redis migration (planned) eliminates this.

---

## Sources

- Rasa: "How LLM Chatbot Architecture Works" — [https://rasa.com/blog/llm-chatbot-architecture](https://rasa.com/blog/llm-chatbot-architecture)
- Google ADK: "Architecting efficient context-aware multi-agent framework for production" — [https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)
- OpenAI Agents SDK — Multi-agent patterns: [https://openai.github.io/openai-agents-python/multi_agent/](https://openai.github.io/openai-agents-python/multi_agent/)
- Anthropic: "Effective context engineering for AI agents" — [https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- FSM + LLM framework pattern: [https://github.com/jsz-05/LLM-State-Machine](https://github.com/jsz-05/LLM-State-Machine)
- LangGraph WhatsApp integration: [https://www.infobip.com/docs/tutorials/integrate-genai-into-whatsapp-chatbot-with-langgraph-ai-agent](https://www.infobip.com/docs/tutorials/integrate-genai-into-whatsapp-chatbot-with-langgraph-ai-agent)
- Aisera hybrid ICM + LLM conversation design: [https://docs.aisera.com/aisera-platform/crafting-the-conversation/conversation-design-icm-llm-and-hybrid](https://docs.aisera.com/aisera-platform/crafting-the-conversation/conversation-design-icm-llm-and-hybrid)
- Current codebase: `app/router.py`, `app/agents/atendimento.py`, `app/agents/orchestrator.py`

---

*Architecture research for: multi-agent WhatsApp scheduling assistant (Agente Ana)*
*Researched: 2026-04-07*
