# Relatório de Stress de Agendamento - Ana v2.2

Data: 2026-05-13

## Objetivo

Validar conversas de agendamento com paciente exigente, recusando ofertas de horário em sequência, sem violar a grade e sem travar o estado.

## Melhorias Implementadas

- Fallback determinístico no `interpreter` para estados de coleta crítica do agendamento.
- Normalização sem acento no `state_machine`, evitando divergência entre `sábado` e `sabado`.
- Escalação silenciosa após preferências de horário inviáveis repetidas.
- Escalação silenciosa após rejeição excessiva de rodadas de slots.
- Tratamento de resposta de modalidade durante upsell.
- Cache curto de 60s para consulta bruta de slots do Dietbox, mantendo filtro por preferência e exclusões por conversa.
- `/test/chat` sem `typing_delay` artificial e sem log Chatwoot, apenas para stress/debug; WhatsApp real mantém o delay humano.

## Stress Local com Chave Gemini Presente

Comando:

```bash
python scripts/stress_test_agendamento_real.py --mock-tools --output resultado_stress_agendamento_gemini_real.json
```

Resultado:

- Cenários complexos: 5/5 passando.
- Erros: 0.
- Escalações esperadas: 1.
- p95 global: 2,40 ms.
- Observação: alguns turnos ambíguos acionaram Gemini real; os estados críticos de agendamento ficaram protegidos por heurística determinística.

## Stress Direto no Container VPS

Comando:

```bash
docker compose -p agente exec -T app python scripts/stress_test_agendamento_real.py --output /tmp/resultado_stress_agendamento_real_prod.json
```

Resultado:

- Cenários complexos: 5/5 passando.
- Erros: 0.
- Escalações esperadas: 1.
- p95 global: 2202 ms.
- Observação: houve um outlier de 42s em uma consulta real de slots antes da otimização/cache; o cenário ainda passou, mas o gargalo foi registrado.

## Stress 50 Agendamentos Paralelos

Comando:

```bash
python scripts/stress_test_50_agendamentos_paralelos.py --conversas 50 --paralelo 10 --mock-tools
```

Resultado local:

- Conversas: 50.
- Taxa de sucesso: 100%.
- Erros: 0.
- p50: 0,59 ms.
- p95: 0,79 ms.
- p99: 1,03 ms.

Resultado no VPS:

- Conversas: 50.
- Taxa de sucesso: 100%.
- Erros: 0.
- p50: 0,45 ms.
- p95: 0,71 ms.
- p99: 0,92 ms.

## Stress HTTP Público

Comando final:

```bash
python scripts/stress_test_via_test_chat.py --target http://anna.vps-kinghost.net:8000 --conversas 30 --paralelo 5 --cenario agendamento_dificil
```

Resultado final:

- Conversas: 30.
- Turnos: 330.
- Erros HTTP 500: 0.
- Respostas vazias: 0.
- Taxa de sucesso: 100%.
- Latência média: 259,01 ms.
- p50: 35,95 ms.
- p95: 1047,66 ms.
- p99: 1460,12 ms.

## Suite Final

Comando:

```bash
pytest tests/ -q --tb=short
```

Resultado:

- 623 passed.
- 2 failed, ambos pré-existentes em `tests/test_test_chat.py`.
- 2 skipped.
- 1 xfailed.

## Conclusão

O fluxo de agendamento suportou recusas repetidas, mudanças de ideia, agressão no meio do fluxo e paciente inviável com escalação. A versão final manteve a grade protegida, não repetiu slots rejeitados no stress mockado e não gerou exceções nos testes concorrentes.
