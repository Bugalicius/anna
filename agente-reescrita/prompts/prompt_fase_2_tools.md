# FASE 2 — Tools e integrações
# Para: Claude Code (Sonnet)

## OBJETIVO

Implementar as tools (ações concretas com integrações externas) seguindo o padrão Pydantic + function calling. Cada tool tem schema explícito de input/output.

## PRÉ-REQUISITOS

- Fases 0 e 1 concluídas
- Núcleo (config_loader, state_machine, rules) funcionando

## TAREFAS

### 2.1 — Estrutura base de tools

Cria `app/conversation_v2/tools/__init__.py`:

```python
"""
Tools — ações concretas com integrações externas.

Padrão:
    - Cada tool é uma função async
    - Input/output via Pydantic
    - Sempre retorna ToolResult(sucesso: bool, dados: Any, erro: str | None)
"""

from pydantic import BaseModel

class ToolResult(BaseModel):
    sucesso: bool
    dados: dict = {}
    erro: str | None = None
```

### 2.2 — Tool: Consultar slots no Dietbox

Cria `app/conversation_v2/tools/scheduling.py` com:

```python
class ConsultarSlotsInput(BaseModel):
    modalidade: Literal["presencial", "online"]
    preferencia: dict  # {dia_semana, turno, hora, descricao}
    janela_max_dias: int = 90  # ou data específica
    excluir_slots: list[str] = []
    max_resultados: int = 3

class ConsultarSlotsOutput(BaseModel):
    slots: list[Slot]
    match_exato: bool
    slots_count: int

async def consultar_slots(input: ConsultarSlotsInput) -> ToolResult:
    """
    Busca slots no Dietbox respeitando:
    - grade de horários (config global)
    - regras de distribuição (max 2/dia, turnos diferentes, etc)
    - preferência do paciente
    """
```

Reaproveita o código existente em `app/tools/scheduling.py` mas adapta pro novo schema.

**Importante:** aplica filtro do `rule_engine.validar_distribuicao_slots()` ANTES de retornar.

### 2.3 — Tool: Detectar tipo de remarcação

Em `app/conversation_v2/tools/patients.py`:

```python
async def detectar_tipo_remarcacao(telefone: str, identificador: str | None = None) -> ToolResult:
    """
    Identifica:
    - retorno (paciente com consulta ativa)
    - sem_agendamento_confirmado (paciente sem consulta)
    - nao_localizado
    
    Adiciona campo ja_remarcada na consulta_atual se aplicável.
    """
```

### 2.4 — Tool: Remarcar e Cancelar Dietbox

```python
async def remarcar_dietbox(id_agenda: int, novo_slot: Slot) -> ToolResult:
    """PUT no Dietbox. Marca ja_remarcada=true após sucesso."""

async def cancelar_dietbox(id_agenda: int) -> ToolResult:
    """PUT desmarcada=true no Dietbox. NUNCA usa DELETE."""
```

### 2.5 — Tool: Pagamento

Em `app/conversation_v2/tools/payments.py`:

```python
async def gerar_link_pagamento(plano: str, modalidade: str, phone_hash: str) -> ToolResult:
    """Gera link via Rede."""

async def analisar_comprovante(imagem_bytes: bytes, mime_type: str, plano: str, modalidade: str) -> ToolResult:
    """
    Analisa comprovante PIX via Gemini Vision.
    Retorna:
    - eh_comprovante: bool
    - valor: float
    - favorecido: str
    - situacao: enum [exato_sinal, acima_sinal, total_quitado, abaixo_sinal, ilegivel]
    - valor_restante: float
    """

async def encaminhar_comprovante_thaynara(imagem_bytes, resumo_formatado) -> ToolResult:
    """Envia comprovante + resumo pra Thaynara (5531991394759)."""
```

### 2.6 — Tool: Mídias

Em `app/conversation_v2/tools/media.py`:

```python
async def transcrever_audio(audio_bytes: bytes, mime_type: str) -> ToolResult:
    """Transcreve áudio via Gemini."""

async def classificar_imagem(imagem_bytes, contexto: str) -> ToolResult:
    """Classifica: comprovante_pagamento, figurinha, foto_pessoal, documento, outro."""
```

### 2.7 — Tool: Notificações internas

Em `app/conversation_v2/tools/notifications.py`:

```python
async def notificar_breno(mensagem: str) -> ToolResult:
    """Envia ao Breno (5531992059211) via Meta API."""

async def notificar_thaynara(mensagem: str, anexo_imagem: bytes | None = None) -> ToolResult:
    """Envia à Thaynara (5531991394759)."""

async def escalar_breno_silencioso(contexto: dict) -> ToolResult:
    """Cria registro de escalação pendente + notifica Breno com contexto completo."""
```

### 2.8 — Tool: Interpretar comando interno

Em `app/conversation_v2/tools/commands.py`:

```python
async def interpretar_comando(texto: str, remetente: str) -> ToolResult:
    """
    Identifica comando da Thaynara/Breno via Gemini:
    - consultar_status_paciente
    - perguntar_paciente_troca_horario
    - cancelar_consulta
    - remarcar_consulta
    - responder_escalacao
    - enviar_mensagem_para_paciente
    - nao_reconhecido
    
    Extrai parâmetros estruturados.
    """
```

### 2.9 — Registry de tools

Cria `app/conversation_v2/tools/registry.py`:

```python
"""
Registry — registro central de todas as tools disponíveis.
Usado pelo orchestrator para chamar tools dinamicamente.
"""

from app.conversation_v2.tools import scheduling, patients, payments, media, notifications, commands

TOOLS = {
    "consultar_slots": scheduling.consultar_slots,
    "remarcar_dietbox": scheduling.remarcar_dietbox,
    "cancelar_dietbox": scheduling.cancelar_dietbox,
    "detectar_tipo_remarcacao": patients.detectar_tipo_remarcacao,
    "gerar_link_pagamento": payments.gerar_link_pagamento,
    "analisar_comprovante": payments.analisar_comprovante,
    "encaminhar_comprovante_thaynara": payments.encaminhar_comprovante_thaynara,
    "transcrever_audio": media.transcrever_audio,
    "classificar_imagem": media.classificar_imagem,
    "notificar_breno": notifications.notificar_breno,
    "notificar_thaynara": notifications.notificar_thaynara,
    "escalar_breno_silencioso": notifications.escalar_breno_silencioso,
    "interpretar_comando": commands.interpretar_comando,
}

async def call_tool(name: str, input: dict) -> ToolResult:
    """Chama tool pelo nome com validação Pydantic."""
```

### 2.10 — Testes de tools

Cria testes em `tests/conversation_v2/tools/`:

- `test_scheduling.py`: testa consulta de slots (com mock do Dietbox)
- `test_payments.py`: testa análise de comprovante (com mocks)
- `test_media.py`: testa classificação de imagem
- `test_commands.py`: testa interpretação de comandos

Pelo menos 2 testes por tool.

## TESTE DE ACEITAÇÃO

✓ Todas as tools listadas implementadas com schema Pydantic  
✓ Registry funcional  
✓ Testes passando: `pytest tests/conversation_v2/tools/ -v`  
✓ Integração com Dietbox testada manualmente (apenas leitura — não criar/cancelar dados de verdade ainda)  

## AO TERMINAR

```
✅ FASE 2 CONCLUÍDA

Tools criadas: <N>
Testes: <X>/<Y> passando
Integração Dietbox: testada (leitura)
Commit: <hash>

Aguardando prompt da Fase 3.
```
