# Relatório de Auditoria - Agente Ana v2

Data: 2026-05-13  
Branch: `refactor/agente-inteligente`

## Resumo Executivo

- `git pull`: repositório já estava atualizado.
- YAMLs: `scripts/validar_yamls.py` validou 9 arquivos sem erro sintático.
- Testes adversariais R1-R16 estavam bloqueados por import quebrado após cutover; corrigido com `app/conversation/state.py`.
- Nova bateria extrema adicionada com 116 cenários e execução verde.
- Replay massivo local: 1.063 conversas elegíveis, 4.751 turnos, 4.748 aceitos, score 99,94.

## Inventário

Arquivos principais em `app/conversation/`:

| Arquivo | Linhas |
|---|---:|
| `orchestrator.py` | 1.028+ |
| `rules.py` | 419+ |
| `command_processor.py` | 343 |
| `state_machine.py` | 330 |
| `scheduler.py` | 326 |
| `interpreter.py` | 301 |
| `tools/scheduling.py` | 244 |
| `interceptors/image_interceptor.py` | 203 |

Agente antigo removido. Estado persistente consolidado em `app/conversation/state.py`.

## Dívidas Técnicas

| Severidade | Item | Evidência | Ação |
|---|---|---|---|
| ALTA | Import público de estado v2 ausente | `tests/conversation_v2/e2e/test_regras_adversariais.py` não coletava | Corrigido com módulo de compatibilidade `app/conversation/state.py` |
| ALTA | `processar_turno` muito longo | `orchestrator.py::processar_turno` com ~358 linhas | Aceito por ora; recomenda extrair interceptadores em módulo próprio depois do hardening |
| MÉDIA | Funções longas em tools/interpreter/state_machine | 12 funções acima de 50 linhas | Refatorar sem alterar contrato após estabilização |
| MÉDIA | Referências YAML não resolvidas por validador simples | 7 refs parecem dinâmicas/ausentes: `criando_agendamento_aguardando_breno`, estados de comandos internos, `Fluxo_1.aguardando_cadastro` | Documentado; não bloqueou runtime atual |
| MÉDIA | Runner standalone não inicializava `sys.path` | `ModuleNotFoundError: app` ao rodar por caminho | Corrigido no runner |
| BAIXA | Placeholders complexos nos YAMLs | 113 placeholders únicos, alguns expressivos como `{valor_total_plano * 0.5}` | Manter validação dinâmica nos testes de fluxo |

Não foram encontrados `TODO`, `FIXME`, `HACK` ou `XXX` reais em `app/conversation`.

## Funções Acima de 50 Linhas

- `app/conversation/orchestrator.py:processar_turno` (~358)
- `app/conversation/interceptors/image_interceptor.py:_processar_comprovante` (~93)
- `app/conversation/interpreter.py:_heuristica` (~84)
- `app/conversation/rules.py:validar_distribuicao_slots` (~73)
- `app/conversation/state_machine.py:_avaliar_condicao` (~74)
- `app/conversation/tools/scheduling.py:marcar_confirmacao_dietbox` (~74)
- `app/conversation/tools/patients.py:detectar_tipo_remarcacao` (~68)

## Validação dos YAMLs

Comando executado:

```bash
python scripts/validar_yamls.py
```

Resultado: 9 YAMLs verificados, todos OK.

Observações adicionais:

- Estados finais/terminais sem saída são esperados: `concluido_pendente`, `concluido_escalado`, `caso_especial_concluido`, `comando_concluido`.
- Algumas referências são ações ou estados dinâmicos e não estados diretos; devem ser monitoradas em testes E2E.

## Matriz R1-R16

| Regra | Implementada em `rules.py` | Output validator | Teste específico | Hardening adicional |
|---|---:|---:|---:|---|
| R1 Breno nunca exposto | Sim | Sim | Sim | Testes de agressão com “Breno” |
| R2 contato Thaynara restrito | Sim | Sim | Sim | Output validator cobre lead novo |
| R3 não inventar valor | Sim | Sim | Sim | Testes com valores inventados |
| R4 horário fora da grade | Sim | Parcial, via ação/slots | Sim | Corrigida normalização de `terça` |
| R5 não confirmar sem pagamento | Sim | Ação pré-envio | Sim | Mantido |
| R6 sinal mínimo 50% | Sim | Ação pré-envio | Sim | Corrigido centavo abaixo do mínimo |
| R7 não orientar clinicamente | Sim | Sim | Sim | Testes com suplemento/dieta/Ozempic |
| R8 B2B 1 resposta/24h | Sim | Regra pura | Sim | Mantido |
| R9 desconto família só solicitado | Sim | Sim | Sim | Mantido |
| R10 idade mínima 16 | Sim | Cadastro/orchestrator | Sim | Interceptador global para texto livre |
| R11 gestante | Sim | Cadastro/orchestrator | Sim | Interceptador global para texto livre |
| R12 nome genérico | Sim | Interpreter/state | Sim | 20 casos extremos |
| R13 não sobrescrever nome | Sim | Regra pura | Sim | Mantido |
| R14 cancelamento PUT | Sim | Ação pré-envio | Sim | Mantido |
| R15 não falar perda de valor | Sim | Sim | Sim | Output validator reforçado em testes |
| R16 comprovante encaminhado | Sim | Regra pura/tool | Sim | Mantido |
