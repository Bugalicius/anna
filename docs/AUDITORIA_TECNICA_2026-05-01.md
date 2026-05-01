# Auditoria tecnica e quadro atualizado do projeto

Data: 2026-05-01

Escopo auditado: codigo local em `C:\Users\Breno\Desktop\agente`, estado da VPS `root@anna.vps-kinghost.net:/root/agente`, Docker, rotas principais, motor conversacional, integracoes, testes e documentacao existente.

## Resumo executivo

O agente esta funcional no caminho principal de producao. A VPS esta com `app`, `nginx`, `postgres` e `redis` ativos, e `/health` retorna `ok` para Redis e PostgreSQL. A suite focada do fluxo atual passou com 81 testes verdes.

O principal problema nao e estabilidade imediata do fluxo novo, mas acumulacao de legado e desalinhamento de processo: existem testes importando modulos removidos, arquivos duplicados que representam arquiteturas antigas e algumas rotas/servicos de teste montados no app de producao. Tambem ha riscos pontuais de integracao por uso inconsistente das variaveis `META_*` versus `WHATSAPP_*`, e um bug importante no processamento de respostas internas do Breno/Thaynara.

## Evidencias de verificacao

- VPS: `/root/agente`, branch `main`, commit `5180b86 feat: versiona knowledge_base JSONs e migra transcrição de áudio para Gemini`.
- Containers ativos: `agente-app-1`, `agente-nginx-1`, `agente-postgres-1`, `agente-redis-1`.
- Health VPS: `{"status":"ok","services":{"redis":{"status":"ok"},"postgres":{"status":"ok"}}}`.
- Testes focados executados:
  `pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py tests/test_bug_fixes.py tests/test_remarcacao_humana.py tests/test_remarcacao_slots.py -q`
  Resultado: `81 passed`.
- Pytest completo:
  `pytest -q`
  Resultado: falha na coleta por `ModuleNotFoundError: No module named 'app.agents.atendimento'`.
- Compilacao Python:
  `python -m compileall -q app tests`
  Resultado: sem erro de sintaxe.

## Achados prioritarios

### P0 - Respostas internas do Breno podem nao chegar ao paciente

Arquivos: `app/webhook.py`, `app/command_processor.py`.

Hoje, qualquer mensagem vinda de remetente autorizado entra primeiro em `process_command`. Quando o texto nao e reconhecido como comando, `process_command` responde "Nao entendi o comando" e retorna `True`. Com isso, o fallback em `webhook.py` que deveria chamar `processar_resposta_breno` fica inacessivel para respostas naturais do Breno a uma escalacao.

Impacto: uma duvida clinica escalada pode ficar sem resposta ao paciente, porque a resposta humana pode ser interpretada como comando invalido.

Correcao sugerida:
- Em `process_command`, retornar `False` quando `tipo == "desconhecido"` para `BRENO_PHONE/NUMERO_INTERNO`, permitindo o relay de escalacao.
- Para `THAYNARA_PHONE`, manter resposta de comando invalido se essa for a regra desejada.
- Adicionar teste: "Breno responde texto livre com pending escalation aberta -> paciente recebe resposta".

### P0 - Suite completa esta quebrada por testes legados

Arquivos: `tests/test_state_manager.py`, `tests/test_behavior.py`, `tests/test_integration.py`.

Testes ainda importam `app.agents.atendimento`, `app.agents.retencao` e `app.state_manager`, mas a arquitetura atual usa `app/conversation/*`. O pytest completo para na coleta.

Impacto: CI nao consegue validar o repositorio inteiro. Isso cria falsa confianca, porque apenas suites manuais/focadas passam.

Correcao sugerida:
- Migrar testes antigos para `ConversationEngine` e `app.conversation.state`.
- Ou marcar explicitamente como legado/arquivados fora de `tests/`.
- Definir uma suite oficial em CI e documentar: `pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py ...`.

### P1 - Uso inconsistente de `META_*` e `WHATSAPP_*`

Arquivos: `app/config.py`, `app/media_handler.py`, `app/webhook.py`, `app/remarketing.py`, `app/flows.py`, `.env.example`.

`app/config.py` aceita aliases `META_ACCESS_TOKEN`/`WHATSAPP_TOKEN` e `META_PHONE_NUMBER_ID`/`WHATSAPP_PHONE_NUMBER_ID`. Mas alguns pontos usam apenas `WHATSAPP_TOKEN` e `WHATSAPP_PHONE_NUMBER_ID`.

Exemplos:
- `app/media_handler.py` baixa midia usando somente `WHATSAPP_TOKEN`.
- `app/webhook.py` cria `MetaAPIClient` para comandos usando somente envs `WHATSAPP_*`.
- `app/remarketing.py` instancia clientes Meta com somente `WHATSAPP_*`.
- `.env.example` documenta principalmente `META_*`.

Impacto: deploys configurados somente com `META_*` podem enviar texto pelo cliente padrao, mas falhar em audio, midia, comandos ou remarketing.

Correcao sugerida:
- Usar sempre `get_meta_access_token()` e `get_meta_phone_number_id()`.
- Manter aliases apenas na borda de configuracao.
- Atualizar `.env.example` para documentar os dois nomes ou padronizar um unico par.

### P1 - Arquivos de midia com acento nao batem com o catalogo

Arquivo: `app/media_store.py`.

O catalogo aponta para:
- `docs/Guia - Circunferencias Corporais - Mulheres.pdf`
- `docs/Guia - Circunferencias Corporais - Homens.pdf`

Mas os arquivos reais sao:
- `docs/Guia - Circunferências Corporais - Mulheres.pdf`
- `docs/Guia - Circunferências Corporais - Homens.pdf`

Impacto: envio desses PDFs pode falhar em producao. O relatorio anterior ja registrava esse sintoma.

Correcao sugerida:
- Ajustar `MEDIA_STATIC` para os nomes reais ou renomear os arquivos para ASCII.
- Adicionar teste que valida existencia de todos os paths de `MEDIA_STATIC`.

### P1 - Rotas de teste estao montadas no app de producao

Arquivo: `app/main.py`.

`app.include_router(test_chat_router)` esta sempre ativo. Isso expõe endpoints de teste junto do app real.

Impacto: superficie operacional maior, risco de reset/conversa fake em producao e confusao em observabilidade.

Correcao sugerida:
- Montar `test_chat_router` apenas quando `ENABLE_TEST_CHAT=true`.
- Proteger endpoints de teste com chave, ou separar app/dev.

### P1 - Banco e migracoes ainda dependem de fallback automatico

Arquivo: `app/main.py`.

O startup chama `Base.metadata.create_all(bind=engine)`. Isso ajuda no inicio, mas esconde ausencia de migracoes reais.

Impacto: mudancas de schema futuras podem nao ser aplicadas corretamente; `create_all` nao altera colunas existentes.

Correcao sugerida:
- Introduzir Alembic como fluxo oficial.
- No startup de producao, trocar `create_all` por validacao de migration head.
- Manter `create_all` somente em teste/local.

### P1 - App Docker de producao monta codigo local e expõe bancos

Arquivo: `docker-compose.yml`.

O compose monta `./app:/app/app`, `./tests:/app/tests`, `./docs:/app/docs` e expõe `postgres:5433` e `redis:6379` no host.

Impacto: imagem deixa de ser artefato imutavel; bancos ficam expostos no host; testes entram no container de producao.

Correcao sugerida:
- Criar `docker-compose.prod.yml` sem bind mount de codigo/testes.
- Remover portas publicas de Postgres/Redis em producao.
- Manter volumes apenas para dados, docs se necessario e certificados.

### P2 - Duplicidade de modulos e codigo legado

Arquivos provaveis para revisar/remover:
- `app/scheduling.py`: duplicado antigo de `app/tools/scheduling.py`.
- `app/state.py`: duplicado antigo de `app/conversation/state.py`.
- `app/flows.py`: fluxo antigo; nao esta no caminho atual de producao.
- `responder.py` na raiz: aparentemente historico.
- `app/tools/escalation.py`: wrapper simples sem uso produtivo claro.
- Testes legados de `AgenteAtendimento`/`AgenteRetencao`.

Impacto: aumenta custo de manutencao e chance de corrigir o arquivo errado.

Correcao sugerida:
- Criar pasta `legacy/` fora do pacote `app` ou remover apos migrar testes.
- Manter apenas um modulo por responsabilidade.
- Bloquear novos imports legados com teste estatico simples.

### P2 - Criacao repetida de clientes Redis, HTTP e Gemini

Arquivos: `app/webhook.py`, `app/rate_limit.py`, `app/chatwoot_bridge.py`, `app/metrics.py`, `app/llm_client.py`, `app/meta_api.py`.

Hoje varias funcoes chamam `Redis.from_url`, `httpx.AsyncClient` e `genai.Client` por operacao.

Impacto: overhead de conexao, latencia e uso maior de CPU/rede. Em pico, pode aumentar timeout e custo indireto.

Correcao sugerida:
- Criar singletons no lifespan para Redis e HTTP clients.
- Injetar dependencias em `MetaAPIClient`, Chatwoot bridge, rate limit e metrics.
- Reusar `genai.Client` por processo.

### P2 - LLM ainda roda ate tres vezes por turno

Caminho: `Interpreter -> Planner -> Responder fallback`.

O projeto ja reduziu chamadas com heuristicas e overrides, mas ainda existem casos em que o turno pode chamar:
- Interpreter LLM.
- Planner LLM.
- Responder LLM em `answer_free`.
- Vision/audio LLM para comprovantes e audios.

Impacto: custo em tokens, latencia e maior chance de timeout.

Otimizacoes sugeridas:
- Medir por turno: `llm_calls`, `input_tokens_est`, `output_tokens_est`, `stage`.
- Expandir bypass deterministico para mensagens curtas e botoes: `pix`, `cartao`, `online`, `presencial`, `slot_1`, `confirmar_presenca`, `remarcar_consulta`, comprovante, audio falho.
- Converter casos frequentes do planner para regras: boas-vindas, coleta de nome/status, envio de planos, modalidade, forma de pagamento, escolha de slot.
- Usar LLM apenas para ambiguidade real e perguntas abertas.

### P2 - Observabilidade boa, mas incompleta para decisao de negocio

Existente:
- `/health`.
- `/dashboard?key=...`.
- `logs/metrics.jsonl`.
- Contador de erros consecutivos no Redis.

Faltando:
- Metrica de custo/LLM por etapa.
- Taxa de handoff humano.
- Taxa de mensagens perdidas por janela 24h da Meta.
- Contagem de falhas por integracao: Meta, Dietbox, Rede/MercadoPago, Chatwoot.
- Tempo medio por turno e por tool.

Correcao sugerida:
- Enriquecer `write_turn_metric`.
- Separar `decision=override|llm|fallback` por etapa.
- Registrar `tool_duration_ms` e `integration_error_code`.

## Otimizacao de custos e processos

1. Reduzir LLM no Interpreter: manter `_heuristic_turno` como primeira barreira e ampliar confianca para respostas atomicas. Cada mensagem de botao deveria ser 100% deterministica.
2. Reduzir LLM no Planner: transformar a maior parte do funil linear em state machine deterministica. O LLM deve decidir apenas quando ha texto livre ambivalente.
3. Evitar `answer_free` como saida frequente: preferir templates por `ask_context` e resposta padrao de fora de contexto.
4. Centralizar clientes: menos conexoes por mensagem reduz latencia e risco de timeout.
5. Revisar Playwright no Docker: instalar Chromium deixa a imagem pesada. Se Rede/Dietbox Playwright nao roda no container principal com frequencia, mover para worker separado ou imagem dedicada.
6. Separar producao e desenvolvimento: compose produtivo sem testes, sem bind mounts e sem banco exposto.
7. Criar fila para operacoes lentas: Dietbox, Rede, upload de midia e Chatwoot podem ficar atras de fila com retry/backoff.
8. Usar cache operacional: slots Dietbox por modalidade/dia podem ter TTL curto de 2-5 minutos para evitar chamadas repetidas em rajadas.

## Pontas soltas de logica e erro

- Webhook exige assinatura sempre. Se `META_APP_SECRET` estiver vazio, qualquer chamada sem assinatura falha com 403. Isso e bom para seguranca, mas precisa estar documentado como obrigatorio real.
- Dedup e debounce fazem fail-open quando Redis cai. Isso preserva atendimento, mas pode gerar duplicidade e custo. Precisa de alerta quando Redis falha.
- `Message.processing_status` vira `processed` depois do roteamento, mas mensagens outbound nao parecem ser persistidas no banco, apenas no Chatwoot bridge.
- `Conversation.outcome` nao parece ser fechado consistentemente quando estado conclui.
- Comandos internos buscam paciente por nome com `ilike`, podendo pegar o contato errado em nomes comuns.
- Scheduler de confirmacao e lembrete esta ativo, apesar de comentario em `remarketing.py` dizer que seria necessario descomentar jobs. Documentacao e codigo estao divergentes.
- `APP_VERSION`/`GIT_SHA` nao esta definido no container; `/health` mostra `version="unknown"` na VPS.
- `.env.example` ainda cita `OPENAI_API_KEY` para Whisper, mas o codigo atual usa Gemini para audio.

## Quadro atualizado do projeto

### Objetivo do agente

Ana e um backend FastAPI para atendimento via WhatsApp da nutricionista Thaynara Teixeira. O foco e agendamento, remarcacao, cancelamento, pagamento, envio de materiais, remarketing e escalacao de duvidas clinicas para humano.

### Arquitetura de producao

```text
WhatsApp / Meta Cloud API
  -> Nginx HTTPS
  -> FastAPI app/main.py
  -> app/webhook.py
      - valida assinatura
      - encaminha payload ao Chatwoot
      - debounce e dedup via Redis
      - rate limit por phone_hash
      - trata audio, midia, botoes e comandos internos
      - persiste inbound no PostgreSQL
  -> app/router.py
      - respeita handoff humano do Chatwoot
      - carrega Contact
      - reconhece retorno
      - chama ConversationEngine
      - envia textos, botoes, listas e midias pela Meta
      - atualiza stage/tags e remarketing
  -> app/conversation/engine.py
      - load state
      - interpreter
      - planner
      - tools
      - responder
      - save state e metrics
```

### Componentes principais

- `app/main.py`: cria FastAPI, valida envs, inicializa Redis state, scheduler, health, dashboard e privacy.
- `app/webhook.py`: entrada de Meta e Chatwoot, dedup, debounce, processamento de midia e comandos.
- `app/router.py`: cola entre engine e Meta API.
- `app/conversation/interpreter.py`: extrai intent e dados do turno, com heuristicas antes/depois do LLM.
- `app/conversation/planner.py`: decide a proxima action/tool; overrides deterministicos primeiro, LLM quando necessario.
- `app/conversation/responder.py`: transforma plano/tool em mensagens finais seguras.
- `app/conversation/state.py`: estado operacional por `phone_hash` em Redis, fallback in-memory.
- `app/tools/scheduling.py`: slots, agendamento, remarcacao e cancelamento via Dietbox.
- `app/tools/patients.py`: busca paciente e classificacao de remarcacao/retorno.
- `app/tools/payments.py`: link de cartao e confirmacao financeira.
- `app/escalation.py`: escalacao humana, resposta do Breno e FAQ aprendido.
- `app/remarketing.py`: filas de recontato, confirmacao de presenca e lembretes.
- `app/meta_api.py`: cliente Meta Cloud API.
- `app/chatwoot_bridge.py`: relay para Chatwoot e controle de handoff humano.

### Persistencia

- Redis:
  - `conv_state:{phone_hash}`: estado da conversa.
  - `dedup:msg:{meta_id}`: deduplicacao.
  - `debounce:*`: agrupamento de mensagens proximas.
  - `cmd_pending:{phone_hash}`: resposta pendente a comando interno.
  - `rate:whatsapp:*`: rate limit.
  - `errors:turn:{phone_hash}`: erros consecutivos.
  - `handoff:*`/Chatwoot: pausa humana.
- PostgreSQL:
  - `contacts`: perfil duravel e stage.
  - `conversations`: conversa aberta/fechada.
  - `messages`: inbound processado e retry.
  - `remarketing_queue`: fila de recontato.
  - `pending_escalations`: duvidas aguardando humano.
- Arquivos:
  - `knowledge_base/*.json`: FAQ, objecoes, remarketing, aprendizado.
  - `docs/`: PDFs e imagens enviados via WhatsApp.
  - `logs/metrics.jsonl`: metricas por turno.

### Fluxos de negocio

1. Novo agendamento:
   - Coleta nome/status, objetivo, plano, modalidade, preferencia de horario, slot, pagamento e dados cadastrais.
   - Envia midia kit/planos.
   - Agenda no Dietbox apos pagamento confirmado.
2. Remarcacao:
   - Detecta paciente e consulta ativa.
   - Aplica regra de retorno em ate 90 dias quando aplicavel.
   - Oferece slots, permite segunda rodada e executa `remarcar_dietbox`.
3. Cancelamento:
   - Pergunta motivo quando necessario.
   - Cancela no Dietbox e agenda follow-up quando aplicavel.
4. Pagamento:
   - PIX: aguarda comprovante e analisa imagem.
   - Cartao: gera link e depois confirma no Dietbox.
   - Valor divergente menor que o sinal esperado deve pedir novo comprovante.
5. Duvida clinica:
   - Nao responde orientacao nutricional.
   - Escala para humano, cria `PendingEscalation` e repassa resposta ao paciente.
6. Chatwoot/handoff:
   - Mensagens Meta sao relayed ao Chatwoot.
   - Eventos Chatwoot podem pausar/retomar Ana por telefone.
7. Remarketing:
   - Agenda recontatos situacionais apos preco, info, link de pagamento e cancelamento.
   - Dispatcher roda a cada minuto.
   - Confirmacao semanal e lembrete de vespera estao ativos no scheduler.

### Regras criticas

- Nao expor numero interno do Breno/Thaynara para pacientes.
- Nao responder duvida clinica como orientacao nutricional.
- Nao inventar horarios, links, chaves PIX, politicas ou confirmacoes.
- Nao atender gestantes e menores de 16 anos.
- Nao oferecer slot do dia atual.
- Respeitar janela de remarcacao/retorno.
- Pausar Ana quando houver handoff humano ativo no Chatwoot.
- Deduplicar mensagem antes de trabalho caro.
- Sanitizar input antes de LLM e limitar historico enviado.

### Plano recomendado

Primeira semana:
- Corrigir relay de resposta interna do Breno.
- Padronizar envs Meta/WhatsApp.
- Corrigir paths de midia com acento.
- Proteger ou desativar rotas de teste em producao.
- Ajustar/remover testes legados que quebram `pytest -q`.

Segunda semana:
- Separar compose de producao.
- Remover/arquivar modulos legados (`app/state.py`, `app/scheduling.py`, fluxos antigos).
- Adicionar teste de existencia de midias e teste de env aliases.
- Versionar `APP_VERSION/GIT_SHA` no deploy.

Terceira semana:
- Centralizar clientes Redis/HTTP/Gemini.
- Adicionar metricas de custo/LLM por etapa.
- Expandir overrides deterministicos para reduzir chamadas LLM.
- Criar dashboard operacional com handoff, falhas por integracao e funil.

