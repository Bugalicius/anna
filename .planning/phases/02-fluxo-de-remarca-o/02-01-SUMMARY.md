---
phase: 02-fluxo-de-remarca-o
plan: "01"
subsystem: retention-agent
tags: [dietbox, remarcacao, fsm, tdd, state-serialization]
dependency_graph:
  requires: [01-01]
  provides: [consultar_agendamento_ativo, verificar_lancamento_financeiro, calcular_fim_janela, AgenteRetencao-phase2-state]
  affects: [app/agents/retencao.py, app/agents/dietbox_worker.py]
tech_stack:
  added: []
  patterns: [TDD RED-GREEN, mock-patch isolation, FSM state expansion, backward-compatible deserialization]
key_files:
  created:
    - tests/test_retencao.py
  modified:
    - app/agents/dietbox_worker.py
    - app/agents/retencao.py
    - tests/test_dietbox_worker.py
    - tests/test_integration.py
decisions:
  - Mock target must match where function is imported, not where it is defined (app.agents.atendimento.* not app.agents.dietbox_worker.*)
  - _detectar_tipo_remarcacao calls real Dietbox functions — must be mocked at retencao module level in tests
  - calcular_fim_janela uses (7 - weekday) % 7 or 7 to always advance to NEXT week, never same week
metrics:
  duration: ~7 min
  completed: 2026-04-13
  tasks_completed: 2
  files_modified: 5
---

# Phase 02 Plan 01: Detecção Retorno vs Nova Consulta + Janela Correta Summary

Implementação de `consultar_agendamento_ativo` e `verificar_lancamento_financeiro` no Dietbox worker, expansão do `AgenteRetencao` com 5 novos campos de estado Phase 2, cálculo correto da janela de remarcação (sexta da semana seguinte ao agendamento original), e detecção automática do tipo de remarcação (retorno vs nova consulta).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Funções Dietbox — consultar_agendamento_ativo e verificar_lancamento_financeiro | 6f44fec | app/agents/dietbox_worker.py, tests/test_dietbox_worker.py |
| 2 | AgenteRetencao — expansão de estado, detecção retorno/nova consulta e janela correta | 7d01790 | app/agents/retencao.py, tests/test_retencao.py, tests/test_integration.py |

## What Was Built

**Task 1 — Funções Dietbox:**
- `consultar_agendamento_ativo(id_paciente)` — GET /agenda filtrado por paciente e período de 180 dias, retorna o próximo agendamento não-desmarcado ordenado por data, ou `None`; timeout=15, try/except nunca propaga exceção
- `verificar_lancamento_financeiro(id_agenda)` — GET /finance/transactions?IdAgenda=..., retorna `True` se houver qualquer lançamento, `False` se vazio ou erro
- 6 testes TDD (RED→GREEN) cobrindo lista vazia, desmarcada=True, exceção HTTP

**Task 2 — AgenteRetencao expandido:**
- `calcular_fim_janela(data_consulta)` — função module-level que retorna a sexta-feira da semana SEGUINTE à semana do agendamento (per D-05). Algoritmo: `dias_ate_prox_segunda = (7 - weekday) % 7 or 7` para garantir sempre semana seguinte
- 5 novos campos em `__init__`: `tipo_remarcacao`, `id_agenda_original`, `fim_janela`, `rodada_negociacao`, `_slots_pool`
- `to_dict` / `from_dict` expandidos com `.get(campo, default)` em todos os novos campos — compatível com estados Phase 1 serializados sem esses campos (mitigação T-02-01-01)
- `_detectar_tipo_remarcacao()` — distingue 3 casos: sem paciente → nova_consulta; com paciente sem lançamento → nova_consulta; com paciente e lançamento → retorno (salva id_agenda_original e fim_janela)
- `_fluxo_remarcacao` atualizado: chama `_detectar_tipo_remarcacao()` na etapa "inicio", redireciona para "redirecionando_atendimento" se nova_consulta; calcula janela correta usando `fim_janela` e `data_inicio=amanhã` (per D-06)
- 9 testes TDD novos em `tests/test_retencao.py`

## Test Results

- `tests/test_dietbox_worker.py`: 18 passed (12 existentes + 6 novos)
- `tests/test_retencao.py`: 9 passed (todos novos)
- Suite completa: 130 passed, 0 failed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Mock target errado em test_integration.py — test_fluxo_atendimento_pix_completo**
- **Found during:** Task 2, verificação de regressões
- **Issue:** `@patch("app.agents.dietbox_worker.consultar_slots_disponiveis")` não intercepta a função em `atendimento.py` quando o módulo já foi importado anteriormente (module-level import caching). O teste falhava no contexto da suite completa mas passava isolado.
- **Fix:** Alterado o mock path para `app.agents.atendimento.consultar_slots_disponiveis` (e `processar_agendamento` igualmente) — correto para módulos que fazem `from X import Y`.
- **Files modified:** `tests/test_integration.py`
- **Commit:** 7d01790

**2. [Rule 1 — Bug] Mocks ausentes para _detectar_tipo_remarcacao em testes de integração**
- **Found during:** Task 2, após implementar _detectar_tipo_remarcacao
- **Issue:** Os testes `test_fluxo_remarcacao_completo` e `test_remarcacao_sem_slots` não mockavam `buscar_paciente_por_telefone`, `consultar_agendamento_ativo` e `verificar_lancamento_financeiro`. Com o novo código, essas funções são chamadas no início do fluxo e tentam acessar DIETBOX_EMAIL (não configurado em testes).
- **Fix:** Adicionados os 3 mocks necessários em cada teste, ajustado o fluxo de 2 passos (inicio → coletando_preferencia → oferecendo_slots), corrigido mock path para `app.agents.retencao.*`.
- **Files modified:** `tests/test_integration.py`
- **Commit:** 7d01790

## Known Stubs

Nenhum. Todas as funções implementadas retornam valores reais (com mock em testes).

## Threat Flags

Nenhuma superfície nova além do que o threat_model do plano já cobria (T-02-01-01 a T-02-01-04).

## Self-Check: PASSED

- app/agents/dietbox_worker.py: FOUND
- app/agents/retencao.py: FOUND
- tests/test_retencao.py: FOUND
- Commit 6f44fec: FOUND
- Commit 7d01790: FOUND
- 130 tests passing: CONFIRMED
