# Deploy de producao

O `docker-compose.yml` atual continua disponivel para desenvolvimento/local e
para o deploy atual da VPS. Ele nao publica Postgres nem Redis no host; estes
servicos devem ficar acessiveis apenas pela rede interna do Docker.

O `docker-compose.prod.yml` e o alvo de producao endurecido, mas deve ser
ativado em janela controlada depois de validar o compose atual sem portas
publicas de banco/cache.

## Diferencas do compose de producao

- nao monta `./app` nem `./tests` como bind mount;
- nao expoe Postgres nem Redis no host;
- mantem somente volumes de dados, certificados, `knowledge_base` e `docs`;
- usa `restart: unless-stopped`;
- grava o SHA curto do Git em `/app/.app_version` durante o build; o endpoint
  `/health` usa esse valor quando `APP_VERSION`, `GIT_SHA` ou `RELEASE_SHA`
  nao estiverem definidos.

## Fase 0 - pre-check na VPS

Antes de qualquer troca, registre o estado atual:

```bash
cd /root/agente
git status
git log --oneline -5
docker compose ps
docker compose logs app --tail=100
curl -s https://anna.vps-kinghost.net/health
docker compose config --quiet
docker compose -f docker-compose.prod.yml config --quiet
```

Se `git status` mostrar alteracoes locais na VPS, nao sobrescreva. Registre o
diff e escolha uma acao segura: commit local, stash ou abortar a atualizacao.

## Fase 1 - aplicar compose atual sem portas publicas

Depois do `git pull`, aplique primeiro o compose atual, mantendo o fluxo de
deploy ja usado na VPS:

```bash
cd /root/agente
git pull origin main
docker compose up -d postgres redis app nginx
docker compose ps
docker port agente-postgres-1
docker port agente-redis-1
curl -s https://anna.vps-kinghost.net/health
docker compose logs app --tail=100
```

Os comandos `docker port agente-postgres-1` e `docker port agente-redis-1`
devem retornar vazio. Isso confirma que Postgres e Redis nao estao publicados
no host.

Rollback da fase 1:

```bash
cd /root/agente
git revert <commit-da-remocao-das-portas>
docker compose up -d postgres redis app nginx
```

## Fase 2 - migrar para docker-compose.prod.yml

Execute esta fase em janela dedicada, depois de confirmar que a fase 1 ficou
estavel:

```bash
cd /root/agente
git status
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs app --tail=100
curl -s https://anna.vps-kinghost.net/health
```

Rollback da fase 2:

```bash
cd /root/agente
docker compose up --build -d app nginx postgres redis
docker compose ps
curl -s https://anna.vps-kinghost.net/health
```

Antes de trocar a VPS para o compose de producao, confirme se o `.env` esta
completo e se o fluxo atual de certificados/nginx e volumes bate com o
servidor.
