# Relatorio de Monitoramento - Ana

## Visao geral

Foi criado o servico `monitor`, executado por Docker Compose com o comando:

```bash
python -m app.monitor.main
```

O loop roda a cada `MONITOR_INTERVAL_SECONDS` segundos, executa checks em paralelo, grava historico em `logs/monitor/YYYY-MM-DD.jsonl` e envia alertas WhatsApp para `MONITOR_ALERTS_TO` quando uma condicao critica ou de alerta falha.

## Checks implementados

Total: 32 checks ativos.

### Infraestrutura

- `infra.app_container`: container `app` em execucao.
- `infra.redis_container`: container `redis` em execucao.
- `infra.postgres_container`: container `postgres` em execucao.
- `infra.nginx_container`: container `nginx` em execucao.
- `infra.health_endpoint`: endpoint `/health` com HTTP 200.
- `infra.redis_ping`: Redis responde PING.
- `infra.postgres_ping`: Postgres responde `SELECT 1`.

### Integracoes

- `integrations.gemini_env`: `GEMINI_API_KEY` configurada.
- `integrations.meta_env`: credenciais Meta configuradas.
- `integrations.gemini`: chamada curta na Gemini API.
- `integrations.dietbox`: GET leve no Dietbox usando somente token em cache valido.
- `integrations.meta_api`: token Meta valido no Graph API.

### Saude da aplicacao

- `app.memory_usage`: memoria do container `app` abaixo de 80%.
- `app.cpu_usage`: CPU do container `app` abaixo de 80%.
- `app.disk_usage`: disco do VPS abaixo de 85%.
- `app.nginx_500`: sem HTTP 500 recentes no Nginx.
- `app.health_latency`: latencia do `/health` abaixo de 2s.

### Comportamento

- `behavior.turn_error_rate`: erro em `processar_turno` abaixo de 5%.
- `behavior.turn_latency_p95`: p95 de turno abaixo de 5s.
- `behavior.state_loop`: sem estado preso por mais de 5 turnos.
- `behavior.zero_messages`: volume nao zerado em horario ativo.
- `behavior.fallback_loop`: sem loop de fallback recente.

### Negocio

- `business.conversions_vs_avg`: conversoes das ultimas 24h contra media historica.
- `business.payment_abandonment`: abandono no fluxo de pagamento abaixo de 50%.
- `business.cancellation_rate`: cancelamentos abaixo de 30% dos agendamentos do dia.
- `business.escalations_volume`: menos de 10 escalacoes em 1h.
- `business.open_payments`: pagamentos abertos antigos sob controle.

### Seguranca e anomalias

- `anomaly.b2b_attempts`: volume incomum de B2B.
- `anomaly.restrictions_today`: menor de 16 anos ou gestante detectado hoje.
- `anomaly.same_phone_spam`: menos de 50 mensagens do mesmo telefone em 5min.
- `anomaly.error_words`: sem `ERROR`, `CRITICAL` ou `Exception` recentes nos logs.
- `anomaly.retrying_messages`: sem volume alto de mensagens em retry/falha.

## Severidade

- `critical`: envia WhatsApp imediatamente, com dedup de `MONITOR_CRITICAL_DEDUP_MINUTES`.
- `alert`: envia WhatsApp, com dedup de `MONITOR_ALERT_DEDUP_MINUTES`.
- `warning`: grava em log, nao envia WhatsApp.
- `info`: grava em log, nao envia WhatsApp.

## Deduplicacao e resolucao

O estado de incidente fica em Redis:

- `monitor:state:{check_id}` guarda `since`, `last_seen`, `last_sent`, severidade e nome.
- Se a mesma condicao persistir, o monitor envia no maximo um status a cada `MONITOR_STATUS_UPDATE_MINUTES`.
- Quando um check volta para OK, o monitor envia uma mensagem unica de resolucao com duracao do incidente.
- Se Redis estiver indisponivel, o monitor usa memoria local temporaria para nao perder dedup durante o loop em execucao.

## Dry-run

Para ensaiar sem enviar WhatsApp:

```bash
MONITOR_DRY_RUN=true docker compose run --rm monitor python -m app.monitor.main --once
```

Para rodar um unico check:

```bash
docker compose run --rm monitor python -m app.monitor.main --once --check infra.redis_container
```

## Como adicionar um check

1. Criar uma funcao async em `app/monitor/checks/<categoria>.py` retornando `CheckResult`.
2. Envolver a funcao com `guarded_check(...)` para timeout e erro controlado.
3. Adicionar a funcao na lista `CHECKS` do modulo.
4. Criar ou atualizar teste em `tests/conversation_v2/monitor/`.
5. Validar com `python -m app.monitor.main --once --check <check_id>`.

