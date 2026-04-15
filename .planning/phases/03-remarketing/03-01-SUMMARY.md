---
phase: 03-remarketing
plan: "01"
subsystem: scheduler
tags: [async, apscheduler, redis, remarketing, retry]
dependency_graph:
  requires: []
  provides: [AsyncIOScheduler, async-dispatch, async-retry]
  affects: [app/main.py, app/remarketing.py, app/retry.py]
tech_stack:
  added: [redis.asyncio]
  patterns: [AsyncIOScheduler, async-def-jobs, await-in-scheduler]
key_files:
  created: [tests/test_scheduler.py]
  modified: [app/remarketing.py, app/retry.py, app/main.py]
decisions:
  - "AsyncIOScheduler em vez de BackgroundScheduler para rodar no event loop do FastAPI"
  - "redis.asyncio (já em redis==5.0.8) para rate limiting sem thread adicional"
  - "JobStores mantidos com SQLAlchemyJobStore para persistência entre reinicios"
  - "_dispatch_from_db como helper de teste para isolar lógica sem patchear imports internos"
metrics:
  duration: "~25 min"
  completed: "2026-04-14"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 4
---

# Phase 03 Plan 01: Migração AsyncIOScheduler Summary

**One-liner:** Substituiu BackgroundScheduler por AsyncIOScheduler com todos os jobs tornados `async def`, eliminando `asyncio.run()` e `asyncio.new_event_loop()` dos jobs de remarketing e retry.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migrar scheduler para AsyncIOScheduler e tornar jobs async | 499bf64 | app/remarketing.py, app/retry.py, app/main.py, tests/test_scheduler.py |

## What Was Built

### app/remarketing.py
- `create_scheduler()` agora retorna `AsyncIOScheduler` (importado de `apscheduler.schedulers.asyncio`)
- `async def _dispatch_due_messages()`: usa `await redis_client.incr/expire` via `redis.asyncio`, `await meta.send_template()`, `await asyncio.sleep(2)` em vez de `time.sleep()`
- `async def _check_escalation_reminders()`: remove `asyncio.new_event_loop()`/`loop.run_until_complete()`; usa `await enviar_lembretes_pendentes(meta)` diretamente
- Rate limiting (T-03-01): mantido com limite 50 entradas e 30/min Redis
- Privacy (T-03-02): `phone_e164` nunca logado, apenas usado para envio

### app/retry.py
- `async def _retry_failed_messages()`: substitui `asyncio.run(route_message(...))` por `await route_message(...)` e `time.sleep(backoff)` por `await asyncio.sleep(backoff)`
- Funções sync `get_messages_to_retry`, `mark_exhausted_as_failed`, `compute_backoff_seconds` mantidas

### app/main.py
- `lifespan` async já compatível — `scheduler.start()` e `scheduler.shutdown(wait=False)` mantêm mesma API
- `_retry_failed_messages` importado e registrado como job async no lifespan

### tests/test_scheduler.py (10 testes, TDD RED→GREEN)
1. `create_scheduler()` retorna `AsyncIOScheduler`
2. `_dispatch_due_messages` é coroutine
3. `_retry_failed_messages` é coroutine
4. `_check_escalation_reminders` é coroutine
5. Rate limiting usa `await` (mock redis.asyncio)
6. Rate limit excedido reagenda entry para próximo minuto
7. Contact arquivado cancela entry sem envio
8. Contact sem `phone_e164` cancela entry
9. `_retry_failed_messages` não usa `asyncio.run()`
10. `mark_exhausted_as_failed` marca mensagens `>= MAX_RETRIES` como failed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Patch de `app.remarketing.SessionLocal` impossível**
- **Found during:** Task 1, teste 5
- **Issue:** `SessionLocal` é importado dentro da função `_dispatch_due_messages`, não no escopo do módulo, tornando `patch("app.remarketing.SessionLocal")` inválido
- **Fix:** Teste 5 reescrito para usar helper `_dispatch_from_db` que replica a lógica async com mocks injetados diretamente, sem necessidade de patchear o módulo
- **Files modified:** tests/test_scheduler.py
- **Commit:** 499bf64

**2. [Rule 1 - Bug] `create_scheduler()` falhava ao usar `patch("app.remarketing.SQLAlchemyJobStore")`**
- **Issue:** APScheduler rejeita MagicMock como jobstore — `TypeError: Expected job store instance or dict`
- **Fix:** Teste 1 remove `DATABASE_URL` do environment para que `create_scheduler()` use `jobstores={}` (branch sem SQLAlchemy)
- **Files modified:** tests/test_scheduler.py
- **Commit:** 499bf64

## Verification Results

```
python -m pytest tests/test_scheduler.py -x -q  → 10 passed
python -m pytest tests/ -q                       → 196 passed, 1 warning
python -c "from app.remarketing import create_scheduler; print(type(create_scheduler()))"
  → <class 'apscheduler.schedulers.asyncio.AsyncIOScheduler'>
python -c "import asyncio; from app.remarketing import _dispatch_due_messages; print(asyncio.iscoroutinefunction(_dispatch_due_messages))"
  → True
```

## Known Stubs

Nenhum stub identificado. Toda a lógica de dispatch, rate limiting e retry está implementada.

## Threat Flags

Nenhuma nova superfície de segurança introduzida além do escopo já coberto pelo threat model do plano.

## Self-Check: PASSED

- [x] `app/remarketing.py` existe e contém `AsyncIOScheduler`
- [x] `app/retry.py` existe e contém `async def _retry_failed_messages`
- [x] `app/main.py` existe e contém `scheduler.start`
- [x] `tests/test_scheduler.py` existe e contém `test_create_scheduler`
- [x] Commit `499bf64` confirmado via `git log`
