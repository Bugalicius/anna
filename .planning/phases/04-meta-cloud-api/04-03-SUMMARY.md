---
phase: 04-meta-cloud-api
plan: "03"
subsystem: pii-sanitizer
tags: [lgpd, pii, security, prompt-injection, tdd]
dependency_graph:
  requires: [04-01]
  provides: [pii-sanitization-lgpd]
  affects: [app/agents/atendimento.py]
tech_stack:
  added: []
  patterns: [regex-pii-masking, context-aware-disambiguation, tdd-red-green]
key_files:
  created:
    - app/pii_sanitizer.py
    - tests/test_pii_sanitizer.py
  modified:
    - app/agents/atendimento.py
decisions:
  - "CPF/phone disambiguation via context-aware ordering: phone with keyword context first, bare 11-digit defaults to CPF"
  - "Nome do paciente nao mascarado — necessario para personalizacao (T-04-11 accepted)"
  - "Aliases _CPF_RE/_PHONE_BR_RE mantidos para compatibilidade com plano"
metrics:
  duration: ~15min
  completed: "2026-04-15"
  tasks_completed: 2
  files_changed: 3
---

# Phase 04 Plan 03: PII Sanitizer (LGPD Compliance) Summary

**One-liner:** Sanitizacao LGPD de CPF, telefone e email via regex context-aware antes de chamadas Anthropic, com deteccao de prompt injection e 13 testes TDD.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Criar PII sanitizer + testes (TDD) | 18f4abc, 062b807 | app/pii_sanitizer.py, tests/test_pii_sanitizer.py |
| 2 | Integrar sanitize_historico em _gerar_resposta_llm | 3dd8333 | app/agents/atendimento.py |

## What Was Built

### app/pii_sanitizer.py
Modulo de sanitizacao de PII com:
- `sanitize_message(text)` — mascara CPF, telefone BR, email; detecta e trunca prompt injection
- `sanitize_historico(historico)` — retorna copia sanitizada do historico (apenas role=user); original preservado
- 6 regex compilados: `_CPF_FORMATTED_RE`, `_PHONE_FORMATTED_RE`, `_PHONE_CONTEXT_RE`, `_CPF_BARE_RE`, `_EMAIL_RE`, `_INJECTION_RE`
- Aliases `_CPF_RE` e `_PHONE_BR_RE` para compatibilidade

**Decisao de design:** CPF com pontuacao (123.456.789-09) e inequivoco. Telefone formatado (com espaco/parens) e inequivoco. Para 11 digitos sem separadores, contexto de palavra-chave ("numero", "celular", etc.) determina TELEFONE; sem contexto, default para CPF.

### app/agents/atendimento.py
`_gerar_resposta_llm` agora:
1. Aplica `sanitize_historico(historico[-10:])` antes de construir msgs para Anthropic
2. Historico original `self.historico` nao e mutado — FSM interno continua usando texto completo

## Verification

```
python -m pytest tests/test_pii_sanitizer.py -q  →  13 passed
python -m pytest tests/ -q                        →  252 passed, 1 warning
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CPF/phone regex ambiguity for unformatted 11-digit numbers**
- **Found during:** Task 1 GREEN phase
- **Issue:** `_PHONE_BR_RE = re.compile(r'\(?\b\d{2}\)?\s?\d{4,5}-?\d{4}\b')` from plan matched bare 11-digit numbers like `12345678909`, causing `test_sanitize_cpf_without_dots` and `test_sanitize_phone_without_parens` to conflict
- **Fix:** Split into separate patterns with context-aware ordering: (1) CPF formatted, (2) phone formatted, (3) phone with context keyword, (4) bare 11-digit → CPF by default
- **Files modified:** app/pii_sanitizer.py
- **Commits:** 18f4abc, 062b807

## Known Stubs

None — all patterns are fully implemented and tested.

## Threat Surface

No new network endpoints or trust boundaries introduced. This plan implements mitigations for threats T-04-09 and T-04-10 already listed in the plan's threat model.

## Self-Check: PASSED

- FOUND: app/pii_sanitizer.py
- FOUND: tests/test_pii_sanitizer.py
- FOUND: app/agents/atendimento.py (modified)
- FOUND: commit 18f4abc (feat: add PII sanitizer)
- FOUND: commit 3dd8333 (feat: integrate sanitize_historico)
- FOUND: commit 062b807 (fix: add aliases)
- 252 tests passing
