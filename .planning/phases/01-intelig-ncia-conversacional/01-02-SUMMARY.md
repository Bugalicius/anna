---
phase: 01-intelig-ncia-conversacional
plan: "02"
subsystem: router-redis-integration
tags: [redis, router, interrupt-detection, inline-response, orchestrator, context-aware]
dependency_graph:
  requires:
    - app/state_manager.py: RedisStateManager (Plan 01-01)
    - app/agents/atendimento.py: to_dict/from_dict (Plan 01-01)
    - app/agents/retencao.py: to_dict/from_dict (Plan 01-01)
    - app/models.py: Contact.first_name (Plan 01-01)
  provides:
    - app/router.py: route_message com Redis load/save/delete + interrupt detection
    - app/router.py: init_state_manager() inicializado no lifespan
    - app/agents/orchestrator.py: rotear() aceita agente_ativo para classificacao sempre
  affects:
    - Plan 01-03: router pronto para receber AgenteEscalacao como agente ativo
tech_stack:
  added: []
  patterns:
    - type(agent).__name__ + getattr(_tipo) fallback para identificacao de tipo sem isinstance quebrar mocks
    - frozenset imutavel para _INTENCOES_INTERRUPT e _INTENCOES_INLINE
    - init_state_manager() injetado no lifespan do FastAPI
key_files:
  created: []
  modified:
    - app/router.py
    - app/agents/orchestrator.py
    - app/main.py
    - tests/test_router.py
    - tests/test_integration.py
decisions:
  - "type(agent).__name__ + getattr(_tipo) como fallback: permite mocks em testes sem quebrar isinstance"
  - "frozenset para conjuntos de intencoes: imutavel e O(1) para lookup"
  - "Saudacao personalizada apenas em sessao nova (agente_ativo is None) para evitar repeticao"
  - "app/main.py atualizado com init_state_manager() no lifespan (WARNING-1 do plan-checker)"
metrics:
  duration: "~35 minutos"
  completed_date: "2026-04-14"
  tasks_completed: 1
  tasks_total: 1
  files_created: 0
  files_modified: 5
---

# Phase 01 Plan 02: Redis Router Integration + Context-Aware Orchestrator Summary

**One-liner:** router.py refatorado com Redis state load/save/delete, interrupt detection (D-02), inline response (D-03), reconhecimento por nome (D-14) e orquestrador sempre ativo (D-01).

## What Was Built

### app/router.py (refatorado)

`_AGENT_STATE` dict in-memory removido completamente. Substituído por `RedisStateManager` global inicializado via `init_state_manager(redis_url)`.

`route_message()` agora:
1. Carrega agente ativo do Redis via `_state_mgr.load(phone_hash)`
2. Determina `tipo_agente` para contexto do orquestrador
3. Classifica intenção SEMPRE via `rotear()` — mesmo com agente ativo (D-01)
4. Detecta interrupções: `remarcar/cancelar/duvida_clinica` deletam estado antigo e criam novo agente (D-02)
5. Responde inline para `tirar_duvida/fora_de_contexto` sem trocar de agente (D-03)
6. Saúda paciente de retorno pelo `first_name` em sessão nova (D-14)
7. Salva estado no Redis após processar; deleta em etapa terminal `finalizacao/concluido`
8. Falha do Redis retorna `None` sem crash — fluxo normal continua (D-15)

Novos helpers:
- `init_state_manager(redis_url)` — inicializa `_state_mgr` global
- `_tipo_agente(agent)` — identifica tipo por `type.__name__` com fallback `getattr(_tipo)` para compatibilidade com mocks
- `_fluxo_finalizado(agent)` — detecta etapa terminal
- `_salvar_nome_contact(phone_hash, nome)` — persiste nome no Contact ao interromper fluxo
- `_inferir_modalidade_de_contato(phone_hash)` — busca modalidade no banco

Segurança (T-01-04): intenção validada contra `_INTENCOES_INTERRUPT` e `_INTENCOES_INLINE` (frozensets) antes de agir.
Privacidade (T-01-05): `phone_hash` como chave Redis, número interno ausente.

### app/agents/orchestrator.py (expandido)

`rotear()` agora aceita `agente_ativo: str | None = None`. Quando presente, inclui contexto no prompt de classificação:
```
Contexto: o paciente está no meio de um fluxo de {agente_ativo}. Classifique a intenção real da mensagem mesmo assim.
```

`_classificar_intencao()` aceita `contexto: str = ""` — passa contexto para o LLM sem alterar a interface pública.

### app/main.py (atualizado — WARNING-1)

Lifespan do FastAPI agora chama `init_state_manager(redis_url)` antes de iniciar o scheduler:
```python
from app.router import init_state_manager
redis_url = os.environ.get("REDIS_URL", "redis://redis:6379")
init_state_manager(redis_url)
```

### tests/test_router.py (reescrito)

11 novos testes além dos 12 existentes (total: 23):
- Test 1: `load()` chamado no início de `route_message`
- Test 2: `save()` chamado após processar (etapa não terminal)
- Test 3: `delete()` chamado em `etapa == "finalizacao"`
- Test 4: interrupt detection — remarcar com agente ativo troca para AgenteRetencao
- Test 5: inline tirar_duvida — agente não troca, save chamado
- Test 6: inline fora_de_contexto — agente não troca, delete não chamado
- Test 7: first_name="Marcela" -> saudação com nome
- Test 8: Redis retorna None -> sem crash
- Test 9: rotear() aceita parâmetro `agente_ativo`
- Test 10: `_AGENT_STATE` não existe mais em `app.router`

Todos os patches usam `app.router.*` (não `app.database.*`) para interceptar corretamente após import.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] isinstance() quebra com mocks — _tipo_agente() helper**
- **Found during:** Task 1 ao executar testes
- **Issue:** `isinstance(mock_instance, AgenteAtendimento)` lança `TypeError` quando a classe é substituída por `MagicMock` via `patch()`
- **Fix:** Criado helper `_tipo_agente(agent)` que usa `type(agent).__name__` com fallback `getattr(agent, '_tipo', None)` — compatível com instâncias reais e mocks
- **Files modified:** `app/router.py`
- **Commit:** cd31a67

**2. [Rule 2 - Missing] test_integration.py importava _AGENT_STATE**
- **Found during:** Execução da suite completa após implementar router.py
- **Issue:** `test_route_message_atendimento` importava `_AGENT_STATE` (removido) e não mockava `_state_mgr`
- **Fix:** Atualizado para mockar `_state_mgr` com `AsyncMock` e adicionado `first_name = None` nos mocks de Contact
- **Files modified:** `tests/test_integration.py`
- **Commit:** cd31a67

## Tests

```
tests/test_router.py        — 23 testes (12 existentes + 11 novos), todos passando
tests/test_state_manager.py — 11 testes (Plan 01-01), todos passando
Suite completa: 165 passed, 1 warning (FutureWarning google-generativeai — pre-existente)
```

## Security / LGPD Compliance

- `phone_hash` como chave Redis — número real nunca armazenado no Redis (T-01-05)
- Intenção validada contra `frozenset` antes de rotear — previne routing inesperado (T-01-04)
- Redis failure retorna `None` sem expor erro ao usuário (T-01-06)
- Número 31 99205-9211 ausente em todos os arquivos modificados (INTL-04)

## Threat Surface Scan

Nenhuma nova superfície de rede ou endpoint criado. Mudanças limitadas a lógica interna de roteamento e chamadas ao Redis já existente no stack.

## Known Stubs

Nenhum stub identificado. Toda a lógica de roteamento está wired ao `_state_mgr` real e o `init_state_manager()` é chamado no lifespan.

## Self-Check: PASSED

- app/router.py: FOUND
- app/agents/orchestrator.py: FOUND (agente_ativo param presente)
- app/main.py: FOUND (init_state_manager chamado no lifespan)
- tests/test_router.py: FOUND (23 testes)
- Commit 6f39eed (RED tests): FOUND
- Commit cd31a67 (GREEN implementation): FOUND
- _AGENT_STATE dict removido de router.py: VERIFIED (apenas comentário)
- Número 99205 ausente de router.py: VERIFIED
- 165 tests passed: VERIFIED
