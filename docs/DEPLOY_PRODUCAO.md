# Deploy de producao

O `docker-compose.yml` atual continua disponivel para desenvolvimento/local.

Para producao, use `docker-compose.prod.yml`:

```bash
docker compose -f docker-compose.prod.yml up --build -d
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs app --tail=100
```

Diferenças do compose de producao:

- nao monta `./app` nem `./tests` como bind mount;
- nao expoe Postgres nem Redis no host;
- mantem somente volumes de dados, certificados, `knowledge_base` e `docs`;
- usa `restart: unless-stopped`.

Antes de trocar a VPS para este compose, confirme se o `.env` esta completo e se o fluxo atual de certificados/nginx e volumes bate com o servidor.
