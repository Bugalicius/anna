# Bloqueios e Limitações Encontradas

Data: 2026-05-13

## Não Bloqueantes

- `tests/test_test_chat.py` mantém 2 falhas antigas em endpoint/debug de test chat. A suite final ficou em 623 passing / 625 executados, com essas 2 falhas conhecidas.
- Os arquivos citados como `data/...` no prompt estão neste checkout em caminhos diferentes: `conversas_export.json` fica na raiz e FAQ/objeções ficam em `knowledge_base/`.
- As pastas antigas do VPS foram preservadas por segurança, sem remoção: `/root/agente-OLD-v1-backup-20260513-061057` e `/root/agente-v21-backup-20260513-061057`.

## Atenção Operacional

- O container definitivo roda em `/root/agente`.
- Resolvido em 2026-05-13: o serviço `nginx` do Docker Compose foi reativado e agora escuta em `:80` e `:443`, encaminhando `https://anna.vps-kinghost.net/webhook` para o app em `app:8000`.
- Simulações assinadas do webhook Meta retornaram 200 via HTTPS público. Como os testes usam número fictício, as respostas outbound ao paciente fake recebem status Meta `131047` (janela de 24h fechada), esperado para esse tipo de simulação e não indicativo de falha do recebimento do webhook.
