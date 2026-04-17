# Instruções para Claude Code — Projeto Agente Ana

## Comportamento ao iniciar sessão

Ao iniciar qualquer sessão neste projeto, leia imediatamente o arquivo `PROGRESS.md` na raiz do projeto e continue o trabalho de onde parou — sem precisar de instrução adicional do usuário.

Se o usuário digitar apenas "continue" ou "pode continuar" ou similar, isso significa: retomar o `PROGRESS.md` e executar a próxima tarefa pendente.

## Sobre o projeto

Agente WhatsApp "Ana" para a nutricionista Thaynara Teixeira. Backend FastAPI com arquitetura multi-agentes. Documentação completa em `docs/superpowers/` e no arquivo `PROGRESS.md`.

## Regras importantes

- Nunca expor o número interno de escalação (31 99205-9211) para pacientes
- Nunca oferecer a modalidade "Formulário" proativamente
- LLM principal: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)
- Todos os novos módulos devem ter testes em `tests/`
- Rodar `python -m pytest tests/ -q` antes de cada commit

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Agente Ana — Assistente Virtual de Agendamento**

Agente de WhatsApp "Ana" para a nutricionista Thaynara Teixeira (CRN9 31020). Backend FastAPI com arquitetura multi-agentes (5 agentes especializados) que automatiza agendamento de consultas, atendimento a dúvidas, remarketing de leads e suporte pré/pós-agendamento. Atende exclusivamente pacientes da Thaynara via WhatsApp.

**Core Value:** A Ana deve interpretar corretamente a intenção do paciente e conduzir o fluxo certo — sem travar, sem dar resposta errada, sem perder o contexto da conversa. Se a interpretação falha, todo o resto falha.

### Constraints

- **LLM**: Claude Haiku 4.5 (claude-haiku-4-5-20251001) — custo controlado, latência baixa
- **Stack**: Python 3.12 + FastAPI — não mudar
- **Hospedagem**: VPS Linux — sem display server (impacta Playwright headless=False)
- **Privacidade**: LGPD — nunca armazenar dados sensíveis fora do Dietbox, pseudonimização para LLM
- **Segurança**: Número 31 99205-9211 NUNCA exposto ao paciente
- **UX**: Mensagens curtas e objetivas, tom informal/acolhedor, emojis com moderação
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- Python 3.12 - All application code (runtime pinned via `FROM python:3.12-slim` in `Dockerfile`)
- None detected
## Runtime
- CPython 3.12 (slim Debian image)
- Containerized via Docker + Docker Compose
- pip (no lockfile; `requirements.txt` is the sole dependency spec)
- Lockfile: absent — only `requirements.txt` present
## Frameworks
- FastAPI 0.115.0 — HTTP server and routing (`app/main.py`, `app/webhook.py`)
- Uvicorn 0.30.6 (standard extras) — ASGI server, launched with `--reload` in development
- SQLAlchemy 2.0.35 — ORM using `DeclarativeBase` with type-mapped columns (`app/models.py`, `app/database.py`)
- Alembic 1.13.3 — database migrations (fallback `create_all` in lifespan if Alembic not run)
- APScheduler 3.10.4 — `BackgroundScheduler` with `SQLAlchemyJobStore` for persistent jobs (`app/remarketing.py`, `app/main.py`)
- Playwright >= 1.40.0 — Chromium-based automation for two purposes:
- pytest 8.3.2 — test runner (`tests/`)
- pytest-asyncio 0.24.0 — async test support
- respx 0.22.0 — httpx mock library for HTTP client tests
## Key Dependencies
- `anthropic >= 0.50.0` — Anthropic Python SDK; used in two places:
- `google-generativeai 0.8.6` — Google Gemini SDK; used in `app/ai_engine.py` as primary response generator (`gemini-2.0-flash` model)
- `httpx[test] 0.27.0` — async HTTP client for Meta Cloud API calls (`app/meta_api.py`, `app/media_handler.py`) and OpenAI Whisper calls
- `requests` (transitive, used explicitly) — sync HTTP client used in `app/agents/dietbox_worker.py` for Dietbox REST API calls
- `psycopg2-binary 2.9.9` — PostgreSQL adapter for SQLAlchemy
- `redis 5.0.8` — Redis client for rate-limiting remarketing dispatch (`app/remarketing.py`)
- `python-dotenv 1.0.1` — loads `.env` file in local development
- `apscheduler[sqlalchemy]` — job persistence via `SQLAlchemyJobStore` using the same Postgres connection
## Configuration
- Configured via `.env` file (loaded by Docker Compose `env_file: .env`)
- Template: `.env.example` at project root
- Critical keys: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DATABASE_URL`, `REDIS_URL`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `META_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN`, `DIETBOX_EMAIL`, `DIETBOX_SENHA`, `REDE_EMAIL`, `REDE_SENHA`
- `Dockerfile` — multi-step: installs system libs for Playwright/Chromium, installs Python deps, runs `playwright install chromium`
- `docker-compose.yml` — defines four services: `app`, `postgres`, `redis`, `nginx`
- No `pyproject.toml` or `setup.py` present; project is not packaged
## Platform Requirements
- Docker + Docker Compose (recommended)
- Python 3.12 for local runs
- Playwright Chromium binaries (installed via `playwright install chromium`)
- For Rede portal automation: display server required (headless=False), which means a headless server needs Xvfb or similar in production
- Docker Compose stack with Postgres 15 and Redis 7
- Nginx (reverse proxy + TLS termination via Certbot/Let's Encrypt volumes configured)
- Port 8000 internal (app), 80/443 external (nginx)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Modules: `snake_case.py` — `meta_api.py`, `knowledge_base.py`, `rede_worker.py`
- Test files: `test_<module>.py` — `test_meta_api.py`, `test_dietbox_worker.py`
- Agents: descriptive name + `_worker` suffix for external-API wrappers — `dietbox_worker.py`, `rede_worker.py`
- `PascalCase` — `AgenteAtendimento`, `AgenteRetencao`, `MetaAPIClient`, `LinkPagamento`
- Agent classes are named `Agente<Domain>` — `AgenteAtendimento`, `AgenteRetencao`
- SQLAlchemy models are named as domain nouns — `Contact`, `Conversation`, `Message`, `RemarketingQueue`
- `snake_case` throughout
- Public functions are descriptive verbs: `consultar_slots_disponiveis`, `processar_agendamento`, `gerar_link_pagamento`
- Private helpers: single underscore prefix `_extrair_nome`, `_identificar_plano`, `_gerar_resposta_llm`, `_despachar`
- Database helpers: `_uuid()`, `_now()` for model default factories
- Private module-level functions: `_classificar_intencao`, `_mock_classificacao`
- Module-level constants: `SCREAMING_SNAKE_CASE` — `ETAPAS`, `MSG_BOAS_VINDAS`, `REMARKETING_SEQ`, `BRT`, `META_API_BASE`
- Local variables: `snake_case` — `msg_lower`, `phone_hash`, `plano_dados`
- Private module-level dicts/sets: leading underscore — `_INTENCOES_AGENTE1`, `_AGENT_STATE`, `_NAO_NOMES`
- `Literal` types defined at module level: `IntencaoType = Literal["novo_lead", ...]` in `app/agents/orchestrator.py`
## Code Style
- No dedicated formatter config detected (no `.prettierrc`, `pyproject.toml`, or `ruff.toml`)
- Indentation: 4 spaces
- Line length: not enforced by config; lines are generally kept under 100 chars
- String quotes: double quotes preferred for multiline strings and messages; single quotes for short inline strings
- No `.pylintrc`, `ruff.toml`, or `setup.cfg` detected — linting is not enforced by tooling
- `# ── Section Name ─────────────────────────────────────────────────────────────`
- Used throughout all agent files to visually separate logical sections
- Example in `app/agents/atendimento.py`: `# ── Mensagens fixas ──────────────────────────────────────────────────────────`
## Type Hints
- Modern union syntax `str | None` (not `Optional[str]`) — enabled by `from __future__ import annotations`
- Return types always annotated: `-> str`, `-> list[str]`, `-> dict`, `-> None`
- SQLAlchemy models use `Mapped[T]` typed columns: `id: Mapped[str] = mapped_column(...)`
- Generic types use built-in forms: `list[dict]`, `dict[str, ...]`, `set[str]` — not `List`, `Dict`
- `from typing import Literal` used for string enum types in `app/agents/orchestrator.py`
## Error Handling
- LLM calls wrapped in `try/except Exception as e` → log error → return fallback string or default value
- External API calls (`dietbox_worker`, `rede_worker`) wrapped in try/except → return structured failure dict
- Database operations use context managers (`with SessionLocal() as db:`) — no explicit try/finally
- `raise_for_status()` called on HTTP responses in `app/meta_api.py` to propagate HTTP errors
- Fallback to PIX when card payment link generation fails (see `app/agents/atendimento.py:_etapa_forma_pagamento`)
## Logging
- Every module defines `logger = logging.getLogger(__name__)` at module level
- Found in: `app/agents/atendimento.py`, `app/agents/orchestrator.py`, `app/agents/retencao.py`, `app/router.py`, `app/webhook.py`, `app/knowledge_base.py`, `app/tags.py`, `app/escalation.py`, `app/media_handler.py`, `app/remarketing.py`
- `logger.error(...)` — exceptions, API failures, missing contacts
- `logger.warning(...)` — missing optional config, unexpected states
- `logger.info(...)` — routing decisions, successful operations, tag changes
- `logger.debug(...)` — high-frequency events like duplicate message skips
- Old-style `%s` string formatting preferred: `logger.error("Falha: %s", e)` — avoids string construction if log level filtered
- f-strings occasionally used: `logger.debug(f"Mensagem duplicada ignorada: {meta_id}")` — inconsistent
- Phone numbers logged as last 4 digits only: `phone[-4:]` — privacy practice
## Documentation Patterns
- All agent files and key modules have module-level docstrings
- Format: multi-line string listing responsibilities and sub-flows as bullet points
- Example in `app/agents/atendimento.py`: lists all 10 flow steps with their names
- Public methods and non-trivial private functions have one-line docstrings
- Return value documented inline in docstring when not obvious: `Returns: (intencao, confianca)`
- Complex returns documented in the docstring body (see `rotear` in `app/agents/orchestrator.py`)
- Domain state values documented as inline comments: `# "pix" | "cartao"`, `# pending | sent | cancelled | failed`
- Section dividers used liberally to structure long files
- TODO-style notes use `# Nota:` or plain comments (no formal `TODO:` prefix found)
## Common Idioms
- Agent classes hold all conversation state as instance attributes
- `etapa: str` tracks current step; `_despachar()` method dispatches to `_etapa_<name>()` methods
- Methods return `list[str]` — multiple messages sent sequentially to the user
- Used in 9 files to enable forward references and `X | Y` union syntax pre-Python 3.10
- `import os`, `from app.xxx import yyy` inside function bodies to avoid circular imports
- Pattern seen in `app/router.py:route_message` and `app/webhook.py:process_message`
- `msg_lower = msg.lower().strip()` computed once at method start and reused for all keyword checks
- External workers return `{"sucesso": bool, "id_paciente": ..., "erro": ...}` rather than raising exceptions
- All user-facing messages defined as module-level constants (`MSG_*` prefix)
- Template placeholders use `.format()` with named keys: `MSG_OBJETIVOS.format(nome=self.nome)`
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## Pattern Overview
- Webhook-driven entry point; Meta Cloud API (WhatsApp Business API) as the message transport
- Stateless HTTP handlers — all conversation state held in-process (Python dict) or database
- Intent classification by LLM (Claude Haiku) routes messages to specialized agents
- Each agent owns a finite-state machine (FSM) for its domain; FSM state persists in `_AGENT_STATE` dict keyed by `phone_hash`
- External side-effects (Dietbox, payment portal) isolated in dedicated worker modules
## Layers
- Purpose: Receive and validate webhooks from Meta; return 200 immediately
- Location: `app/webhook.py`
- Contains: Signature verification, payload parsing, deduplication, `BackgroundTasks` dispatch
- Depends on: `app/meta_api.py` (signature check), `app/models.py` (Contact, Conversation, Message)
- Used by: Meta Cloud API (external)
- Purpose: Load contact state from DB, check for active agent, call orchestrator, dispatch to correct agent, send replies
- Location: `app/router.py`
- Contains: `route_message()`, `_AGENT_STATE` in-memory dict, helper functions
- Depends on: `app/agents/orchestrator.py`, `app/agents/atendimento.py`, `app/agents/retencao.py`, `app/meta_api.py`, `app/database.py`
- Used by: `app/webhook.py` (via `BackgroundTasks`)
- Purpose: Classify message intent via Claude Haiku; return routing instruction
- Location: `app/agents/orchestrator.py`
- Contains: `rotear()`, `_classificar_intencao()`, intent enum, prompt template
- Depends on: `anthropic` SDK (synchronous)
- Used by: `app/router.py`
- Purpose: Drive new patient through 10-step booking funnel
- Location: `app/agents/atendimento.py`
- Contains: `AgenteAtendimento` class, FSM with 10 stages, LLM fallback, helper extractors
- Depends on: `app/agents/dietbox_worker.py`, `app/agents/rede_worker.py`, `app/knowledge_base.py`
- Used by: `app/router.py`
- Purpose: Handle rescheduling and cancellation; outbound remarketing message generation
- Location: `app/agents/retencao.py`
- Contains: `AgenteRetencao` class, `REMARKETING_SEQ` sequence definitions, lembrete builder
- Depends on: `app/agents/dietbox_worker.py`, `app/knowledge_base.py`
- Used by: `app/router.py`, `app/remarketing.py` (for message text)
- Purpose: All Dietbox API interactions — slot lookup, patient CRUD, appointment booking, financial records
- Location: `app/agents/dietbox_worker.py`
- Contains: `consultar_slots_disponiveis()`, `processar_agendamento()`, `agendar_consulta()`, `lancar_financeiro()`, Playwright-based token login
- Depends on: `requests`, `playwright.sync_api`
- Used by: `app/agents/atendimento.py`, `app/agents/retencao.py`
- Purpose: Generate card payment links via meu.userede.com.br portal automation
- Location: `app/agents/rede_worker.py`
- Contains: `gerar_link_pagamento()`, Playwright portal automation in `ThreadPoolExecutor`
- Depends on: `playwright.sync_api`
- Used by: `app/agents/atendimento.py`
- Purpose: SQLAlchemy ORM models; single database session factory
- Location: `app/database.py`, `app/models.py`
- Contains: `Contact`, `Conversation`, `Message`, `RemarketingQueue` models
- Depends on: SQLAlchemy, PostgreSQL (production) / SQLite (dev/test)
- Used by: `app/webhook.py`, `app/router.py`, `app/remarketing.py`, `app/retry.py`
- Purpose: Singleton providing all static business knowledge (plans, prices, policies, FAQ, system prompt) to agents
- Location: `app/knowledge_base.py`
- Contains: `KnowledgeBase` class, `kb` global instance; reads JSON/MD files from `knowledge_base/`
- Used by: `app/agents/atendimento.py`, `app/agents/retencao.py`
- Purpose: APScheduler background jobs — remarketing dispatch and message retry
- Location: `app/remarketing.py`, `app/retry.py`
- Contains: `create_scheduler()`, `_dispatch_due_messages()`, `_retry_failed_messages()`
- Depends on: `apscheduler`, Redis (rate limiting), `app/meta_api.py`
- Used by: `app/main.py` (lifespan startup)
- Purpose: Forward clinical questions to the nutritionist's private number
- Location: `app/escalation.py`
- Contains: `escalar_para_humano()`, `build_contexto_escalacao()`
- Used by: `app/router.py`
- Purpose: Enforce valid `Contact.stage` transitions
- Location: `app/tags.py`
- Contains: `Tag` enum, `set_tag()`, transition rules dict
- Used by: `app/router.py`
## Data Flow
## Key Abstractions
- Purpose: Maintains per-conversation stage and accumulated state (name, plan, slot, payment method)
- Examples: `app/agents/atendimento.py` (`AgenteAtendimento`), `app/agents/retencao.py` (`AgenteRetencao`)
- Pattern: `etapa: str` field drives a `_despachar()` dispatch method; each step returns `list[str]`
- Purpose: Single source of truth for all business rules loaded at import time
- Examples: `app/knowledge_base.py` — `kb.system_prompt()`, `kb.get_valor()`, `kb.get_plano()`
- Pattern: Module-level `kb = KnowledgeBase()` instance; agents import and read but never mutate
- Purpose: Async HTTP client for Meta Cloud API (send text, templates)
- Examples: `app/meta_api.py`
- Pattern: Instantiated per request in `route_message()` using env vars
- Purpose: Browser automation to extract tokens and perform portal actions that lack a public API
- Examples: `app/agents/dietbox_worker.py` (`_login_playwright_sync`), `app/agents/rede_worker.py` (`_gerar_link_portal_sync`)
- Pattern: Sync Playwright wrapped in `ThreadPoolExecutor` to avoid blocking asyncio event loop
## Entry Points
- Location: `app/webhook.py` — `POST /webhook`
- Triggers: Inbound WhatsApp messages from Meta
- Responsibilities: Validate, deduplicate, persist, enqueue for processing
- Location: `app/main.py` — `GET /health`
- Triggers: Load balancer / uptime monitor
- Location: `app/test_chat.py` (router mounted in `app/main.py`)
- Triggers: Development/QA only, not intended for production
- Location: Started in `app/main.py` lifespan `create_scheduler()`
- Triggers: APScheduler intervals (1 min remarketing, 5 min retry)
## Error Handling
- Dietbox/Rede workers: `try/except` around all HTTP calls; return `{"sucesso": False, "erro": ...}` or `LinkPagamento(sucesso=False)` on failure
- Orchestrator: falls back to `"novo_lead"` intent on any Claude API error
- Agent LLM fallback: `_gerar_resposta_llm()` called when no deterministic step matches
- Message delivery: per-message `try/except` in `_enviar()`; failures logged, other messages continue
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
