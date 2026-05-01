# PROXIMOPASSO

## Status Atual

O fluxo principal da Ana agora roda pela arquitetura `ConversationEngine`, com
Gemini em `llm_client`, estado em Redis e ferramentas isoladas em `app/tools/`.
A documentacao antiga de `AgenteAtendimento` e `AgenteRetencao` nao representa
mais o caminho principal de producao.

## Resolvido Hoje

- Validacao obrigatoria de ambiente no startup:
  `GEMINI_API_KEY`, token/phone id Meta, `DATABASE_URL` e `REDIS_URL`.
- Rate limit por numero no Redis: 30 mensagens por hora, com warning e silencio.
- Sanitizacao de input antes do pipeline conversacional, com limite de 2000 chars.
- Timeout geral de turno em 25 segundos com fallback ao paciente.
- Tratamento deterministico para audio, localizacao, figurinha e imagem que nao
  e comprovante.
- Aviso de fora de horario comercial, uma vez por periodo.
- Bloqueio de atendimento para gestantes e menores de 16 anos.
- Fluxo de remarcacao melhorado:
  - retorno expira apos 90 dias
  - confirmacao sempre inclui data/hora explicitas
  - rejeicao generica de horario pergunta o que nao atende antes de buscar novos slots
- Observabilidade:
  - `/health` com Redis, PostgreSQL, versao e timestamp
  - metricas JSONL por turno
  - alerta ao numero interno apos mais de 3 erros consecutivos
  - `/dashboard?key=DASHBOARD_KEY` com status simples
- Documentacao atualizada para a arquitetura real.
- Limpeza de imports/variaveis nao usados em `app/conversation/` e `app/tools/`.

## Pendencias Recomendadas

- Definir `DASHBOARD_KEY` no `.env` da VPS para habilitar o dashboard.
- Acompanhar `logs/metrics.jsonl` nas primeiras conversas reais apos deploy.
- Revisar manualmente no WhatsApp real:
  - novo paciente
  - retorno valido
  - retorno vencido
  - comprovante real
  - pergunta clinica
- Conferir se a regra de fora de horario deve bloquear todo processamento ou
  apenas avisar e continuar em casos especificos.

## Comandos Uteis

```bash
pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py -q
pytest tests/test_bug_fixes.py tests/test_remarcacao_humana.py tests/test_remarcacao_slots.py -q
pytest tests/test_ponta_a_ponta.py -q
```

Deploy:

```bash
git push
ssh root@anna.vps-kinghost.net "cd /root/agente && git pull && docker compose up --build -d app"
ssh root@anna.vps-kinghost.net "curl -s http://localhost:8000/health"
```
