---
phase: 02-fluxo-de-remarca-o
plan: "03"
subsystem: retention-agent
tags: [dietbox, remarcacao, fsm, tdd, dietbox-first, write-before-confirm]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [alterar_agendamento, aguardando_confirmacao_dietbox, erro_remarcacao, MSG_ERRO_REMARCACAO_DIETBOX]
  affects: [app/agents/dietbox_worker.py, app/agents/retencao.py, tests/test_dietbox_worker.py, tests/test_retencao.py, tests/test_integration.py]
tech_stack:
  added: []
  patterns: [TDD RED-GREEN, Dietbox-write-before-confirm, FSM error state, observation per D-23]
key_files:
  created: []
  modified:
    - app/agents/dietbox_worker.py
    - app/agents/retencao.py
    - tests/test_dietbox_worker.py
    - tests/test_retencao.py
    - tests/test_integration.py
decisions:
  - alterar_agendamento uses requests.patch with timeout=20 and try/except — same pattern as existing Dietbox functions; returns bool, never propagates exception
  - aguardando_confirmacao_dietbox etapa handles both success (concluido) and failure (erro_remarcacao) — no false confirmation possible
  - T-02-03-01 mitigated: id_agenda_original=None triggers alterar_agendamento("", ...) which returns False → erro_remarcacao (no special-case needed, consistent path)
  - Observation built from consulta_atual.inicio field; gracefully degrades to "Remarcado para {data}" if original date unavailable
metrics:
  duration: ~10 min
  completed: 2026-04-13
  tasks_completed: 2
  files_modified: 5
---

# Phase 02 Plan 03: Sequência Dietbox-first — Write Before Confirm Summary

`alterar_agendamento()` PATCH no Dietbox antes de enviar qualquer confirmação ao paciente: slot escolhido → espera → Dietbox alterado → confirmação (ou erro informativo se falhar).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | alterar_agendamento() em dietbox_worker.py — PATCH com nova data e observação | 2c074d1 | app/agents/dietbox_worker.py, tests/test_dietbox_worker.py |
| 2 | Sequência Dietbox-first em retencao.py — etapa aguardando_confirmacao_dietbox | b684681 | app/agents/retencao.py, tests/test_retencao.py, tests/test_integration.py |

## What Was Built

**Task 1 — alterar_agendamento():**
- `alterar_agendamento(id_agenda, novo_dt_inicio, observacao, duracao_minutos=60)` em `dietbox_worker.py`, após `agendar_consulta()`
- PATCH para `DIETBOX_API/agenda/{id_agenda}` com payload `{"Start", "End", "Observacao"}`
- Adiciona timezone BRT se `novo_dt_inicio` for naive
- `try/except` completo: retorna `False` em qualquer falha (HTTPError, Timeout, etc), nunca propaga
- 5 testes TDD: sucesso→True, HTTPError→False, Timeout→False, payload keys corretas, URL correta

**Task 2 — Sequência Dietbox-first:**
- Adicionado `alterar_agendamento` ao import de `dietbox_worker` em `retencao.py`
- Novas constantes: `MSG_ERRO_REMARCACAO_DIETBOX` (primeiro erro) e `MSG_ERRO_REMARCACAO_RETRY` (mensagem subsequente)
- `oferecendo_slots` corrigido: salva `self.novo_slot = slot`, muda etapa para `aguardando_confirmacao_dietbox`, retorna `["Um instante, por favor 💚"]` — sem chamar Dietbox ainda
- Nova etapa `aguardando_confirmacao_dietbox`:
  - Valida `self.novo_slot` presente (estado inconsistente → `erro_remarcacao`)
  - Monta observação per D-23: `"Remarcado do dia {data_original} para {data_nova}"` com fallback se `consulta_atual` ausente
  - Chama `alterar_agendamento(id_agenda, novo_dt, observacao)`
  - Sucesso → `etapa = "concluido"`, retorna `MSG_CONFIRMACAO_REMARCACAO` com data/hora/modalidade reais
  - Falha → `etapa = "erro_remarcacao"`, retorna `MSG_ERRO_REMARCACAO_DIETBOX` (zero confirmação falsa — per D-21)
- Nova etapa `erro_remarcacao`: qualquer mensagem → retorna `MSG_ERRO_REMARCACAO_RETRY`
- 6 testes TDD novos em `tests/test_retencao.py`

## Test Results

- `tests/test_dietbox_worker.py`: 23 passed (18 existentes + 5 novos)
- `tests/test_retencao.py`: 31 passed (25 existentes + 6 novos)
- Suite completa: 154 passed, 0 failed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_integration.py assertava MSG_CONFIRMACAO_REMARCACAO após escolha de slot**
- **Found during:** Task 2, verificação de regressões
- **Issue:** `test_fluxo_remarcacao_completo` assertava `"remarcada" in texto3.lower()` após escolher slot — comportamento correto do plan 02-02 como stub, mas incorreto após a implementação real do plan 02-03 (retorna "Um instante, por favor 💚" agora).
- **Fix:** Atualizado o teste para adicionar `patch("app.agents.retencao.alterar_agendamento", return_value=True)` e assertar `"instante" in texto3.lower() or "💚" in texto3` — reflete o comportamento correto com Dietbox-first.
- **Files modified:** `tests/test_integration.py`
- **Commit:** b684681

## Known Stubs

Nenhum. A sequência completa está implementada: slot escolhido → indicador de espera → Dietbox PATCH → confirmação real (ou erro informativo).

## Threat Flags

Nenhuma superfície nova além do que o threat_model do plano já cobria (T-02-03-01 a T-02-03-05).

- T-02-03-01 (id_agenda vazio/None): mitigado — `id_agenda_original or ""` passa string vazia para `alterar_agendamento`, que retorna `False` → `erro_remarcacao` (sem chamar Dietbox com dados inválidos)
- T-02-03-02 (Timeout): mitigado — `timeout=20` + `try/except` retorna `False` imediatamente
- T-02-03-03, T-02-03-04, T-02-03-05: aceitos conforme plano

## Self-Check: PASSED

- app/agents/dietbox_worker.py: FOUND
- app/agents/retencao.py: FOUND
- tests/test_dietbox_worker.py: FOUND
- tests/test_retencao.py: FOUND
- tests/test_integration.py: FOUND
- Commit 2c074d1: FOUND
- Commit b684681: FOUND
- 154 tests passing: CONFIRMED
