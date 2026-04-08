# Feature Research

**Domain:** WhatsApp AI scheduling agent for a nutritionist (single-practitioner health clinic)
**Researched:** 2026-04-07
**Confidence:** HIGH (primary sources: existing codebase + verified industry patterns)

---

## Context: Where This Project Stands

The agent "Ana" already has a working implementation of the core booking flow (Phases 1-3 complete,
104 tests passing). This research maps the feature landscape for the **next milestone**: improving
intelligence and adding features to an already-functional agent.

Features marked "(EXISTS)" are already implemented. The focus is on what should be improved, added, or
deliberately not built.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features patients assume exist. Missing = agent feels broken or untrustworthy.

| Feature | Why Expected | Complexity | Status | Notes |
|---------|--------------|------------|--------|-------|
| Natural language intent detection | Patients send free-form messages; rigid keyword matching fails ("queria remarcar" vs "preciso mudar minha consulta") | MEDIUM | EXISTS (broken) | Orchestrator routes by intent but context switching fails mid-flow |
| Multi-turn context retention | A patient saying "prefiro sexta" mid-scheduling must be understood as a slot preference, not a new topic | MEDIUM | EXISTS (broken) | History is stored but not used intelligently by FSM dispatcher |
| Graceful out-of-flow responses | Patient asks "qual o endereço?" during the payment step — must answer without resetting the flow | HIGH | MISSING | Current FSM ignores off-topic questions or falls through to LLM fallback poorly |
| 3-option slot presentation | Industry standard: offer 3 time slots max to avoid decision paralysis | LOW | EXISTS | Implemented; needs preference-aware ordering |
| Appointment confirmation with details | Date, time, modality, location/link, prep instructions sent upon booking | LOW | EXISTS | Implemented in `_etapa_confirmacao` |
| 24h pre-appointment reminder | Automated message day before; reduces no-shows 30-38% (industry proven) | LOW | EXISTS | `MSG_LEMBRETE_24H` exists; APScheduler configured but trigger untested |
| Rescheduling flow | Patients will miss appointments; must rebook within policy window | MEDIUM | EXISTS (broken) | Logic exists in `AgenteRetencao` but 7-day window rules are wrong |
| Cancellation flow | Must acknowledge request, apply policy, confirm | LOW | EXISTS | Partially implemented; no Dietbox cancellation call |
| Payment information on demand | Patients ask about PIX/card mid-conversation; must answer without breaking flow | LOW | EXISTS | Available via LLM fallback + `FAQ_ESTATICO` |
| Waiting/processing indicator | "Um instante..." before long operations (Dietbox query ~3-5s, Rede ~180s) | LOW | MISSING | Identified in PROJECT.md as a required fix |
| Human escalation path | When bot cannot resolve, route to real person without losing context | MEDIUM | PARTIAL | Escalation to internal number exists conceptually; "send to 31 99205-9211 and relay" not implemented |
| FAQ answering | Prices, location, hours, cancellation policy — basic questions must be answered instantly | LOW | EXISTS | `FAQ_ESTATICO` + `faq_minerado` in knowledge base |
| Graceful "I don't know" | Bot must not make up clinical or pricing information | LOW | PARTIAL | LLM fallback exists; hallucination guard not explicit |

### Differentiators (Competitive Advantage)

Features that set Ana apart from a generic scheduling system or a simple "click a link" booking form.

| Feature | Value Proposition | Complexity | Status | Notes |
|---------|-------------------|------------|--------|-------|
| Preference-aware slot ordering | Offer slots closest to patient's stated preference first (day, time), with fallback to "next available" | MEDIUM | MISSING | PROJECT.md Priority 1; differentiates from random slot lists |
| Contextual upsell (one-shot) | At plan selection stage, suggest one upgrade naturally ("the Ouro plan is only R$X more and includes...") | LOW | EXISTS | Implemented; needs tone-polishing |
| Distinct return vs. new consultation handling | Return patients get 7-day rescheduling window; new patients have no restriction. Bot must distinguish | MEDIUM | EXISTS (broken) | Business rule exists in code but applied incorrectly |
| Objection handling via LLM | Patient says "tá caro" or "preciso pensar" — bot acknowledges empathetically and asks what's blocking | MEDIUM | PARTIAL | `objections.json` in knowledge base; not wired into FSM checkpoints |
| Proactive lead re-engagement (drip) | 24h / 7d / 30d follow-up sequence for leads who went cold; max 3 attempts | MEDIUM | EXISTS (untested) | `AgenteRetencao.REMARKETING_SEQ` defined; APScheduler not validated end-to-end |
| Inline FAQ during active flow | Answer incidental questions ("aceita plano de saude?") mid-booking and resume flow at same step | HIGH | MISSING | Most impactful intelligence improvement; requires intent-over-state routing |
| Prep material delivery at confirmation | Send PDF guides and preparation images automatically based on modality (online vs presencial) | LOW | EXISTS | Implemented in `_etapa_confirmacao`; references placeholders not actual sends |
| Family discount detection | "Quero agendar para mim e minha filha" → 10% discount applied, sequential slots offered | MEDIUM | MISSING | Listed in `FAQ_ESTATICO` but not wired into booking flow |
| Payment receipt acknowledgment | When patient sends comprovante, bot confirms receipt and proceeds without requiring explicit "fiz o pix" | LOW | PARTIAL | Heuristic: `len(msg) > 30` counts as comprovante; needs improvement |
| Post-booking satisfaction check | 24h after appointment, brief "how did it go?" message opens door for renewal | MEDIUM | MISSING | Not in current scope; high value for retention |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem valuable but create problems in this specific context.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Nutritional advice via chat | Patients will ask "posso comer X?" or "qual a dieta pra emagrecer?" | Out of scope for Ana's role (she is a scheduler, not a nutritionist); clinical advice via WhatsApp is legally and ethically risky in Brazil; creates liability | Hard stop: "Não tenho formação para orientar sobre nutrição — essa é uma conversa importante pra ter diretamente com a Thaynara na consulta 💚" |
| Full cancellation/refund automation | Patients request refund via bot | Chargeback policies require human judgment; automating refunds creates fraud surface | Escalate to human; bot confirms cancellation only, never refund decision |
| Persistent conversation history across years | "Lembra quando eu agendei em 2024?" | Storage cost, LGPD compliance risk, stale data leading to wrong decisions | Keep 30-day rolling window; summarize older sessions into a compact patient profile |
| Multi-practitioner / multi-clinic support | "Você também agenda com outra nutricionista?" | Project is exclusively for Thaynara; adding complexity fractures the knowledge base and voice | Keep single-tenant design; revisit only if explicitly requested |
| Proactive Formulario plan offer | "Offer cheaper plan to price-sensitive patients" | Thaynara explicitly does not want this done proactively; undermines her premium positioning | Confirm only when patient explicitly asks |
| WhatsApp payment (native Meta Pay) | Direct Pix inside WhatsApp conversation | Meta's native WhatsApp Pay in Brazil has friction (bank linking, recipient registration); less proven than PIX key + comprovante photo workflow | Keep PIX key + comprovante + card link; revisit if Meta Pay penetration grows |
| Sending body measurement files automatically | Bot proactively sends PDF guides without request | Creates message noise; patients receive guides they haven't asked for | Send only at confirmed booking (already implemented) |
| Rich menus / interactive buttons | WhatsApp Business Interactive Messages look polished | Requires Meta Business API-level approval; template messages cost per message; limits free-form conversation | Text-only with numbered choices is simpler, already works, and maintains conversation feel |
| Appointment waitlist | "Notify me if a slot opens up" | Requires real-time Dietbox polling and push notifications; adds significant complexity for unknown frequency of cancellations | Tell patient to re-contact Ana; low-tech but sufficient for single-practitioner scale |

---

## Feature Dependencies

```
[Intent Detection (robust)]
    └──required by──> [Inline FAQ during active flow]
    └──required by──> [Contextual upsell tone]
    └──required by──> [Graceful out-of-flow responses]
    └──required by──> [Return vs. new patient distinction]

[Dietbox Worker (slot query)]
    └──required by──> [Preference-aware slot ordering]
    └──required by──> [Rescheduling workflow]

[Payment confirmation (PIX receipt)]
    └──required by──> [Dietbox booking]
    └──required by──> [Confirmation message delivery]

[APScheduler (background jobs)]
    └──required by──> [24h appointment reminder]
    └──required by──> [Drip re-engagement sequence]
    └──required by──> [Post-booking satisfaction check]

[Human escalation path]
    └──required by──> [Graceful "I don't know"]
    └──enhances──> [Objection handling]

[Rescheduling workflow (corrected)]
    └──depends on──> [Return vs. new patient distinction]
    └──depends on──> [Dietbox slot query]
```

### Dependency Notes

- **Intent detection requires improvement before inline FAQ**: The FSM dispatch model (`_despachar`) routes by current state, ignoring user intent. Inline FAQ during active flow requires intent-first routing: check intent before checking current FSM state, and only advance the FSM if intent matches the expected flow.
- **Preference-aware slots requires Dietbox integration remaining stable**: The slot query is functional (Playwright headless, via Dietbox Worker). Slot ordering is a pure post-processing improvement on top of the existing query; it does not require migrating the Dietbox integration first.
- **APScheduler drip triggers depend on correct database state**: Remarketing messages should only fire when a conversation has gone cold (no inbound message for N hours). This requires reliable conversation state timestamps in the database.
- **Return vs. new patient distinction conflicts with current FSM**: Currently, `status_paciente` is collected at step 1 but the rescheduling branch in `AgenteRetencao` doesn't reference it. The distinction must propagate through the session state and be checked at rescheduling entry.

---

## MVP Definition (for Next Milestone)

### Launch With — Intelligence Milestone (what makes Ana usable in production)

- [ ] **Inline FAQ during active flow** — Current behavior breaks the conversation (patient asks about address during payment, flow resets or gives wrong response); this is the single biggest friction point
- [ ] **Corrected rescheduling rules** — 7-day window, preference-aware ordering, graceful fallback when preference unavailable; required for basic patient trust
- [ ] **Return vs. new patient distinction** — Wrong business rules applied to remarcacao de retorno; creates real-world errors (patient loses retorno entitlement)
- [ ] **Waiting indicator before slow operations** — "Um instante, por favor 💚" before Dietbox/Rede calls; without this, patients think the bot crashed
- [ ] **Human escalation relay** — When Ana cannot answer, notify internal number and relay response; prevents dead-end conversations

### Add After Validation (v1.x)

- [ ] **APScheduler drip triggers validated end-to-end** — Trigger when: lead with `status=qualificado` has no inbound in 24h; max 3 attempts total
- [ ] **Payment receipt acknowledgment improvement** — Replace `len(msg) > 30` heuristic with: detect image attachment OR keywords, reduce false positives
- [ ] **Prep material delivery via actual WhatsApp sends** — Confirmacao messages currently log `[IMG: ...]` placeholders; wire to actual Meta API media sends

### Future Consideration (v2+)

- [ ] **Family discount flow** — Niche use case; implement after core reliability is proven
- [ ] **Post-booking satisfaction check** — High value for renewal conversion; defer until booking flow is stable
- [ ] **Objection handling checkpoints** — Wire `objections.json` into FSM checkpoints at plan presentation and payment stages; low risk but requires careful prompt engineering

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Inline FAQ during active flow | HIGH | HIGH | P1 |
| Corrected rescheduling rules (7d window + preference order) | HIGH | MEDIUM | P1 |
| Return vs. new patient distinction in remarcacao | HIGH | LOW | P1 |
| Waiting indicator before slow operations | MEDIUM | LOW | P1 |
| Human escalation relay (notify internal, relay answer) | HIGH | MEDIUM | P1 |
| APScheduler drip triggers end-to-end | MEDIUM | MEDIUM | P2 |
| Payment receipt acknowledgment improvement | MEDIUM | LOW | P2 |
| Actual media sends at confirmation (not placeholders) | MEDIUM | MEDIUM | P2 |
| Family discount detection and flow | LOW | MEDIUM | P3 |
| Post-booking satisfaction check | MEDIUM | LOW | P3 |
| Objection handling at FSM checkpoints | MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Must have for production launch (blocks real patients from using Ana)
- P2: Should have; add in the same milestone once P1 is stable
- P3: Nice to have; future milestone

---

## Competitor Feature Analysis

Context: Ana competes with (a) generic WhatsApp bots that just send a Calendly link, (b) Dietbox's own native scheduling, and (c) a receptionist/secretary taking calls.

| Feature | Generic WA Bot (Calendly link) | Dietbox native | Human receptionist | Ana (target) |
|---------|--------------------------------|-----------------|---------------------|--------------|
| Natural language booking | No (link redirect) | No (web form) | Yes | Yes |
| Plan presentation and upsell | No | No | Depends on person | Yes |
| PIX + card payment inline | No | No | Yes | Yes |
| Context switching mid-flow | No | No | Yes | Yes (target) |
| Rescheduling within policy | No | Manual | Yes | Yes (partial) |
| 24h reminder | Often (Calendly) | Yes | Depends | Yes (unvalidated) |
| Remarketing drip | No | No | No | Yes (unvalidated) |
| Objection handling | No | No | Yes | Partial |
| Human escalation | No | No | N/A | Partial |
| Available 24/7 | Yes | Yes | No | Yes |

Ana's defensible advantage: the combination of plan qualification + upsell + PIX + scheduling + remarketing in a single natural WhatsApp conversation — no link redirects, no form filling, no off-hours missed calls.

---

## Sources

- Existing codebase: `app/agents/atendimento.py`, `app/agents/retencao.py`, `app/knowledge_base.py` — HIGH confidence
- PROJECT.md active requirements — HIGH confidence (primary source)
- [WhatsApp Healthcare Automation: Transform Patient Engagement (BotMD)](https://www.botmd.io/blog/whatsapp-healthcare-automation-patient-engagement) — MEDIUM confidence
- [WhatsApp Chatbot for Healthcare (respond.io)](https://respond.io/blog/whatsapp-chatbot-for-healthcare) — MEDIUM confidence
- [WhatsApp Drip Campaigns: Complete Guide (Whautomate)](https://whautomate.com/the-ultimate-guide-to-whatsapp-drip-campaigns-in-2024/) — MEDIUM confidence
- [Chatbot to Human Handoff Guide (Spurnow)](https://www.spurnow.com/en/blogs/chatbot-to-human-handoff) — MEDIUM confidence
- [Chatbot Upsell & Cross-Sell (Quickchat AI)](https://quickchat.ai/post/chatbot-upsell-cross-sell-ai) — MEDIUM confidence
- [Brazil PIX + WhatsApp AI Payments (Bloomberg/Invezz)](https://invezz.com/news/2025/10/22/brazil-banks-turn-whatsapp-chats-into-instant-ai-powered-payments-with-pix/) — MEDIUM confidence
- [WhatsApp Bot Design: 5 Tips for Perfect UX (Landbot)](https://landbot.io/blog/design-whatsapp-bot-dialogue) — MEDIUM confidence
- [Conversational AI Session Management (Rasa)](https://rasa.com/blog/llm-chatbot-architecture) — MEDIUM confidence

---

*Feature research for: WhatsApp AI scheduling agent (Ana) for nutritionist Thaynara Teixeira*
*Researched: 2026-04-07*
