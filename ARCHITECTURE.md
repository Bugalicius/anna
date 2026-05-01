# ARCHITECTURE.md

## Fluxo de Producao

```text
WhatsApp / Meta Cloud API
          |
          v
app/webhook.py
  - valida payload e assinatura quando configurado
  - deduplica mensagens
  - aplica rate limit Redis por numero
  - trata audio, localizacao, sticker e imagens nao comprovante
  - persiste inbound em PostgreSQL
          |
          v
app/router.py
  - cria/atualiza Contact e Conversation
  - chama ConversationEngine
  - envia respostas pela Meta API
          |
          v
ConversationEngine
          |
          +--> Interpreter (Gemini via app/llm_client.py)
          |      - intent
          |      - campos coletados
          |      - escolha de slot
          |      - pergunta operacional/clinica
          |
          +--> Planner
          |      - overrides deterministicos primeiro
          |      - Gemini quando a regra fixa nao cobre
          |      - escolhe action/tool/update de estado
          |
          +--> Tools
          |      - scheduling.py: Dietbox slots/agendar/remarcar/cancelar
          |      - patients.py: busca de paciente e retorno vencido
          |      - payments.py: PIX/cartao/comprovantes
          |      - escalation.py: duvidas clinicas
          |
          +--> Responder
                 - templates seguros
                 - mensagens curtas no tom da Ana
                 - sanitizacao final contra respostas indevidas
          |
          v
Meta API -> Paciente
```

## Persistencia de Estado

Redis guarda o estado operacional de cada conversa por `phone_hash`:

- `goal`
- `status`
- `collected_data`
- `appointment`
- `flags`
- `history`
- `last_slots_offered`
- `slots_pool`
- resultados recentes de tools

PostgreSQL guarda entidades duraveis:

- `Contact`
- `Conversation`
- `Message`
- `RemarketingQueue`
- `PendingEscalation`

## Overrides Deterministicos

Overrides disparam antes do planner LLM quando ha risco operacional ou regra de
negocio clara:

- rate limit por numero
- fora de horario
- audio/localizacao/sticker
- imagem que nao e comprovante
- gestante ou menor de 16 anos
- pergunta sobre reputacao/depoimento sem base factual
- handoff de remarcacao para nova consulta
- retorno vencido por prazo de 90 dias
- resistencia generica a horarios ofertados

## LLMs por Etapa

- `Interpreter`: Gemini classifica a mensagem e extrai dados.
- `Planner`: Gemini decide action/tool apenas quando os overrides nao resolveram.
- `Responder`: usa templates e dados de estado/tool; nao deve inventar valores,
  horarios, politicas ou dados pessoais.

## Observabilidade

- `/health`: Redis, PostgreSQL, versao e timestamp.
- `/dashboard?key=DASHBOARD_KEY`: HTML simples com conversas 24h, sucesso,
  erros recentes e status dos servicos.
- `logs/metrics.jsonl`: um JSON por turno com hash do paciente, intent, action,
  duracao, decisao (`llm`, `override`, `fallback`) e erro.
- Redis `errors:turn:{phone_hash}`: contador de erros consecutivos. Acima de 3,
  a Ana envia alerta interno pela Meta API.
