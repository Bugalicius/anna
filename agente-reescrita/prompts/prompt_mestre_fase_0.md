# PROMPT MESTRE — Reescrita do Agente Ana
# Para: Claude Code (Sonnet)
# Visão geral + Fase 0

---

## CONTEXTO DA REESCRITA

O **Agente Ana** é um assistente WhatsApp para a nutricionista **Thaynara Teixeira**. A versão atual tem **5.576 linhas de código** distribuídas em módulos que viraram ingovernáveis (`planner.py` sozinho tem 1.702 linhas com 7 overrides determinísticos + LLM).

**Resultado:** bugs frequentes, estado corrompido, LLM tomando decisões que deveriam ser determinísticas, dificuldade de manutenção.

## DECISÃO ARQUITETURAL

Reescrita completa em **6 módulos** com arquitetura clara:

```
WhatsApp → webhook.py → router.py
                         │
                         ▼
              ┌──────── orchestrator.py ────────┐
              │                                 │
              │  1. Carrega contexto            │
              │  2. Interpreter (Gemini)        │
              │  3. State machine               │
              │  4. Rule engine (valida)        │
              │  5. Tools (executa ações)       │
              │  6. Response writer             │
              │  7. Output validator            │
              │  8. Persiste estado             │
              └─────────────┬───────────────────┘
                            │
                            ▼
                       Meta API → User
```

**Princípio central:**
> "LLM entende e conversa. Estado decide onde estamos. Regras decidem o que pode acontecer. Tools trazem dados reais. Validador impede resposta errada."

## TAMANHO ESPERADO

| Módulo | Atual | Novo |
|--------|-------|------|
| orchestrator.py | engine.py (425 linhas) | ~200 |
| state_machine.py | NÃO EXISTE | ~400 |
| rules.py | espalhado | ~300 |
| interpreter.py | 834 linhas | ~150 |
| response_writer.py | responder.py (1.047) | ~250 |
| tools/ (todos) | ~1.270 linhas | ~400 |
| **TOTAL** | **~5.576** | **~1.700** |

Redução de **70%** do código com comportamento mais confiável.

---

## ESTRUTURA DE ARQUIVOS DE CONFIGURAÇÃO

Você receberá os seguintes YAMLs declarativos com todas as regras:

```
config/
├── global.yaml                  # regras globais (planos, valores, números, etc)
├── fluxos/
│   ├── fluxo_1_agendamento.yaml
│   ├── fluxo_2_3_remarcacao_cancelamento.yaml
│   ├── fluxo_4_confirmacao_presenca.yaml
│   ├── fluxo_5_recebimento_imagem.yaml
│   ├── fluxo_6_7_duvidas_casos_especiais.yaml
│   ├── fluxo_8_comandos_internos.yaml
│   ├── fluxo_9_midias_nao_textuais.yaml
│   └── fluxo_10_fora_de_contexto.yaml
```

**Esses YAMLs são a fonte da verdade.** O código deve ser construído pra carregá-los e executar suas regras — não pra hardcodar lógica.

---

## FASES DA REESCRITA

A reescrita será feita em **10 fases sequenciais**:

| Fase | Foco | Tempo estimado |
|------|------|----------------|
| 0 | Setup, branch, backup, pausa do agente atual | 1 dia |
| 1 | Núcleo do sistema (módulos vazios + carregamento de YAMLs) | 2 dias |
| 2 | Tools e integrações com schemas | 2 dias |
| 3 | Fluxo 1 (Agendamento) completo | 2 dias |
| 4 | Fluxos 2 + 3 (Remarcação + Cancelamento) | 2 dias |
| 5 | Fluxos 4 + 5 (Confirmação presença + Imagens) | 1 dia |
| 6 | Fluxos 6 + 7 (Dúvidas + Casos especiais) | 1 dia |
| 7 | Fluxos 8 + 9 + 10 (Comandos + Mídias + Fora contexto) | 1 dia |
| 8 | Testes E2E e validação | 1 dia |
| 9 | Cutover (substituir agente antigo) | 1 dia |

**Total: ~14 dias úteis** (~3 semanas).

Cada fase tem **prompt próprio** que será enviado depois. **Não tente fazer fases adiantadas** — espera o prompt da fase específica.

---

## REGRAS DE COMPORTAMENTO DURANTE A IMPLEMENTAÇÃO

### O que VOCÊ DEVE fazer

1. **Ler os YAMLs antes de codar.** Os YAMLs são autoritários sobre todas as regras de negócio.

2. **Validação contínua.** A cada módulo novo, rodar testes locais ANTES de avançar.

3. **Logging estruturado.** Cada turno deve gerar uma entrada no `logs/metrics.jsonl` com:
   ```json
   {
     "timestamp": "...",
     "phone_hash": "...",
     "fluxo": "agendamento",
     "estado_antes": "aguardando_plano",
     "estado_depois": "aguardando_modalidade",
     "intent": "escolher_plano",
     "regra_aplicada": "R3_nunca_inventar_valor",
     "tools_chamadas": ["consultar_slots_dietbox"],
     "duracao_ms": 1234,
     "erro": null
   }
   ```

4. **Commits pequenos e frequentes.** Commit por módulo ou conjunto pequeno de funcionalidades.

5. **Branch separada.** Toda reescrita acontece na branch `refactor/agente-inteligente`. Não tocar na `main` até a Fase 9.

### O que VOCÊ NÃO DEVE fazer

1. **NÃO hardcoded regras de negócio no código.** Tudo vem dos YAMLs.

2. **NÃO criar novos overrides.** A arquitetura nova tem state machine + rule engine. Não voltar pro padrão antigo de overrides espalhados.

3. **NÃO fazer LLM tomar decisões de fluxo.** LLM só entende intent + redige resposta dentro do escopo.

4. **NÃO esquecer das regras invioláveis globais.** Cada resposta passa pelo output validator antes de sair.

5. **NÃO tocar no código do agente atual durante as fases 0-8.** Ele fica pausado. Só na Fase 9 que substitui.

---

## CONVENÇÕES DE CÓDIGO

```python
# Estrutura de cada módulo
"""
Módulo X — descrição
"""
from __future__ import annotations

import logging
from typing import ...

logger = logging.getLogger(__name__)

# Constantes
...

# Classes (Pydantic models pra schemas)
...

# Funções
...
```

**Type hints obrigatórios.**
**Pydantic pra schemas de input/output de tools.**
**Async/await onde fizer sentido (HTTP, DB).**
**Sem prints — só logging.**

---

## FERRAMENTAS DISPONÍVEIS

- **Python 3.11+**
- **FastAPI** (já no projeto)
- **Pydantic v2** (já no projeto)
- **Redis** via `redis.asyncio` (já no projeto)
- **PostgreSQL** via SQLAlchemy ou asyncpg (já no projeto)
- **APScheduler** (já no projeto — jobs de confirmação)
- **PyYAML** (instalar se não estiver — pra carregar YAMLs)
- **Gemini API** via `app/llm_client.py` (já no projeto)
- **Meta WhatsApp Cloud API** (já no projeto)
- **Dietbox API** (já no projeto)
- **Rede payment gateway** (já no projeto)

---

# ═════════════════════════════════════════════════════════════════════════
# FASE 0 — SETUP
# ═════════════════════════════════════════════════════════════════════════

## OBJETIVO

Preparar ambiente, criar branch, pausar agente atual, organizar YAMLs de configuração.

## TAREFAS DA FASE 0

### 0.1 — Pausar agente atual em produção

No VPS, para o container do app (mantém Redis e PostgreSQL rodando):

```bash
cd /root/agente
docker compose stop app
```

Confirma com `docker compose ps` que só `app` está parado.

### 0.2 — Criar branch da reescrita

Localmente (ou no VPS, onde estiver desenvolvendo):

```bash
cd /root/agente
git checkout main
git pull
git checkout -b refactor/agente-inteligente
```

Confirma `git status` limpo.

### 0.3 — Criar estrutura de pastas nova

```bash
mkdir -p app/conversation_v2/
mkdir -p app/conversation_v2/tools/
mkdir -p config/fluxos/
mkdir -p logs/
```

A pasta `conversation_v2/` vai conviver com a `conversation/` antiga até a Fase 9 (cutover).

### 0.4 — Copiar YAMLs para o projeto

Coloca os 8 arquivos YAML em `config/fluxos/`:

- `fluxo_1_agendamento.yaml`
- `fluxo_2_3_remarcacao_cancelamento.yaml`
- `fluxo_4_confirmacao_presenca.yaml`
- `fluxo_5_recebimento_imagem.yaml`
- `fluxo_6_7_duvidas_casos_especiais.yaml`
- `fluxo_8_comandos_internos.yaml`
- `fluxo_9_midias_nao_textuais.yaml`
- `fluxo_10_fora_de_contexto.yaml`

E o `config/global.yaml`.

### 0.5 — Validar YAMLs

Cria um script `scripts/validar_yamls.py` que:

```python
"""Valida sintaxe e estrutura dos YAMLs de configuração."""
import sys
from pathlib import Path
import yaml

CONFIG_DIR = Path("config")

def validate_yaml(path: Path) -> bool:
    """Tenta carregar e valida estrutura mínima."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        
        if path.name.startswith("fluxo_"):
            # Fluxos devem ter: estados, regras_invioláveis (opcional)
            assert "estados" in data, f"{path.name}: faltando 'estados'"
        elif path.name == "global.yaml":
            # Global deve ter: identidade, numeros, planos, etc
            assert "identidade" in data
            assert "numeros" in data
            assert "planos" in data
        
        print(f"✓ {path.name}")
        return True
    except Exception as e:
        print(f"✗ {path.name}: {e}")
        return False

if __name__ == "__main__":
    all_ok = True
    for yaml_file in CONFIG_DIR.rglob("*.yaml"):
        if not validate_yaml(yaml_file):
            all_ok = False
    
    sys.exit(0 if all_ok else 1)
```

Roda: `python scripts/validar_yamls.py`
Esperado: todos os 9 YAMLs com ✓

### 0.6 — Atualizar dependências

Verifica/adiciona em `requirements.txt`:
```
pyyaml>=6.0
```

E instala:
```bash
pip install -r requirements.txt
```

### 0.7 — Criar README da reescrita

Cria `REFACTOR.md` na raiz com:

```markdown
# Reescrita do Agente Ana — Status

## Branch atual: refactor/agente-inteligente

## Fases concluídas:
- [x] Fase 0: Setup

## Próxima fase: Fase 1 — Núcleo do sistema

## Estrutura nova
- `app/conversation_v2/` — código novo
- `config/global.yaml` — config global
- `config/fluxos/*.yaml` — fluxos declarativos

## Status do agente antigo
- Pausado em produção desde {DATA}
- Código em `app/conversation/` (intocado)
- Será removido na Fase 9 (cutover)
```

### 0.8 — Commit inicial

```bash
git add .
git commit -m "feat(fase-0): setup da reescrita - estrutura de pastas + YAMLs declarativos"
git push -u origin refactor/agente-inteligente
```

---

## TESTE DE ACEITAÇÃO DA FASE 0

✓ Container `app` parado em produção (verificar com `docker compose ps`)  
✓ Branch `refactor/agente-inteligente` criada e pushada  
✓ Estrutura de pastas `app/conversation_v2/` e `config/fluxos/` existe  
✓ Os 9 YAMLs estão em `config/` e passam pelo script de validação  
✓ `REFACTOR.md` existe na raiz  

---

## AO TERMINAR

Responde:

```
✅ FASE 0 CONCLUÍDA

- Branch: refactor/agente-inteligente
- YAMLs validados: 9/9
- Estrutura de pastas: OK
- Agente atual: pausado em produção
- Commit: <hash>

Aguardando prompt da Fase 1.
```
