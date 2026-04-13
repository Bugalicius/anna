---
phase: 02-fluxo-de-remarca-o
plan: "02"
subsystem: retention-agent
tags: [remarcacao, priorizar-slots, negociacao, perda-retorno, tdd]
dependency_graph:
  requires: [02-01]
  provides: [_priorizar_slots, MSG_PERDA_RETORNO, MSG_SEGUNDA_RODADA, rodada_negociacao-flow, perda_retorno-etapa]
  affects: [app/agents/retencao.py, tests/test_retencao.py, tests/test_integration.py]
tech_stack:
  added: []
  patterns: [TDD RED-GREEN, FSM 2-round negotiation, slot prioritization algorithm]
key_files:
  created: []
  modified:
    - app/agents/retencao.py
    - tests/test_retencao.py
    - tests/test_integration.py
decisions:
  - _priorizar_slots recebe pool completo + preferências; lógica de aviso (dia não disponível) permanece na etapa coletando_preferencia — separação de responsabilidades
  - Etapa após escolha de slot é 'aguardando_confirmacao_dietbox' não 'concluido' — Plan 02-03 implementará a efetivação no Dietbox
  - next_batch calculado por diferença de datetime strings (set de datetimes) — confiável desde que pool seja deserializado corretamente do Redis
metrics:
  duration: ~8 min
  completed: 2026-04-13
  tasks_completed: 2
  files_modified: 3
---

# Phase 02 Plan 02: Algoritmo _priorizar_slots + 2 Rodadas de Negociação Summary

Implementação do algoritmo `_priorizar_slots()` (substituindo `_selecionar_slots_dias_diferentes()`), das constantes de mensagem `MSG_SEGUNDA_RODADA`/`MSG_PERDA_RETORNO`/`MSG_SEM_MAIS_SLOTS`, e do fluxo de 2 rodadas de negociação com fallback de perda de retorno na etapa `oferecendo_slots`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Algoritmo _priorizar_slots — preferência + dias diferentes | 78a379a | app/agents/retencao.py, tests/test_retencao.py |
| 2 | Fluxo de negociação — 2 rodadas + perda de retorno + mensagens fixas | 1b72da1 | app/agents/retencao.py, tests/test_retencao.py, tests/test_integration.py |

## What Was Built

**Task 1 — _priorizar_slots:**
- `_priorizar_slots(pool, dia_preferido, hora_preferida)` — substitui `_selecionar_slots_dias_diferentes()`
- Algoritmo: slot 1 = melhor match (dia+hora); slots 2-3 = próximos em dias diferentes do slot 1; sem preferência = 3 primeiros em dias diferentes; completa com mesmo dia se pool insuficiente
- Valida `"datetime"` em cada slot antes de usar (T-02-02-01)
- Etapa `coletando_preferencia` simplificada: aviso de dia-não-disponível gerado aqui, seleção delegada para `_priorizar_slots(todos_slots, dia_preferido, hora_preferida)` — código de pré-filtragem manual removido
- 7 testes TDD novos em `tests/test_retencao.py`

**Task 2 — Fluxo de negociação:**
- `MSG_SEGUNDA_RODADA` — segunda rodada (tom informal, emojis moderados)
- `MSG_PERDA_RETORNO` — perda de prazo após 2 rodadas
- `MSG_SEM_MAIS_SLOTS` — perda por pool esgotado (sem mais slots no next_batch)
- Etapa `oferecendo_slots` reestruturada: detecta rejeição via `_extrair_escolha_slot`, calcula `next_batch` (pool - oferecidos por datetime), aplica condição `rodada_negociacao >= 1 OR next_batch vazio` → perda imediata (T-02-02-02); caso contrário incrementa rodada e oferece segunda rodada
- Etapa `perda_retorno` adicionada: qualquer mensagem → `redirecionando_atendimento`
- Etapa após escolha vai para `aguardando_confirmacao_dietbox` (Plan 02-03 efetiva no Dietbox)
- 6 testes TDD novos em `tests/test_retencao.py`

## Test Results

- `tests/test_retencao.py`: 25 passed (9 existentes + 16 novos)
- `tests/test_integration.py`: atualizado com nova etapa `aguardando_confirmacao_dietbox`
- Suite completa: 143 passed, 0 failed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Etapa após escolha de slot era 'concluido' — test_integration esperava o antigo nome**
- **Found during:** Task 2, verificação de regressões
- **Issue:** O plan 02-02 mudou a etapa após escolha de slot para `aguardando_confirmacao_dietbox`, mas `test_fluxo_remarcacao_completo` ainda assertava `etapa == "concluido"`.
- **Fix:** Atualizado o assert para `aguardando_confirmacao_dietbox` com comentário explicando que Plan 02-03 implementará a confirmação Dietbox.
- **Files modified:** `tests/test_integration.py`
- **Commit:** 1b72da1

## Known Stubs

Nenhum. `aguardando_confirmacao_dietbox` é etapa intermediária intencional — Plan 02-03 implementará a efetivação no Dietbox a partir dessa etapa.

## Threat Flags

Nenhuma superfície nova além do que o threat_model do plano já cobria (T-02-02-01 a T-02-02-04).

## Self-Check: PASSED

- app/agents/retencao.py: FOUND
- tests/test_retencao.py: FOUND
- tests/test_integration.py: FOUND
- Commit 78a379a: FOUND
- Commit 1b72da1: FOUND
- 143 tests passing: CONFIRMED
