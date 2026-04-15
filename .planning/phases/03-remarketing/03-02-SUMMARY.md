---
phase: 03-remarketing
plan: "02"
subsystem: remarketing
tags: [remarketing, orchestrator, router, redis, lead_perdido, tdd]
dependency_graph:
  requires: [03-01-PLAN.md]
  provides: [sequencia-corrigida, recusou_remarketing, redis-active-check, lead_perdido-handler]
  affects: [app/remarketing.py, app/agents/orchestrator.py, app/router.py]
tech_stack:
  added: []
  patterns: [TDD-RED-GREEN, _dispatch_from_db-helper, intent-routing-remarketing_recusa]
key_files:
  created: [tests/test_remarketing.py]
  modified: [app/remarketing.py, app/agents/orchestrator.py, app/router.py]
decisions:
  - "REMARKETING_SEQUENCE corrigida para 3 entradas: 24h/168h/720h conforme D-01"
  - "MAX_REMARKETING=3 — era 5, agora alinhado com D-01"
  - "BEHAVIORAL_TEMPLATES e schedule_behavioral_remarketing removidos (deferido para backlog)"
  - "recusou_remarketing adicionado ao IntencaoType e rotear() -> remarketing_recusa"
  - "Handler no router envia MSG_ENCERRAMENTO_REMARKETING exata (D-09) + set_tag LEAD_PERDIDO"
  - "Redis check D-11: exists(agent_state:{phone_hash}) antes de disparar — skip sem cancelar"
  - "_dispatch_from_db helper extraido para permitir testes unitarios sem patching de imports"
  - "cancel_pending_remarketing movido para import top-level no router.py"
metrics:
  duration: "~30 min"
  completed: "2026-04-14"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
---

# Phase 03 Plan 02: Logica de Negocio do Remarketing Summary

**One-liner:** Corrigiu sequencia para 24h/7d/30d com MAX=3, adicionou intencao `recusou_remarketing` ao orquestrador com handler dedicado no router (farewell + lead_perdido + cancel queue) e verificacao de conversa ativa no Redis antes de disparar.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Corrigir sequencia/MAX + recusou_remarketing no orquestrador | d69160e | app/remarketing.py, app/agents/orchestrator.py, tests/test_remarketing.py |
| 2 | Handler recusou_remarketing no router + farewell message | d69160e | app/router.py |
| 3 | Verificacao de conversa ativa no Redis antes de disparar | d69160e | app/remarketing.py |

## What Was Built

### app/remarketing.py
- `REMARKETING_SEQUENCE` corrigida: 3 entradas com delays 24h, 168h, 720h e templates `ana_followup_24h`, `ana_followup_7d`, `ana_followup_30d`
- `MAX_REMARKETING = 3` (era 5)
- `BEHAVIORAL_TEMPLATES` dict removido completamente
- `schedule_behavioral_remarketing()` removido completamente
- `can_schedule_remarketing()`: novo check `contact.stage == "lead_perdido"` retorna False
- `_dispatch_due_messages()`: check Redis D-11 adicionado (exists agent_state: skip sem cancelar); `archived` → stage check inclui `lead_perdido`; ao atingir MAX, muda stage para `lead_perdido` em vez de `archived`
- `_dispatch_from_db()`: novo helper testavel com toda a logica de dispatch injetavel (mesmo padrao do Plan 03-01)

### app/agents/orchestrator.py
- `IntencaoType` Literal expandido com `"recusou_remarketing"`
- `_PROMPT_CLASSIFICACAO`: nova opcao documentada com exemplos de frases
- Validacao em `_classificar_intencao()`: `recusou_remarketing` adicionado ao set `validas`
- `rotear()`: branch dedicado para `recusou_remarketing` retornando `{"agente": "remarketing_recusa", ...}`

### app/router.py
- `cancel_pending_remarketing` movido para import top-level (era import local em `route_message`)
- `MSG_ENCERRAMENTO_REMARKETING` constante modulo com texto exato do D-09
- Handler `remarketing_recusa` adicionado antes do bloco `padrao`:
  - Envia `MSG_ENCERRAMENTO_REMARKETING`
  - `cancel_pending_remarketing(db, contact.id)`
  - `set_tag(db, contact, Tag.LEAD_PERDIDO, force=True)`
  - `_state_mgr.delete(phone_hash)` se state_mgr presente

### tests/test_remarketing.py
- Reescrito: manteve 5 testes originais validos, adicionou 20 novos testes
- Total: 25 testes cobrindo Tasks 1, 2 e 3

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] cancel_pending_remarketing era import local — impossivel de mockar**
- **Found during:** Task 2, testes do router
- **Issue:** `cancel_pending_remarketing` era importado dentro de `route_message()` com `from app.remarketing import cancel_pending_remarketing`, tornando `patch("app.router.cancel_pending_remarketing")` invalido
- **Fix:** Movido para import top-level no modulo `router.py`; import local removido
- **Files modified:** app/router.py
- **Commit:** d69160e

## Verification Results

```
python -m pytest tests/test_remarketing.py -x -q  -> 25 passed
python -m pytest tests/ -q                         -> 215 passed, 1 warning
python -c "from app.remarketing import MAX_REMARKETING, REMARKETING_SEQUENCE; assert MAX_REMARKETING == 3; assert len(REMARKETING_SEQUENCE) == 3"  -> OK
grep -r "BEHAVIORAL_TEMPLATES" app/               -> nenhum resultado
grep "recusou_remarketing" app/agents/orchestrator.py -> presente (3 ocorrencias)
```

## Known Stubs

Nenhum stub identificado. Toda a logica de negocio esta implementada e testada.

## Threat Flags

Nenhuma nova superficie de seguranca alem do escopo do threat model do plano.

## Self-Check: PASSED

- [x] `app/remarketing.py` — `MAX_REMARKETING = 3`, `REMARKETING_SEQUENCE` com 3 entradas, `_dispatch_from_db` presente
- [x] `app/agents/orchestrator.py` — `recusou_remarketing` no IntencaoType e em `rotear()`
- [x] `app/router.py` — `MSG_ENCERRAMENTO_REMARKETING` e handler `remarketing_recusa` presentes
- [x] `tests/test_remarketing.py` — 25 testes coletados e passando
- [x] Commit `d69160e` confirmado
