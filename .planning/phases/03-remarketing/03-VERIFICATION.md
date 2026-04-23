---
phase: 03-remarketing
verified: 2026-04-14T22:00:00Z
status: gaps_found
score: 3/5
overrides_applied: 0
gaps:
  - truth: "Lead sem resposta recebe follow-up automático em 24h, 7 dias e 30 dias — mensagens chegam de fato no WhatsApp"
    status: partial
    reason: "O scheduler job real (_dispatch_due_messages) chama meta.send_template() para todos os positions. A mensagem 24h deveria usar send_text (janela aberta), mas na prática usa send_template igual às demais. Se o template não estiver aprovado na Meta, a mensagem 24h também não é enviada — contradiz o comportamento de graceful degradation planejado."
    artifacts:
      - path: "app/remarketing.py"
        issue: "_dispatch_due_messages (linha 211-227) chama meta.send_template() diretamente para todos os positions. _enviar_remarketing() existe e implementa a lógica correta de send_text vs send_template, mas não é chamada por _dispatch_due_messages — apenas por _dispatch_from_db (helper de teste)."
    missing:
      - "_dispatch_due_messages deve delegar para _enviar_remarketing() em vez de chamar meta.send_template() diretamente"

  - truth: "Mensagens de follow-up seguem os templates da documentação (seção 6) — sem texto improvisado"
    status: partial
    reason: "As constantes MSG_FOLLOWUP_24H, MSG_FOLLOWUP_7D e MSG_FOLLOWUP_30D existem e contêm os textos exatos aprovados (D-02, D-03, D-04). Porém, _dispatch_due_messages não as utiliza — chama send_template com o nome do template, sem usar os textos das constantes. Os textos só seriam usados via _enviar_remarketing (position 1) que não é chamada pelo job real."
    artifacts:
      - path: "app/remarketing.py"
        issue: "_dispatch_due_messages passa entry.template_name para send_template (linha 214) mas nunca usa MSG_FOLLOWUP_* nem _MSG_POR_POSICAO. Os textos aprovados ficam sem efeito na execução real do scheduler."
    missing:
      - "_dispatch_due_messages deve chamar _enviar_remarketing() que já implementa os textos corretos por position"
---

# Phase 3: Remarketing — Verification Report

**Phase Goal:** Sistema de follow-up automático funciona de ponta a ponta — scheduler dispara nas janelas certas, templates corretos são enviados, controle de tentativas e lead perdido funcionam.
**Verified:** 2026-04-14T22:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Lead sem resposta recebe follow-up automático em 24h, 7 dias e 30 dias — mensagens chegam de fato no WhatsApp | PARTIAL | Scheduler existe, fila funciona, Redis check correto — mas o job real usa send_template diretamente para todas as posições, ignorando a lógica send_text/send_template de _enviar_remarketing. Mensagem 24h não usa send_text. |
| 2 | Sistema para de enviar após 3 tentativas sem resposta — não envia quarta mensagem | VERIFIED | MAX_REMARKETING = 3 (remarketing.py:31). can_schedule_remarketing bloqueia quando remarketing_count >= 3 (linha 102). _dispatch_from_db e _dispatch_due_messages movem contact.stage para "lead_perdido" ao atingir MAX (linhas 220-221 e 353-354). |
| 3 | Quando lead responde que não vai marcar, sistema move para "lead perdido" e nenhuma mensagem adicional é enviada | VERIFIED | recusou_remarketing no IntencaoType e no _PROMPT_CLASSIFICACAO. rotear() retorna agente="remarketing_recusa". Handler no router.py (linhas 181-195) envia farewell, chama cancel_pending_remarketing, set_tag(Tag.LEAD_PERDIDO, force=True) e deleta estado Redis. Testes 03-02 cobrem todos os caminhos. |
| 4 | Mensagens de follow-up seguem os templates da documentação (seção 6) — sem texto improvisado | PARTIAL | MSG_FOLLOWUP_24H/7D/30D existem com textos exatos (D-02/D-03/D-04). TEMPLATE_NAMES mapeado corretamente. Porém, _dispatch_due_messages (job real) não usa essas constantes nem chama _enviar_remarketing — usa send_template diretamente sem os textos. |
| 5 | Remarketing não interrompe paciente com conversa ativa — verifica estado FSM antes de disparar | VERIFIED | agent_state:{phone_hash} verificado via redis_client.exists() em ambos _dispatch_due_messages (linha 206) e _dispatch_from_db (linha 342). Entry não é cancelada, apenas pulada (continue). Testes test_dispatch_skip_quando_conversa_ativa e test_dispatch_nao_cancela_entry_quando_conversa_ativa verificam esse comportamento. |

**Score:** 3/5 truths verified (SCs 2, 3 e 5)

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/remarketing.py` | AsyncIOScheduler + async dispatch + sequência corrigida + MSG_FOLLOWUP_* + _enviar_remarketing | PARTIAL | Existe, substantivo, todos os elementos presentes. Gap: _dispatch_due_messages não usa _enviar_remarketing — os dois caminhos de execução (prod vs teste) têm comportamento divergente. |
| `app/agents/orchestrator.py` | Intenção recusou_remarketing | VERIFIED | recusou_remarketing em IntencaoType (linha 37), no prompt (linha 58), no set validas (linha 108), e em rotear() (linha 174). |
| `app/router.py` | Handler de recusou_remarketing | VERIFIED | MSG_ENCERRAMENTO_REMARKETING definida (linha 51-54). Handler completo em linhas 181-195. cancel_pending_remarketing no top-level import (linha 21). |
| `tests/test_remarketing.py` | Testes de lógica de negócio | VERIFIED | 25 testes. Cobre sequência, MAX, lead_perdido, recusou_remarketing no orquestrador e router, Redis active check. |
| `tests/test_remarketing_templates.py` | Testes de templates | VERIFIED | 16 testes. Cobre MSG_FOLLOWUP_*, TEMPLATE_NAMES, _enviar_remarketing por position, TEMPLATES_APPROVED flag. |
| `tests/test_scheduler.py` | Testes do scheduler async | VERIFIED | 10 testes. Cobre AsyncIOScheduler, coroutines, rate limiting, contact arquivado/sem phone, asyncio.run ausente. |
| `app/retry.py` | Async retry job | VERIFIED | async def _retry_failed_messages com await route_message e await asyncio.sleep. |
| `app/main.py` | Lifespan com scheduler async | VERIFIED | AsyncIOScheduler criado em create_scheduler(), job retry adicionado, scheduler.start() chamado. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `app/main.py` | `app/remarketing.py` | create_scheduler() | WIRED | lifespan importa e chama create_scheduler() (linha 26) |
| `app/remarketing.py` | `redis.asyncio` | aioredis client para rate limiting | WIRED | import redis.asyncio as aioredis (linha 17), aioredis.Redis.from_url() em _dispatch_due_messages |
| `app/remarketing.py` | `app/meta_api.py` | await meta.send_template/send_text | PARTIAL | _dispatch_due_messages chama await meta.send_template() diretamente (linha 212). _enviar_remarketing usa send_text para position 1 e send_template para 2/3 — mas não é chamada por _dispatch_due_messages. |
| `app/agents/orchestrator.py` | `app/router.py` | intencao recusou_remarketing roteada para handler | WIRED | rotear() retorna agente="remarketing_recusa"; router.py verifica agente_destino == "remarketing_recusa" (linha 181) |
| `app/router.py` | `app/remarketing.py` | cancel_pending_remarketing ao detectar recusou_remarketing | WIRED | import top-level (linha 21), chamada no handler (linha 188) |
| `app/remarketing.py` | `app/state_manager.py` | Verifica chave agent_state:{phone_hash} no Redis antes de disparar | WIRED | f"agent_state:{contact.phone_hash}" em _dispatch_due_messages (linha 205) e _dispatch_from_db (linha 341) |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `_dispatch_due_messages` | `due` (RemarketingQueue entries) | db.query(RemarketingQueue).filter(...pending...).limit(50) | Sim — query real ao banco | FLOWING |
| `_dispatch_due_messages` | send_template call | meta.send_template(to=contact.phone_e164, template_name=entry.template_name) | Sim — envia para Meta API | FLOWING (mas não usa send_text para 24h) |
| `_enviar_remarketing` | MSG_FOLLOWUP_24H | _MSG_POR_POSICAO[1] | Sim — constante definida | FLOWING mas UNREACHABLE via _dispatch_due_messages |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| MAX_REMARKETING = 3 | `python -c "from app.remarketing import MAX_REMARKETING; assert MAX_REMARKETING == 3; print('OK')"` | OK (verificado na leitura do arquivo) | PASS |
| Scheduler retorna AsyncIOScheduler | `create_scheduler()` retorna tipo correto | Verificado via código e summary 03-01 | PASS |
| _dispatch_due_messages é coroutine | `asyncio.iscoroutinefunction` | Verificado via código e tests/test_scheduler.py | PASS |
| recusou_remarketing no IntencaoType | Literal includes "recusou_remarketing" | Presente na linha 37 do orchestrator.py | PASS |
| _dispatch_due_messages usa _enviar_remarketing | Presença de chamada à função | AUSENTE — chama send_template diretamente (linha 212) | FAIL |
| MSG_FOLLOWUP_* usadas no dispatch | Texto enviado usa constantes aprovadas | AUSENTE no caminho real — apenas em _dispatch_from_db | FAIL |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RMKT-01 | 03-01, 03-02, 03-03 | Scheduler dispara follow-up automático | PARTIAL | Scheduler funciona, fila processa, mas caminho de envio 24h usa send_template em vez de send_text |
| RMKT-02 | 03-02 | MAX 3 tentativas | SATISFIED | MAX_REMARKETING = 3, can_schedule_remarketing verifica, stage muda para lead_perdido |
| RMKT-03 | 03-01, 03-02 | Controle de tentativas e fila | SATISFIED | cancel_pending_remarketing, set_tag LEAD_PERDIDO, Redis active check |
| RMKT-04 | 03-02 | recusou_remarketing detectado e tratado | SATISFIED | IntencaoType, rotear(), handler no router, testes 03-02 |
| RMKT-05 | 03-03 | Templates com texto correto | PARTIAL | Constantes existem com texto correto, mas _dispatch_due_messages não as utiliza |
| RMKT-06 | 03-02 | Não interrompe conversa ativa | SATISFIED | Redis check em ambos os caminhos de dispatch |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/remarketing.py` | 211-227 | `_dispatch_due_messages` usa `meta.send_template()` diretamente ignorando `_enviar_remarketing()` | Blocker | Todas as mensagens (inclusive 24h) usam send_template em vez de send_text. Textos aprovados em MSG_FOLLOWUP_* nunca chegam ao WhatsApp via scheduler. |
| `app/ai_engine.py` | 128, 168 | Importa e chama `schedule_behavioral_remarketing` que foi removida do módulo | Warning | Causaria AttributeError se `handle_ai()` fosse chamada — mas handle_ai não está wired no router ou webhook atuais, portanto não é caminho de execução ativo. |

---

## Human Verification Required

Nenhum item precisa de verificação humana — o gap é verificável programaticamente.

---

## Gaps Summary

### Gap 1: _dispatch_due_messages não usa _enviar_remarketing (BLOCKER)

Esta é a raiz das falhas nos SCs 1 e 4.

**O que existe:**
- `_enviar_remarketing()` implementa corretamente: position 1 → `send_text` com MSG_FOLLOWUP_24H; positions 2/3 → `send_template` com guarda TEMPLATES_APPROVED.
- `_dispatch_from_db()` (helper de teste) chama `_enviar_remarketing()` corretamente.
- Os testes de `test_remarketing_templates.py` e `test_remarketing.py` testam `_dispatch_from_db`, não `_dispatch_due_messages`.

**O que falta:**
- `_dispatch_due_messages` (o job real que o scheduler executa) tem sua própria implementação de envio usando `meta.send_template()` diretamente — nunca chama `_enviar_remarketing()`.
- Resultado: na produção, todas as mensagens de remarketing passam por `send_template` para qualquer position. A mensagem 24h não usa `send_text`. Os textos de `MSG_FOLLOWUP_*` nunca chegam ao paciente.

**Correção necessária:** Em `_dispatch_due_messages`, substituir o bloco `try: await meta.send_template(...)` por `success = await _enviar_remarketing(meta, contact.phone_e164, entry)` com a lógica de status correspondente — igual ao que já existe em `_dispatch_from_db`.

**Impacto no SC:** SC1 (mensagens chegam no WhatsApp) e SC4 (textos corretos) ficam comprometidos em produção, apesar de todos os 231 testes passarem. Os testes testam o helper de teste, não o job real.

---

### Informação adicional: ai_engine.py

`app/ai_engine.py` linha 128 importa `schedule_behavioral_remarketing` que foi removida do módulo `remarketing.py`. Isso causaria `ImportError` em runtime se `handle_ai()` fosse chamada, mas como `handle_ai` não está wired no router ou webhook atuais, não é um gap bloqueador desta fase.

---

_Verified: 2026-04-14T22:00:00Z_
_Verifier: Claude (gsd-verifier)_
