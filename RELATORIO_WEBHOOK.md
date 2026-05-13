# Relatório - Diagnóstico Webhook

Data: 2026-05-13

## Estado Encontrado

- Cenário identificado: B inicialmente, corrigido durante a execução.
- Problema: o `docker-compose.yml` já tinha serviço `nginx` com portas `80` e `443`, certificados Let's Encrypt e proxy para `app:8000`, mas o deploy anterior havia subido apenas `app`. Com isso, `https://anna.vps-kinghost.net` recusava conexão.
- Estado final: webhook público HTTPS ativo via Nginx em Docker.
- URL pública validada: `https://anna.vps-kinghost.net/webhook`.
- TLS: sim, terminado no container `agente-nginx-1`, usando certificados do volume `agente_certbot_conf`.

## Configuração Atual

- Nginx host: não instalado/ativo fora do Docker.
- Cloudflare Tunnel: não encontrado.
- Traefik/Caddy: não encontrados.
- Docker Compose:
  - `agente-nginx-1`: `0.0.0.0:80->80`, `0.0.0.0:443->443`.
  - `agente-app-1`: `0.0.0.0:8000->8000`.
  - `agente-postgres-1`: healthy.
  - `agente-redis-1`: healthy.
- Nginx:
  - `anna.vps-kinghost.net`: HTTP redireciona para HTTPS; HTTPS proxia `/webhook` e demais rotas para `http://app:8000`.
  - `chat.anna.vps-kinghost.net`: HTTPS proxia `/webhooks/whatsapp/` para o app e o restante para Chatwoot.
  - Access log ajustado para não registrar query string de verificação.
- Firewall/NAT:
  - Docker NAT publicando `80`, `443`, `8000` e `3000`.

## Validação

- DNS: `anna.vps-kinghost.net` resolve para `187.45.255.62`.
- Antes da correção:
  - `https://anna.vps-kinghost.net/health`: conexão recusada.
  - `http://anna.vps-kinghost.net/health`: conexão recusada.
  - `http://anna.vps-kinghost.net:8000/health`: 200 OK.
- Depois da correção:
  - `https://anna.vps-kinghost.net/health`: 200 OK, `status=ok`, Redis OK, Postgres OK.
  - `http://anna.vps-kinghost.net/health`: 301 para HTTPS.
  - GET de verificação Meta com token correto: retornou o challenge.
  - POST assinado inicial para `/webhook`: 200 OK.
  - 10 POSTs assinados por 10 minutos: 10/10 retornaram 200 OK.
  - Latência média dos 10 POSTs: 892,07 ms.
  - Latência máxima dos 10 POSTs: 1298,95 ms.

Evidências nos logs:

- Nginx registrou POSTs públicos para `/webhook` com `200`.
- App registrou `WEBHOOK PAYLOAD` e `POST /webhook HTTP/1.1" 200 OK`.
- App executou rota de conversa para o telefone fake do teste.
- Meta enviou status callbacks reais para `/webhooks/whatsapp/+553171893255`, também com `200`.

Observação: como os testes usam um número fictício e não uma conversa real aberta pelo WhatsApp, as respostas outbound para esse número receberam status Meta `131047` (janela de 24h fechada). Isso é esperado nessa simulação e confirma que o app tentou responder; não indica falha do recebimento do webhook.

## Ações Tomadas

- Executei diagnóstico completo e salvei em `logs/diagnostico_webhook.log`.
- Validei configuração existente:
  - `docker compose -p agente run --rm --no-deps nginx nginx -t`
- Reativei o proxy existente:
  - `cd /root/agente && docker compose -p agente up -d nginx`
- Validei portas:
  - `ss -tlnp | grep -E ':80 |:443 |:8000 '`
- Criei `scripts/simular_webhook_meta.py` para POSTs assinados com `META_APP_SECRET`/`WHATSAPP_APP_SECRET`.
- Ajustei `docker-compose.yml` com `restart: unless-stopped` para app, nginx, Redis e Postgres.
- Atualizei `CLAUDE.md` para deploy subir `app nginx`.
- Ajustei `nginx/nginx.conf` para não registrar query string no access log.
- Recarreguei Nginx:
  - `docker compose -p agente exec -T nginx nginx -t`
  - `docker compose -p agente exec -T nginx nginx -s reload`

## Recomendações Futuras

- Conferir no Meta Developer Console se a URL cadastrada é `https://anna.vps-kinghost.net/webhook` ou o alias `https://anna.vps-kinghost.net/webhooks/whatsapp/+553171893255`.
- Remover exposição pública direta da porta `8000` depois de confirmar que Meta e testes operacionais usam apenas HTTPS via Nginx.
- Configurar monitoramento simples para `https://anna.vps-kinghost.net/health` e alerta se `agente-nginx-1` parar.
- Revisar renovação automática dos certificados Let's Encrypt no volume `agente_certbot_conf`.

## Bloqueios Encontrados

- Nenhum bloqueio crítico restante para recebimento público do webhook.
- Limitação de teste: POSTs simulados não abrem janela real de conversa na Meta; por isso o outbound para o número fake falha com erro esperado `131047`.
