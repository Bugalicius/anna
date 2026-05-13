# Bloqueios e Limitações Encontradas

Data: 2026-05-13

## Não Bloqueantes

- `GEMINI_API_KEY` não está presente no ambiente local; por isso o stress test foi executado em modo local mockado, sem Gemini real.
- `docker compose ps` não mostrou serviços locais ativos. Os logs de `app` disponíveis eram antigos, de 2026-05-02.
- `tests/test_test_chat.py` mantém 2 falhas em endpoint/debug de test chat, compatíveis com a exceção citada no prompt.
- Os arquivos citados como `data/...` no prompt estão neste checkout em caminhos diferentes: `conversas_export.json` fica na raiz e FAQ/objeções ficam em `knowledge_base/`.

