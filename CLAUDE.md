# CLAUDE.md

## Projeto

Agente Ana e um backend FastAPI para atendimento via WhatsApp da nutricionista
Thaynara Teixeira. O fluxo principal de producao hoje passa por:

`WhatsApp -> app/webhook.py -> app/router.py -> processar_turno (Orchestrator v2) -> Meta API`

Producao consolidada no VPS: `root@anna.vps-kinghost.net:/root/agente`.
Backups preservados em `/root/agente-OLD-v1-backup-20260513-061057` e
`/root/agente-v21-backup-20260513-061057`.

**v2.0 (reescrita completa)** — o motor conversacional ativo e o Orchestrator v2
em `app/conversation/`. O agente antigo foi removido do repositorio; novas
mudancas devem priorizar `app/conversation/` (orchestrator, state_machine, rules).

## Arquitetura Atual

### Entrada HTTP

- `app/main.py`: cria o app FastAPI, valida variaveis obrigatorias no startup,
  inicializa scheduler, expoe `/health`, `/dashboard`, `/privacy` e monta routers.
- `app/webhook.py`: recebe webhooks da Meta, valida payload, deduplica mensagens,
  aplica rate limit, trata midias simples, registra inbound no banco e chama o router.
- `app/router.py`: carrega/atualiza contato, chama `ConversationEngine` e envia
  respostas pela Meta API.

### Motor Conversacional (v2 — ativo em producao)

- `app/conversation/orchestrator.py`: ponto de entrada principal (`processar_turno`).
  Coordena interpretacao, state machine, tools e escrita de resposta.
- `app/conversation/state_machine.py`: decide proxima acao com base em estado e intent.
- `app/conversation/rules.py`: 16 regras inviolaveis validadas antes de toda resposta.
- `app/conversation/interpreter.py`: interpreta intent e extrai entidades via Gemini.
- `app/conversation/response_writer.py`: gera mensagens finais com tom da Ana.
- `app/conversation/scheduler.py`: jobs automaticos (confirmacao semanal, lembrete vespera).
- `app/conversation/tools/`: scheduling, patients, payments, media, notifications, commands.
- Estado persistente: `app/conversation/state.py` (Redis com fallback in-memory).

### LLM

- Provider atual: Gemini via `app/llm_client.py`.
- Chamadas principais:
  - interpreter: classifica e extrai dados do turno
  - planner: escolhe action/tool quando nao ha regra deterministica
  - responder: usa templates e guardrails, sem deixar o LLM inventar dados criticos
- Variavel obrigatoria: `GEMINI_API_KEY`.

### Tools

- `app/tools/scheduling.py`: slots, agendamento, remarcacao e cancelamento.
- `app/tools/patients.py`: busca de paciente e classificacao de remarcacao/retorno.
- `app/tools/payments.py`: PIX/cartao/comprovante e confirmacao financeira.
- `app/tools/escalation.py`: encaminhamento de duvida clinica ao numero interno.

### Persistencia

- PostgreSQL: contatos, conversas, mensagens e filas.
- Redis: estado de conversa, deduplicacao operacional, rate limit por numero,
  aviso de fora de horario e contagem de erros consecutivos.
- `logs/metrics.jsonl`: metricas estruturadas por turno.

### Configuracao de Debounce e UX

- `INACTIVITY_RESET_HOURS=1`: reseta o contexto para `inicio` quando o paciente
  volta depois de 1h sem mensagem.
- `DEBOUNCE_SECONDS=15`: aguarda 15s apos a ultima mensagem de texto do paciente
  antes de processar o turno agrupado.
- `TYPING_INDICATOR_ENABLED=true`: envia o indicador "digitando..." via Meta API
  com `message_id` valido antes da resposta; falhas sao logadas e nao bloqueiam
  o envio.
- O orchestrator usa lock por telefone (`agente:lock:processing:{phone}`) com TTL
  de 60s para evitar duas execucoes paralelas do pipeline.

### Monitoramento

- Servico Docker: `monitor`, comando `python -m app.monitor.main`.
- Roda checks a cada `MONITOR_INTERVAL_SECONDS` (padrao 60s) e grava JSONL em
  `logs/monitor/YYYY-MM-DD.jsonl`.
- Alertas WhatsApp vao para `MONITOR_ALERTS_TO` (padrao `BRENO_PHONE`) usando
  `app.meta_api.MetaAPIClient`.
- Dedup Redis:
  - critico: `MONITOR_CRITICAL_DEDUP_MINUTES` (padrao 5)
  - alerta: `MONITOR_ALERT_DEDUP_MINUTES` (padrao 30)
  - persistente: status a cada `MONITOR_STATUS_UPDATE_MINUTES` (padrao 60)
- Dry-run:
  `MONITOR_DRY_RUN=true docker compose run --rm monitor python -m app.monitor.main --once`
- Check individual:
  `docker compose run --rm monitor python -m app.monitor.main --once --check redis`

## Regras Importantes

- Nunca expor o numero interno do Breno/Thaynara para pacientes.
- Nunca responder duvida clinica como se fosse orientacao nutricional.
- Nunca inventar relacao pessoal com a Thaynara ou depoimentos de pacientes.
- Fora do horario comercial, responder apenas uma vez por periodo.
- Mensagens acima de 2000 caracteres devem ser sanitizadas antes do LLM.
- Audio/localizacao/figurinhas devem receber respostas deterministicamente.
- Gestantes e menores de 16 anos devem ser recusados com a mensagem padrao.

## Variaveis Criticas

O app recusa iniciar se faltar:

- `GEMINI_API_KEY`
- `META_ACCESS_TOKEN` ou `WHATSAPP_TOKEN`
- `META_PHONE_NUMBER_ID` ou `WHATSAPP_PHONE_NUMBER_ID`
- `DATABASE_URL`
- `REDIS_URL`

Para dashboard:

- `DASHBOARD_KEY`

## Testes e Verificacao

Antes de commit, rode ao menos a suite relacionada ao arquivo alterado. Para
mudancas amplas no fluxo conversacional:

```bash
pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py -q
pytest tests/test_bug_fixes.py tests/test_remarcacao_humana.py -q
```

Para deploy:

```bash
git push
ssh root@anna.vps-kinghost.net "cd /root/agente && git pull && docker compose -p agente up --build -d app nginx"
ssh root@anna.vps-kinghost.net "cd /root/agente && docker compose -p agente logs --tail=50 app"
```
