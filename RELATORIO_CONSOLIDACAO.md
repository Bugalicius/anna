# Relatório de Consolidação VPS - Ana v2.2

Data: 2026-05-13

## Diagnóstico Inicial

- `/root/agente` existia na branch `main`, com worktree suja e arquivos modificados.
- `/root/agente-v21` estava no commit `ca9d293` e era a pasta realmente usada pelo container `agente-app-1`.
- O container ativo tinha label `com.docker.compose.project.working_dir=/root/agente-v21`.
- A porta exposta era `8000`; não havia serviço escutando em `80` ou `443`.

## Consolidação Executada

- Parei o projeto Docker ativo a partir de `/root/agente-v21`.
- Preservei a pasta antiga suja como `/root/agente-OLD-v1-backup-20260513-061057`.
- Preservei a pasta v2.1 como `/root/agente-v21-backup-20260513-061057`.
- Clonei a branch `refactor/agente-inteligente` limpa em `/root/agente`.
- Copiei o `.env` preservado do backup v2.1 para `/root/agente/.env`.
- Subi o app com `docker compose -p agente up --build -d app`.

## Estado Final VPS

- Pasta definitiva: `/root/agente`.
- Projeto Compose: `agente`.
- Container app: `agente-app-1`.
- Versão em produção após deploy final: `abf8350`.
- Redis: healthy.
- Postgres: healthy.
- Scheduler: iniciado, com jobs `confirmacao_semanal`, `lembrete_vespera` e `followup_check`.
- `GEMINI_API_KEY`: presente no container.

## Validações

- `/test/chat` respondeu normalmente via `localhost:8000`.
- `/webhook` retornou `200 {"status":"ok"}` com payload assinado por `META_APP_SECRET`.
- `docker inspect` confirmou working dir do container em `/root/agente`.
- `docker compose ls` aponta a configuração para `/root/agente/docker-compose.yml`.

## Observação Importante

O VPS não está escutando em `80` ou `443`. A aplicação está acessível em HTTP na porta `8000`.
O endpoint `/webhook` está funcional no app, mas a URL HTTPS pública `https://anna.vps-kinghost.net`
não aceitou conexão durante o stress. Se a Meta estiver configurada para HTTPS sem porta/proxy,
é necessário ativar proxy/TLS ou confirmar a URL de callback cadastrada.
