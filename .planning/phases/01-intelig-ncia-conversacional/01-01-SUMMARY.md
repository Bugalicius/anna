---
phase: 01-intelig-ncia-conversacional
plan: "01"
subsystem: state-persistence
tags: [redis, state-manager, serialization, models, agent-fsm]
dependency_graph:
  requires: []
  provides:
    - app/state_manager.py: RedisStateManager async load/save/delete
    - app/agents/atendimento.py: AgenteAtendimento.to_dict/from_dict
    - app/agents/retencao.py: AgenteRetencao.to_dict/from_dict
    - app/models.py: Contact(first_name, last_name, dietbox_patient_id), PendingEscalation
  affects:
    - app/router.py: pode usar RedisStateManager em vez de _AGENT_STATE dict
    - Plan 03: PendingEscalation pronto para escalação relay
tech_stack:
  added:
    - redis.asyncio (já presente em requirements.txt como redis 5.0.8)
  patterns:
    - to_dict/from_dict para serialização de FSM de agente
    - Imports locais em RedisStateManager.load() para evitar circular imports
key_files:
  created:
    - app/state_manager.py
    - tests/test_state_manager.py
  modified:
    - app/agents/atendimento.py
    - app/agents/retencao.py
    - app/models.py
decisions:
  - "Sem TTL no Redis: estado de conversa persiste até fim do fluxo (D-12)"
  - "Redis failure retorna None sem crash: Ana pede info novamente (D-15)"
  - "historico limitado a 20 entradas em to_dict() para evitar exposição excessiva (T-01-01)"
  - "Sem Alembic migration: diretório alembic/ ausente; Contact/PendingEscalation criados via create_all fallback em app/main.py"
  - "AgenteRetencao ganhou 3 campos (motivo, consulta_atual, novo_slot) no __init__: eram usados no código mas não declarados"
metrics:
  duration: "~20 minutos"
  completed_date: "2026-04-09"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 3
---

# Phase 01 Plan 01: Redis State Persistence + Agent Serialization Summary

**One-liner:** Async Redis persistence layer with to_dict/from_dict agent serialization and expanded PostgreSQL Contact/PendingEscalation models.

## What Was Built

### app/state_manager.py (novo)

`RedisStateManager` com três operações assíncronas:
- `load(phone_hash)`: deserializa JSON do Redis para `AgenteAtendimento` ou `AgenteRetencao` baseado em `_tipo`; retorna `None` em falha sem crash
- `save(phone_hash, agent)`: serializa `agent.to_dict()` para JSON no Redis SEM TTL (D-12)
- `delete(phone_hash)`: remove chave ao finalizar fluxo

Todas as operações usam `try/except` com `logger.error` — falhas do Redis são logadas, não propagadas (D-15).

### Serialização nos agentes

`AgenteAtendimento.to_dict()` / `from_dict()`:
- Serializa 15 campos de estado + `_tipo: "atendimento"`
- `historico` limitado aos últimos 20 itens (mitigação T-01-01)

`AgenteRetencao.to_dict()` / `from_dict()`:
- Serializa 9 campos de estado + `_tipo: "retencao"`
- Também limitado a 20 entradas no historico

### app/models.py (expandido)

Três novas colunas em `Contact`:
- `first_name: Mapped[str | None]` — primeiro nome permanente (D-13)
- `last_name: Mapped[str | None]` — sobrenome permanente (D-13)
- `dietbox_patient_id: Mapped[int | None]` — ID do paciente no Dietbox

Nova tabela `PendingEscalation` com 11 colunas para relay bidirecional com Breno (Plans 02/03).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Fields] AgenteRetencao.__init__ sem motivo, consulta_atual, novo_slot**
- **Found during:** Task 1 ao implementar to_dict()
- **Issue:** O plano define campos `motivo`, `consulta_atual`, `novo_slot` no `__init__` do `AgenteRetencao`, mas o código existente não os declarava (eram usados apenas como atributos dinâmicos)
- **Fix:** Adicionados ao `__init__` com tipagem correta (`str | None` e `dict | None`)
- **Files modified:** `app/agents/retencao.py`
- **Commit:** 2f26f15

### Known Deferred Items

**1. Alembic migration ausente:**
- Diretório `alembic/` não existe no projeto
- Novas colunas/tabela são criadas via `Base.metadata.create_all()` no lifespan do FastAPI (`app/main.py`)
- Em produção com banco existente: colunas precisarão ser adicionadas manualmente ou com Alembic configurado
- Registrado como fora do escopo deste plano (zero impacto em ambiente de desenvolvimento com SQLite)

**2. Teste flaky pré-existente:**
- `tests/test_integration.py::test_fluxo_atendimento_pix_completo` falha quando executado junto com outros arquivos de teste (ordem de execução cria state compartilhado)
- Confirmado pré-existente via git stash — falha mesmo sem as mudanças deste plano
- Passa quando executado isoladamente (`pytest tests/test_integration.py`)

## Tests

```
tests/test_state_manager.py — 11 testes novos, todos passando
  test_atendimento_to_dict_tem_tipo          PASSED
  test_atendimento_to_dict_todos_campos      PASSED
  test_atendimento_round_trip               PASSED
  test_retencao_to_dict_tem_tipo             PASSED
  test_retencao_round_trip                  PASSED
  test_redis_save_and_load_round_trip       PASSED
  test_redis_load_none_para_chave_inexistente PASSED
  test_redis_delete_remove_chave            PASSED
  test_redis_save_sem_ttl                   PASSED
  test_redis_load_falha_retorna_none        PASSED
  test_to_dict_limita_historico_a_20_entradas PASSED

Suite completa: 115 passed (104 pré-existentes + 11 novos), 1 flaky pré-existente
```

## Security / LGPD Compliance

- `phone_hash` usado como chave Redis (nunca o número real)
- `historico` limitado a 20 entradas em to_dict() — mitigação T-01-01
- Número 31 99205-9211 não presente em nenhum arquivo modificado
- `PendingEscalation.phone_e164` armazenado apenas para roteamento interno — nunca exposto ao paciente

## Threat Surface Scan

Nenhuma nova superfície de rede ou endpoint criado. Mudanças limitadas a:
- Novo módulo de persistência interna (Redis já existia no stack)
- Novas colunas em tabelas existentes (sem novo acesso externo)

## Self-Check: PASSED

- app/state_manager.py: FOUND
- tests/test_state_manager.py: FOUND
- Commit 2f26f15 (Task 1): FOUND
- Commit 05ebf78 (Task 2): FOUND
- Contact.first_name column: VERIFIED
- PendingEscalation table: VERIFIED (11 colunas corretas)
- No TTL in Redis save(): VERIFIED (Test 8 passa)
- All 11 tests pass: VERIFIED
