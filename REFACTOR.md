# Reescrita do Agente Ana — Status

## Branch atual: refactor/agente-inteligente

## Fases concluídas:
- [x] Fase 0: Setup

## Próxima fase: Fase 1 — Núcleo do sistema

## Estrutura nova
- `app/conversation_v2/` — código novo
- `config/global.yaml` — config global
- `config/fluxos/*.yaml` — fluxos declarativos

## Status do agente antigo
- Pausado em produção desde 2026-05-11
- Código em `app/conversation/` (intocado)
- Será removido na Fase 9 (cutover)

## Arquitetura alvo

```
WhatsApp -> webhook.py -> router.py -> orchestrator.py
                                           |
                          interpreter  state_machine  rule_engine
                                           |
                                         tools
                                           |
                                    response_writer -> output_validator
                                           |
                                       Meta API
```

## Módulos novos (em app/conversation_v2/)

| Módulo | Tamanho alvo | Status |
|---|---|---|
| orchestrator.py | ~200 linhas | pendente |
| state_machine.py | ~400 linhas | pendente |
| rules.py | ~300 linhas | pendente |
| interpreter.py | ~150 linhas | pendente |
| response_writer.py | ~250 linhas | pendente |
| tools/ | ~400 linhas | pendente |
