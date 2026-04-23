---
id: "260417-busca-paciente-nome"
description: "Adicionar buscar_paciente_por_nome no dietbox_worker e usar como fallback no retencao"
status: planning
created: "2026-04-17"
---

# Quick Task: Busca de paciente por nome (fallback)

## Problema
O `retencao.py:_detectar_tipo_remarcacao()` só busca paciente por telefone.
Se o paciente trocou de número, não é encontrado e cai em "nova_consulta",
perdendo o direito de remarcação gratuita.

## Tarefas

### T1: Adicionar `buscar_paciente_por_nome()` em `dietbox_worker.py`
- Endpoint: `GET /v2/patients?Search={nome}&Take=5`
- Retorna `dict | None` com `{id, nome, email, telefone}`
- Mesma estrutura de retorno do `buscar_paciente_por_telefone`
- Compara nome normalizado (case-insensitive, sem acentos) para match

### T2: Usar fallback no `retencao.py:_detectar_tipo_remarcacao()`
- Se `buscar_paciente_por_telefone` retorna None e `self.nome` está disponível
- Chamar `buscar_paciente_por_nome(self.nome)` como fallback
- Log da situação: "Paciente não encontrado por telefone, buscando por nome"

### T3: Testes
- Testar `buscar_paciente_por_nome` com match e sem match
- Testar fallback no `_detectar_tipo_remarcacao`

## Arquivos
- `app/agents/dietbox_worker.py` — nova função
- `app/agents/retencao.py` — fallback em `_detectar_tipo_remarcacao`
- `tests/test_dietbox_worker.py` ou `tests/test_retencao.py` — testes
