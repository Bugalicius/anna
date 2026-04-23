---
id: "260417-busca-paciente-nome"
status: complete
---

# Busca de paciente por nome (fallback)

## Alterações

### `app/agents/dietbox_worker.py`
- Nova função `buscar_paciente_por_nome(nome)` — busca na API Dietbox por nome
  com comparação case-insensitive e sem acentos (normalização NFD)
- Retorna `dict | None` com mesma estrutura de `buscar_paciente_por_telefone`
- Proteção: nome < 3 caracteres retorna None sem chamar API

### `app/agents/retencao.py`
- Import de `buscar_paciente_por_nome`
- `_detectar_tipo_remarcacao()`: se `buscar_paciente_por_telefone` retorna None
  e `self.nome` está disponível, tenta `buscar_paciente_por_nome` como fallback
- Log informativo quando o fallback é ativado

### Testes (8 novos)
- `test_dietbox_worker.py`: 5 testes para `buscar_paciente_por_nome`
  (match, sem acento, não encontrado, nome curto, exceção)
- `test_retencao.py`: 3 testes para o fallback
  (fallback encontra, sem nome não tenta, ambos None = nova_consulta)

## Resultado
261 testes passaram, 0 falharam.
