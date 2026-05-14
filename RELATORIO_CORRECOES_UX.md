# Relatorio de Correcoes UX - Conversacao v2.4

Data: 2026-05-14
Base: v2.2.1-webhook-validado

## BUG 1 - Contexto nao expirava

Causa raiz: o estado persistido em Redis nao era reavaliado por inatividade antes
do processamento do turno. Um paciente voltando horas depois continuava preso em
estados como `aguardando_escolha_plano`.

Correcao: `maybe_reset_stale_state` reseta o estado para `inicio` quando
`last_message_at` passa de `INACTIVITY_RESET_HOURS` (padrao 1h), preservando
apenas o nome e as ultimas mensagens para referencia.

## BUG 2 - Loop de fallback infinito

Causa raiz: o fluxo de fora de contexto incrementava contador e ate escalava
silenciosamente, mas continuava enviando a mesma resposta de fallback ao paciente.

Correcao: o orchestrator agora controla `fallback_streak` e `last_response_hash`.
Ao detectar fallback repetido, chama `escalar_breno_silencioso`, muda o estado
para `aguardando_orientacao_breno` e substitui a resposta por:

`Deixa eu chamar alguém da equipe pra te dar atenção especial 💚`

## BUG 3 - Mensagem duplicada no mesmo turno

Causa raiz: havia protecao de debounce, mas faltava uma trava explicita no
pipeline conversacional para impedir execucao paralela por telefone.

Correcao: `app/conversation/locks.py` adiciona lock por telefone via Redis com
TTL de 60s e fallback local. Se outro turno ja estiver processando o mesmo
telefone, a execucao retorna sem enviar resposta duplicada e registra metrica.

## BUG 4 - Debounce longo e sem indicador visual

Causa raiz: o debounce usava `MESSAGE_DEBOUNCE_SECONDS` com default de 30s e o
typing indicator estava implementado como no-op.

Correcao: o webhook usa `DEBOUNCE_SECONDS=15`, reinicia a janela a cada nova
mensagem e processa o buffer em um unico turno. Antes do processamento e antes
do envio das respostas, o app tenta enviar typing indicator via Cloud API usando
o `message_id` mais recente. Falhas sao logadas e nao bloqueiam a resposta.

## Observabilidade

Eventos relevantes agora sao registrados em `logs/metrics.jsonl`:

- `state_reset_inactivity`
- `fallback_loop_escalado`
- `processing_lock_busy`
- `debounce_flush`

## Testes

Cobertura adicionada em `tests/conversation_v2/regression/test_bugs_producao.py`:

- `test_bug1_contexto_nao_expira`
- `test_bug2_loop_fallback_escala`
- `test_bug3_mensagens_paralelas_nao_duplicam`
- `test_bug4_debounce_15s_apos_ultima`
