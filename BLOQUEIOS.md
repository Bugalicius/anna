# Bloqueios e Limitações Encontradas

Data: 2026-05-13

## Não Bloqueantes

- `tests/test_test_chat.py` mantém 2 falhas antigas em endpoint/debug de test chat. A suite final ficou em 623 passing / 625 executados, com essas 2 falhas conhecidas.
- Os arquivos citados como `data/...` no prompt estão neste checkout em caminhos diferentes: `conversas_export.json` fica na raiz e FAQ/objeções ficam em `knowledge_base/`.
- As pastas antigas do VPS foram preservadas por segurança, sem remoção: `/root/agente-OLD-v1-backup-20260513-061057` e `/root/agente-v21-backup-20260513-061057`.

## Atenção Operacional

- O container definitivo roda em `/root/agente` e expõe HTTP em `:8000`.
- O VPS não tem serviço escutando em `:80` ou `:443` no momento da validação. O `/webhook` respondeu 200 com assinatura válida via `localhost:8000`; a URL pública HTTPS `https://anna.vps-kinghost.net` não aceitou conexão no stress. Se a Meta estiver configurada para HTTPS sem porta/proxy, precisa ajustar proxy/TLS ou confirmar a URL cadastrada.
