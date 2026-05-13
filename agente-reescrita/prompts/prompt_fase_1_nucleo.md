# FASE 1 — Núcleo do sistema
# Para: Claude Code (Sonnet)

## OBJETIVO

Criar os módulos do núcleo da arquitetura nova: orchestrator, state machine, rule engine, response writer, output validator. **Sem fluxos específicos ainda** — só a infraestrutura que vai consumir os YAMLs.

## PRÉ-REQUISITOS

- Fase 0 concluída
- YAMLs em `config/`
- Branch `refactor/agente-inteligente` ativa

## TAREFAS

### 1.1 — Carregador de configuração

Cria `app/conversation_v2/config_loader.py`:

```python
"""
Config Loader — carrega YAMLs de configuração com cache.

Uso:
    from app.conversation_v2.config_loader import config
    
    valor_plano = config.get_plano("ouro").valores.pix_presencial
    estados_fluxo_1 = config.get_fluxo("agendamento").estados
"""
```

Implementa:
- Classe `ConfigLoader` que carrega `global.yaml` e todos `fluxos/*.yaml` no startup
- Cache em memória (carregamento lazy)
- Validação Pydantic dos dados (cria models pra `Plano`, `Fluxo`, `Estado`, `Situacao`, etc)
- Método `reload()` pra recarregar sem reiniciar app (útil em dev)
- Singleton global `config`

### 1.2 — Pydantic models

Cria `app/conversation_v2/models.py` com schemas:

- `Plano` (nome_publico, descricao, consultas, valores, etc)
- `Fluxo` (fluxo_id, estado_inicial, estados, regras_invioláveis)
- `Estado` (descricao, intents_aceitas, situacoes, on_enter)
- `Situacao` (trigger, resposta, proximo_estado, etc)
- `Interpretacao` (intent, confidence, entities, ...)
- `AcaoAutorizada` (tipo, dados, proximo_estado, mensagens_a_enviar)

Todos com `model_config = ConfigDict(extra='forbid')` pra catching erros.

### 1.3 — State Machine

Cria `app/conversation_v2/state_machine.py`:

```python
"""
State Machine — decide próxima ação possível a partir do estado atual + intent.

Função principal:
    proxima_acao(estado_atual, intent, entities, fluxo_id) -> AcaoAutorizada | None
"""
```

Implementa:
- Função `proxima_acao(...)` que consulta o YAML do fluxo
- Encontra o estado atual, lê as situações, identifica qual situação foi triggered
- Retorna a `AcaoAutorizada` correspondente
- Se nenhuma situação dispara, retorna `None` (cai pro fallback do orchestrator)
- Suporta `permite_improviso: true` (retorna AcaoAutorizada com flag pro response_writer chamar LLM)
- Aplica `salva_no_estado` nas mutações declaradas

### 1.4 — Rule Engine

Cria `app/conversation_v2/rules.py`:

Implementa funções **puras** (sem efeitos colaterais) pra cada regra inviolável global definida no `config/global.yaml` (R1 a R16):

```python
def R1_nunca_expor_breno(texto: str) -> RuleResult:
    """Bloqueia se texto contém termos do Breno."""
    
def R2_contato_thaynara_apenas_paciente_existente(texto: str, paciente_status: str) -> RuleResult:
    """Só permite enviar contato da Thaynara se for paciente existente."""

def R3_nunca_inventar_valor(texto: str, plano: str | None) -> RuleResult:
    """Verifica se valores citados batem com a tabela."""

# ... R4 a R16
```

Cada função retorna `RuleResult(passou: bool, motivo: str | None)`.

Cria também:
- `validar_resposta_completa(texto, contexto)` que roda TODAS as regras relevantes
- `validar_acao_pre_envio(acao)` que valida ações antes de executar tools

### 1.5 — Response Writer

Cria `app/conversation_v2/response_writer.py`:

```python
"""
Response Writer — transforma AcaoAutorizada em mensagem(ns) final(is).

Função principal:
    escrever(acao: AcaoAutorizada, contexto: Contexto) -> list[Mensagem]
"""
```

Implementa:
- Renderização de template com substituição de placeholders (`{primeiro_nome}`, `{slot_1}`, etc)
- Suporte a múltiplas mensagens em sequência (com delays declarados no YAML)
- Suporte a botões interativos
- Suporte a anexos (imagens, PDFs, contatos)
- Quando `permite_improviso: true`: chama Gemini com instrução estrita e contexto
- **Output Validator** roda DEPOIS de gerar a mensagem — se reprovar, regenera ou usa fallback

### 1.6 — Output Validator

Cria `app/conversation_v2/output_validator.py`:

```python
"""
Output Validator — valida toda mensagem antes de enviar ao paciente.

Roda regras invioláveis globais (R1, R3, R5, etc) na resposta final.
Se reprova, registra e regenera (max 2 tentativas) ou usa fallback seguro.
"""
```

### 1.7 — Orchestrator (esqueleto)

Cria `app/conversation_v2/orchestrator.py` com a estrutura completa mas SEM execução real ainda:

```python
"""
Orchestrator — coordena o pipeline do turno conversacional.

Pipeline:
    1. Carregar contexto (estado + histórico + config)
    2. Interpreter (Gemini)
    3. Normalizar entidades
    4. State Machine -> AcaoAutorizada
    5. Rule Engine valida
    6. Tools (se necessário)
    7. Response Writer
    8. Output Validator
    9. Persistir
"""

async def processar_turno(phone: str, mensagem: dict) -> ResultadoTurno:
    """Pipeline completo de um turno."""
    # TODO: implementar nas próximas fases conforme cada componente fica pronto
    raise NotImplementedError("Será implementado a partir da Fase 3")
```

### 1.8 — Testes unitários do núcleo

Cria `tests/conversation_v2/test_config_loader.py`:
- testa que `global.yaml` carrega sem erro
- testa que todos os fluxos YAML carregam
- testa que `config.get_plano("ouro")` retorna dados corretos

Cria `tests/conversation_v2/test_state_machine.py`:
- testa transição básica entre estados (mock de fluxo simples)
- testa que `proxima_acao` retorna `None` quando nenhuma situação dispara

Cria `tests/conversation_v2/test_rules.py`:
- testa R1: texto com "Breno" é bloqueado
- testa R3: valores divergentes da tabela são bloqueados
- testa R12: nome "consulta" é bloqueado

Roda: `pytest tests/conversation_v2/ -v`
Esperado: todos passam ✅

## TESTE DE ACEITAÇÃO

✓ Todos os módulos criados em `app/conversation_v2/`  
✓ `python scripts/validar_yamls.py` passa  
✓ `pytest tests/conversation_v2/ -v` passa  
✓ `python -c "from app.conversation_v2.config_loader import config; print(config.get_plano('ouro'))"` retorna dados sem erro  

## AO TERMINAR

```
✅ FASE 1 CONCLUÍDA

Módulos criados:
- config_loader.py
- models.py
- state_machine.py
- rules.py
- response_writer.py
- output_validator.py
- orchestrator.py (esqueleto)

Testes: <N>/<M> passando
Commit: <hash>

Aguardando prompt da Fase 2.
```
