# CLAUDE.md

## Projeto

Agente Ana e um backend FastAPI para atendimento via WhatsApp da nutricionista
Thaynara Teixeira. O fluxo principal de producao hoje passa por:

`WhatsApp -> app/webhook.py -> app/router.py -> ConversationEngine -> Meta API`

A arquitetura antiga com `AgenteAtendimento` e `AgenteRetencao` ainda existe em
alguns arquivos historicos, mas nao e mais o caminho principal de atendimento.
Novas mudancas devem priorizar `app/conversation/` e `app/tools/`.

## Arquitetura Atual

### Entrada HTTP

- `app/main.py`: cria o app FastAPI, valida variaveis obrigatorias no startup,
  inicializa scheduler, expoe `/health`, `/dashboard`, `/privacy` e monta routers.
- `app/webhook.py`: recebe webhooks da Meta, valida payload, deduplica mensagens,
  aplica rate limit, trata midias simples, registra inbound no banco e chama o router.
- `app/router.py`: carrega/atualiza contato, chama `ConversationEngine` e envia
  respostas pela Meta API.

### Motor Conversacional

- `app/conversation/engine.py`: orquestra um turno completo:
  1. carrega estado no Redis
  2. interpreta mensagem
  3. aplica extracoes ao estado
  4. decide a proxima acao
  5. executa tool quando necessario
  6. gera resposta
  7. salva estado e metricas
- `app/conversation/interpreter.py`: interpreta intent, campos informados,
  escolhas de slot, perguntas e restricoes. Usa `app/llm_client.py`.
- `app/conversation/planner.py`: decide a acao operacional. Primeiro roda
  overrides deterministicos de seguranca/fluxo; se nao houver override, usa Gemini.
- `app/conversation/responder.py`: transforma plano e resultado de tool em
  mensagens finais com tom da Ana.
- `app/conversation/state.py`: serializa estado de conversa no Redis e reidrata
  dados persistentes do contato.

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
