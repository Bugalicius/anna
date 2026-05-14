# Relatório de Hardening - Agente Ana v2.1

Data: 2026-05-13  
Branch: `refactor/agente-inteligente`

## Resultado

- Testes totais: 623 executados na suíte completa (`621 passed`, `2 skipped`, `1 xfailed`, `2 failed` preexistentes em `tests/test_test_chat.py`).
- Testes críticos v2/R1-R16/extremos: `170 passed`.
- Cenários adversariais novos: 116.
- Regras invioláveis: 16/16 implementadas e cobertas por testes específicos.
- Replay de conversas reais: 1.063 conversas elegíveis, 4.751 turnos, 4.748 aceitos, score 99,94/100.
- Stress local mockado: 100 conversas simultâneas, 238 turnos, 0 erros, p95 0,74ms.
- Deploy VPS: executado em worktree separada `/root/agente-v21` no commit final `2360bb8`, container `agente-app-1` iniciado sem erro.
- Smoke tests pós-deploy via `/test/chat`: 10/10 OK.

## Melhorias Implementadas

1. Compatibilidade de estado v2:
   - `app/conversation/state.py` concentra a implementação persistente de estado usada pelo v2.
   - Desbloqueou a suíte adversarial v2 existente.

2. Agressão e ameaça:
   - Adicionado interceptador global em `orchestrator.py`.
   - Primeira agressão recebe resposta profissional curta.
   - Segunda agressão escala silenciosamente para a equipe.
   - Incidentes são registrados em `logs/agressoes.jsonl`.
   - Resposta ao paciente nunca expõe nome/número interno do Breno.

3. Gestante e menor de 16 em texto livre:
   - Adicionado interceptador global para mensagens como “minha filha de 12 anos” e “estou grávida”.
   - Gestante com dúvida clínica escala silenciosamente.
   - Menor de 16 recebe recusa direta sem exceções.

4. Regras invioláveis reforçadas:
   - R4 agora normaliza acentos em dias da semana, corrigindo `terça`.
   - R6 não aceita mais centavo abaixo do sinal mínimo de 50%.

5. Testes extremos:
   - Criado `tests/conversation_v2/e2e/test_situacoes_extremas.py`.
   - Cobre agressão, ameaça, manipulação, gestante, menor, mídia rara, texto gigante, emoji, idioma estrangeiro, serviço inexistente e pagamentos inválidos.

6. Análise e replay:
   - Criado `scripts/analisar_conversas_completo.py`.
   - Atualizado `tests/conversation_v2/e2e/runner.py` com CLI, batch e export JSON.
   - Criado `scripts/stress_test_real.py`.

## Conversas Reais

O export real disponível está na raiz como `conversas_export.json` e contém:

- 1.283 conversas.
- 20.386 mensagens.
- 105 conversas com agressão/ameaça.
- 41 conversas com menção a gestante.
- 24 conversas com manipulação/negociação.
- 1 conversa com menor de 16 detectável por texto.

Relatório gerado: `CONVERSAS_PROBLEMATICAS.md`.

## Validação Executada

```bash
python scripts/validar_yamls.py
pytest tests/conversation_v2/e2e/test_situacoes_extremas.py -q --tb=short
pytest tests/conversation_v2/test_rules.py tests/conversation_v2/test_output_validator.py tests/conversation_v2/e2e/test_regras_adversariais.py tests/conversation_v2/e2e/test_situacoes_extremas.py -q --tb=short
python scripts/analisar_conversas_completo.py --top 50
python tests/conversation_v2/e2e/runner.py --batch-size 100 --output relatorio_replay.json
python scripts/stress_test_real.py --conversas 100 --paralelo 20 --output stress_test_real_result.json
pytest tests/ -q --tb=short
```

## Pendências Não Bloqueantes

- `tests/test_test_chat.py` mantém 2 falhas já descritas como não críticas/debug.
- Docker local não está rodando (`docker compose ps` não listou serviços ativos); logs disponíveis eram antigos.
- Stress com Gemini real não foi executado porque `GEMINI_API_KEY` não está presente no ambiente local.
- A pasta principal do VPS `/root/agente` está em `main` com worktree suja; para preservar mudanças locais, o deploy final foi feito por `/root/agente-v21` usando o projeto Docker `agente`.
- `/health` em produção retornou `status=ok` para Redis e Postgres. O campo `version` aparece `unknown` porque o build em git worktree tem `.git` como arquivo.

## Métricas Finais

| Métrica | Resultado |
|---|---:|
| Testes completos passando | 621 |
| Falhas completas | 2 preexistentes/debug |
| Testes críticos v2 | 170/170 |
| Cenários adversariais novos | 116 |
| Cobertura R1-R16 | 16/16 |
| Replay score | 99,94/100 |
| Replay turnos aceitos | 4.748/4.751 |
| Stress erro | 0% |
| Stress p95 local mockado | 0,74ms |
| Deploy VPS | OK |
| Smoke pós-deploy | 10/10 |
