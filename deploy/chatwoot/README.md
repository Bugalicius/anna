# Chatwoot na VPS com Docker

Este pacote sobe o Chatwoot em producao com:

- `rails` e `sidekiq`
- `postgres` local
- `redis` local com senha
- `caddy` como proxy reverso com HTTPS automatico

## 1. Pre-requisitos da VPS

Use Ubuntu/Debian com DNS do dominio apontando para o IP da VPS.

Instale Docker e Compose:

```bash
apt-get update && apt-get upgrade -y
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
apt-get install -y docker-compose-plugin
```

## 2. Copiar os arquivos

Copie a pasta `deploy/chatwoot` para a VPS, por exemplo em `/opt/chatwoot`:

```bash
mkdir -p /opt/chatwoot
```

## 3. Criar o `.env`

```bash
cd /opt/chatwoot
cp .env.example .env
```

Edite o `.env` e ajuste no minimo:

- `CHATWOOT_DOMAIN`
- `LETSENCRYPT_EMAIL`
- `FRONTEND_URL`
- `SECRET_KEY_BASE`
- `ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY`
- `ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY`
- `ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT`
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `REDIS_URL`
- `MAILER_SENDER_EMAIL`

Geracao rapida dos segredos:

```bash
openssl rand -hex 64
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

## 4. Preparar o banco e subir

```bash
docker compose pull
docker compose run --rm rails bundle exec rails db:chatwoot_prepare
docker compose up -d
```

## 5. Acesso via navegador

Abra:

```text
https://SEU_DOMINIO
```

O Caddy emite e renova o certificado TLS automaticamente. Se o dominio ainda nao estiver apontado corretamente para a VPS, o HTTPS nao vai subir.

## 6. WhatsApp Cloud API da Meta

Se sua API oficial da Meta ja esta funcionando, use o fluxo manual do Chatwoot:

1. Entre no Chatwoot no navegador.
2. Acesse `Settings -> Inboxes -> Add Inbox -> WhatsApp`.
3. Escolha `Manual setup`.
4. Informe no Chatwoot:
   - `WHATSAPP_CLOUD_API_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `WHATSAPP_BUSINESS_ACCOUNT_ID`
5. O Chatwoot vai gerar:
   - `WHATSAPP_WEBHOOK_URL`
   - `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
6. Cole esses dois valores no painel da Meta em `WhatsApp -> Configuration -> Webhook`.

Observacao importante: no fluxo manual, o webhook nao fica pronto antes da criacao da inbox, porque ele e gerado pelo proprio Chatwoot.

## 7. Webhook esperado

Depois que a inbox for criada, o callback fica no formato:

```text
https://SEU_DOMINIO/webhooks/whatsapp/{phone_number}
```

Use exatamente a URL e o token mostrados pelo Chatwoot, porque podem variar conforme a inbox.

## 8. Comandos uteis

Ver logs:

```bash
docker compose logs -f rails
docker compose logs -f sidekiq
docker compose logs -f caddy
```

Atualizar Chatwoot:

```bash
docker compose pull
docker compose run --rm rails bundle exec rails db:chatwoot_prepare
docker compose up -d
```

## 9. Referencias oficiais

- Docker self-hosted: https://developers.chatwoot.com/self-hosted/deployment/docker
- Environment variables: https://developers.chatwoot.com/self-hosted/configuration/environment-variables
- WhatsApp Cloud manual: https://www.chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow
