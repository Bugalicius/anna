# Coding Conventions

**Analysis Date:** 2026-04-07

## Naming Patterns

**Files:**
- Modules: `snake_case.py` — `meta_api.py`, `knowledge_base.py`, `rede_worker.py`
- Test files: `test_<module>.py` — `test_meta_api.py`, `test_dietbox_worker.py`
- Agents: descriptive name + `_worker` suffix for external-API wrappers — `dietbox_worker.py`, `rede_worker.py`

**Classes:**
- `PascalCase` — `AgenteAtendimento`, `AgenteRetencao`, `MetaAPIClient`, `LinkPagamento`
- Agent classes are named `Agente<Domain>` — `AgenteAtendimento`, `AgenteRetencao`
- SQLAlchemy models are named as domain nouns — `Contact`, `Conversation`, `Message`, `RemarketingQueue`

**Functions:**
- `snake_case` throughout
- Public functions are descriptive verbs: `consultar_slots_disponiveis`, `processar_agendamento`, `gerar_link_pagamento`
- Private helpers: single underscore prefix `_extrair_nome`, `_identificar_plano`, `_gerar_resposta_llm`, `_despachar`
- Database helpers: `_uuid()`, `_now()` for model default factories
- Private module-level functions: `_classificar_intencao`, `_mock_classificacao`

**Variables and Constants:**
- Module-level constants: `SCREAMING_SNAKE_CASE` — `ETAPAS`, `MSG_BOAS_VINDAS`, `REMARKETING_SEQ`, `BRT`, `META_API_BASE`
- Local variables: `snake_case` — `msg_lower`, `phone_hash`, `plano_dados`
- Private module-level dicts/sets: leading underscore — `_INTENCOES_AGENTE1`, `_AGENT_STATE`, `_NAO_NOMES`

**Type Aliases:**
- `Literal` types defined at module level: `IntencaoType = Literal["novo_lead", ...]` in `app/agents/orchestrator.py`

## Code Style

**Formatting:**
- No dedicated formatter config detected (no `.prettierrc`, `pyproject.toml`, or `ruff.toml`)
- Indentation: 4 spaces
- Line length: not enforced by config; lines are generally kept under 100 chars
- String quotes: double quotes preferred for multiline strings and messages; single quotes for short inline strings

**Linting:**
- No `.pylintrc`, `ruff.toml`, or `setup.cfg` detected — linting is not enforced by tooling

**Import Organization:**
1. `from __future__ import annotations` — always first when present (used in 9 of 18 source files)
2. Standard library imports (`os`, `json`, `logging`, `datetime`, `hashlib`)
3. Third-party imports (`anthropic`, `fastapi`, `sqlalchemy`, `httpx`, `respx`)
4. Local app imports (`from app.agents.xxx import ...`, `from app.knowledge_base import kb`)

**Visual Section Separators:**
- `# ── Section Name ─────────────────────────────────────────────────────────────`
- Used throughout all agent files to visually separate logical sections
- Example in `app/agents/atendimento.py`: `# ── Mensagens fixas ──────────────────────────────────────────────────────────`

## Type Hints

**Usage:** Consistent across all source files. Every function signature has type hints on parameters and return types.

**Patterns:**
- Modern union syntax `str | None` (not `Optional[str]`) — enabled by `from __future__ import annotations`
- Return types always annotated: `-> str`, `-> list[str]`, `-> dict`, `-> None`
- SQLAlchemy models use `Mapped[T]` typed columns: `id: Mapped[str] = mapped_column(...)`
- Generic types use built-in forms: `list[dict]`, `dict[str, ...]`, `set[str]` — not `List`, `Dict`
- `from typing import Literal` used for string enum types in `app/agents/orchestrator.py`

**Examples:**
```python
# app/agents/orchestrator.py
def rotear(mensagem: str, stage_atual: str | None, primeiro_contato: bool = False) -> dict:

# app/agents/atendimento.py
def _gerar_resposta_llm(historico: list[dict], etapa: str, contexto_extra: str = "") -> str:

# app/models.py — Mapped columns
id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
phone_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
```

## Error Handling

**Strategy:** Catch `Exception` broadly in agent methods, log the error, and return a graceful fallback.

**Patterns:**
- LLM calls wrapped in `try/except Exception as e` → log error → return fallback string or default value
- External API calls (`dietbox_worker`, `rede_worker`) wrapped in try/except → return structured failure dict
- Database operations use context managers (`with SessionLocal() as db:`) — no explicit try/finally
- `raise_for_status()` called on HTTP responses in `app/meta_api.py` to propagate HTTP errors
- Fallback to PIX when card payment link generation fails (see `app/agents/atendimento.py:_etapa_forma_pagamento`)

**Examples:**
```python
# app/agents/orchestrator.py — LLM fallback
except Exception as e:
    logger.error("Erro ao classificar intenção: %s", e)
    return "novo_lead", 0.5   # fallback conservador para novos leads

# app/agents/atendimento.py — Dietbox failure, silent and continue
except Exception as e:
    logger.error("Erro no cadastro Dietbox: %s", e)
# flow continues to confirmation stage regardless
```

## Logging

**Framework:** Python's standard `logging` module throughout.

**Setup Pattern:**
- Every module defines `logger = logging.getLogger(__name__)` at module level
- Found in: `app/agents/atendimento.py`, `app/agents/orchestrator.py`, `app/agents/retencao.py`, `app/router.py`, `app/webhook.py`, `app/knowledge_base.py`, `app/tags.py`, `app/escalation.py`, `app/media_handler.py`, `app/remarketing.py`

**Log Level Usage:**
- `logger.error(...)` — exceptions, API failures, missing contacts
- `logger.warning(...)` — missing optional config, unexpected states
- `logger.info(...)` — routing decisions, successful operations, tag changes
- `logger.debug(...)` — high-frequency events like duplicate message skips

**Format:**
- Old-style `%s` string formatting preferred: `logger.error("Falha: %s", e)` — avoids string construction if log level filtered
- f-strings occasionally used: `logger.debug(f"Mensagem duplicada ignorada: {meta_id}")` — inconsistent
- Phone numbers logged as last 4 digits only: `phone[-4:]` — privacy practice

## Documentation Patterns

**Module Docstrings:**
- All agent files and key modules have module-level docstrings
- Format: multi-line string listing responsibilities and sub-flows as bullet points
- Example in `app/agents/atendimento.py`: lists all 10 flow steps with their names

**Function Docstrings:**
- Public methods and non-trivial private functions have one-line docstrings
- Return value documented inline in docstring when not obvious: `Returns: (intencao, confianca)`
- Complex returns documented in the docstring body (see `rotear` in `app/agents/orchestrator.py`)

**Inline Comments:**
- Domain state values documented as inline comments: `# "pix" | "cartao"`, `# pending | sent | cancelled | failed`
- Section dividers used liberally to structure long files
- TODO-style notes use `# Nota:` or plain comments (no formal `TODO:` prefix found)

## Common Idioms

**Agent State Machine:**
- Agent classes hold all conversation state as instance attributes
- `etapa: str` tracks current step; `_despachar()` method dispatches to `_etapa_<name>()` methods
- Methods return `list[str]` — multiple messages sent sequentially to the user

**`from __future__ import annotations`:**
- Used in 9 files to enable forward references and `X | Y` union syntax pre-Python 3.10

**Inline imports inside functions:**
- `import os`, `from app.xxx import yyy` inside function bodies to avoid circular imports
- Pattern seen in `app/router.py:route_message` and `app/webhook.py:process_message`

**`getattr` with defaults for optional attributes:**
```python
slots = getattr(self, "_slots_oferecidos", [])
```

**`msg.lower()` caching:**
- `msg_lower = msg.lower().strip()` computed once at method start and reused for all keyword checks

**Multi-condition keyword matching:**
```python
any(w in msg_lower for w in ["pix", "transferência", "transferencia"])
```

**Structured result dicts:**
- External workers return `{"sucesso": bool, "id_paciente": ..., "erro": ...}` rather than raising exceptions

**String message constants:**
- All user-facing messages defined as module-level constants (`MSG_*` prefix)
- Template placeholders use `.format()` with named keys: `MSG_OBJETIVOS.format(nome=self.nome)`

---

*Convention analysis: 2026-04-07*
