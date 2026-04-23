---
phase: 04-meta-cloud-api
plan: "01"
subsystem: webhook
tags: [redis, dedup, meta-api, webhook, tdd]
dependency_graph:
  requires: []
  provides: [redis-dedup-atomica, meta-api-client-sem-args]
  affects: [app/webhook.py, app/meta_api.py]
tech_stack:
  added: [redis.asyncio]
  patterns: [Redis SET NX atomico, graceful degradation, args opcionais com env fallback]
key_files:
  created: []
  modified:
    - app/webhook.py
    - app/meta_api.py
    - tests/test_webhook.py
    - tests/test_meta_api.py
decisions:
  - "Dedup Redis como camada primaria; dedup DB mantida como camada secundaria (nao removida)"
  - "Graceful degradation: Redis down retorna False (fail open) para nao bloquear webhook"
  - "MetaAPIClient args opcionais com fallback env vars mantem retrocompatibilidade total"
metrics:
  duration: ~15 min
  completed_date: "2026-04-15"
  tasks_completed: 3
  files_modified: 4
---

# Phase 04 Plan 01: Redis Dedup Atomica + MetaAPIClient Fix Summary

**One-liner:** Redis SET NX atomico com TTL 4h elimina race condition de dedup no webhook; MetaAPIClient corrigido para aceitar chamada sem argumentos lendo env vars.

## Objective

Implementar deduplicacao atomica de mensagens via Redis SET NX e corrigir bug de instanciacao do MetaAPIClient (GAP-1 e GAP-3 identificados na pesquisa da Fase 4).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Testes RED: dedup Redis + MetaAPIClient sem args | dda1148 | tests/test_webhook.py, tests/test_meta_api.py |
| 2 | Redis dedup atomica em webhook.py | c74ab15 | app/webhook.py, tests/test_webhook.py |
| 3 | Fix MetaAPIClient.__init__ para args opcionais | 19dc988 | app/meta_api.py |

## What Was Built

### Redis Dedup Atomica (app/webhook.py)

Funcao `_is_duplicate_message(meta_message_id)` adicionada antes do bloco `SessionLocal`:

- Cria chave `dedup:msg:{meta_message_id}` no Redis com `SET NX EX 14400` (4 horas)
- Retorna `True` se chave ja existia (duplicata) — operacao atomica, sem race condition
- Retorna `False` em qualquer falha Redis (graceful degradation, fail open)
- `process_message()` retorna imediatamente se `_is_duplicate_message` retorna True
- Dedup por DB existente (`filter_by meta_message_id`) mantida como segunda camada

### MetaAPIClient Args Opcionais (app/meta_api.py)

`MetaAPIClient.__init__` modificado:

- `phone_number_id` e `access_token` agora sao `str | None = None`
- Fallback: le `WHATSAPP_PHONE_NUMBER_ID` e `WHATSAPP_TOKEN` do ambiente
- Retrocompativel: args explicitos tem precedencia (existentes em `webhook.py` funcionam)
- Corrige `TypeError` em producao quando `router.py` chama `MetaAPIClient()` sem args

## Test Coverage

- **test_dedup_redis_blocks_duplicate**: `_is_duplicate_message` retorna True → `route_message` nao chamado
- **test_dedup_redis_allows_first**: `_is_duplicate_message` retorna False → `route_message` chamado
- **test_dedup_graceful_degradation**: Redis lanca excecao → `_is_duplicate_message` retorna False (fail open)
- **test_client_no_args_reads_env**: `MetaAPIClient()` sem args le env vars corretamente

**Full suite result:** 235 testes passando (0 failures)

## Verification

```
grep "import redis.asyncio as aioredis" app/webhook.py   # OK
grep "_DEDUP_TTL = 14400" app/webhook.py                # OK
grep "dedup:msg:" app/webhook.py                        # OK
grep "_is_duplicate_message" app/webhook.py             # 2 matches (definicao + chamada)
grep "phone_number_id: str | None = None" app/meta_api.py  # OK
grep "access_token: str | None = None" app/meta_api.py     # OK
grep 'os.environ.get("WHATSAPP_PHONE_NUMBER_ID"' app/meta_api.py  # OK
grep 'os.environ.get("WHATSAPP_TOKEN"' app/meta_api.py            # OK
python -m pytest tests/ -q  → 235 passed
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Testes de graceful degradation e test_dedup_redis_allows_first ajustados**

- **Found during:** Task 1 (RED phase) + Task 2 (GREEN phase)
- **Issue:** Testes tentavam patchar `app.webhook.route_message` e `app.webhook.SessionLocal`, mas esses sao importados localmente dentro da funcao `process_message()` (padrao do projeto para evitar circular imports). Patches nao funcionavam.
- **Fix:** `test_dedup_redis_blocks_duplicate` ajustado para patchar `app.router.route_message`. `test_dedup_graceful_degradation` refatorado para testar `_is_duplicate_message` diretamente (mockando `aioredis` em vez de `process_message`), que e o ponto correto para testar graceful degradation (comportamento interno da funcao).
- **Files modified:** tests/test_webhook.py
- **Commit:** c74ab15

## Known Stubs

Nenhum. Implementacao completa e funcional — sem placeholders ou dados hardcoded.

## Threat Surface

Ameacas do threat model cobertas:

| Threat ID | Status | Mitigation |
|-----------|--------|------------|
| T-04-01 | Mitigado | Redis SET NX atomico com key `dedup:msg:{id}`, TTL 14400s |
| T-04-02 | Mitigado | Graceful degradation: fail open quando Redis indisponivel |
| T-04-04 | Mitigado | Env vars lidas no `__init__`, nunca logadas |

## Self-Check: PASSED

- [x] app/webhook.py existe e contem `_is_duplicate_message`, `dedup:msg:`, `_DEDUP_TTL`
- [x] app/meta_api.py existe e contem args opcionais + env var fallback
- [x] tests/test_webhook.py contem 3 novos testes de dedup
- [x] tests/test_meta_api.py contem `test_client_no_args_reads_env`
- [x] Commits dda1148, c74ab15, 19dc988 existem
- [x] 235 testes passando no full suite
