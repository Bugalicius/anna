# CLAUDE.md

## Projeto

Agente Ana e um backend FastAPI para atendimento via WhatsApp da nutricionista
Thaynara Teixeira. O fluxo principal de producao hoje passa por:

`WhatsApp -> app/webhook.py -> app/router.py -> processar_turno (Orchestrator v2) -> Meta API`

**v2.0 (reescrita completa)** — o motor conversacional e agora o Orchestrator v2
em `app/conversation/`. O codigo legado esta preservado em `app/conversation_legacy/`
para consulta mas nao e mais o caminho ativo.
Novas mudancas devem priorizar `app/conversation/` (orchestrator, state_machine, rules).

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
- `app/conversation_legacy/`: engine v1 preservado para referencia (nao e o caminho ativo).
- Estado compartilhado: `app/conversation_legacy/state.py` (Redis, reusado pelo v2).

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
ssh root@anna.vps-kinghost.net "cd /root/agente && git pull && docker compose up --build -d app"
ssh root@anna.vps-kinghost.net "cd /root/agente && docker compose logs --tail=50 app"
```
