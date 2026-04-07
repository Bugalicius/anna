# Testing Patterns

**Analysis Date:** 2026-04-07

## Test Framework

**Runner:**
- pytest 8.3.2
- Config: `pytest.ini` (root of project)
- `pythonpath = .` — project root is on `sys.path`, so `from app.xxx import yyy` works directly
- `testpaths = tests` — only `tests/` directory is scanned

**Async Support:**
- pytest-asyncio 0.24.0
- Async tests decorated with `@pytest.mark.asyncio`
- Used for: `test_integration.py` (3 async tests), `test_meta_api.py` (2 async tests)

**HTTP Mocking:**
- respx 0.22.0 — intercepts `httpx` requests at the transport level
- Used in `tests/test_meta_api.py` with `@respx.mock` decorator

**Run Commands:**
```bash
python -m pytest tests/ -q          # Run all tests (quiet)
python -m pytest tests/ -v          # Verbose output
python -m pytest tests/test_<name>.py   # Run single file
python -m pytest tests/ -k "keyword"    # Filter by name
```

No coverage configuration was found (no `--cov` in pytest.ini, no `pytest-cov` in requirements.txt).

## Test File Organization

**Location:** All tests live in `tests/` (separate from source). Co-location with source files is not used.

**Naming:**
- `test_<module_name>.py` — mirrors the source file being tested
- Examples: `test_dietbox_worker.py` tests `app/agents/dietbox_worker.py`

**Structure:**
```
tests/
├── __init__.py
├── test_ai_engine.py
├── test_analyzer.py
├── test_consolidator.py
├── test_dietbox_worker.py       # Dietbox external API worker
├── test_evolution_client.py
├── test_flows.py                # Legacy flow responses
├── test_integration.py          # End-to-end multi-agent flows
├── test_meta_api.py             # MetaAPIClient + verify_signature
├── test_mine_conversations.py
├── test_models.py               # SQLAlchemy ORM models
├── test_pseudonymizer.py
├── test_rede_worker.py          # Rede payment gateway worker
├── test_remarketing.py          # Remarketing queue logic
├── test_retry.py                # Message retry + backoff logic
├── test_router.py               # Orchestrator routing + intent classification
└── test_webhook.py              # FastAPI webhook endpoints
```

## Test Structure

**Suite Organization:**
```python
# Visual section headers mirror the module's own convention
# ── consultar_slots_disponiveis ───────────────────────────────────────────────

def test_slots_exclui_ocupados():
    """Slots que já constam na agenda não devem aparecer como disponíveis."""
    ...

def test_slots_sem_sabado_domingo():
    """Sábado (5) e domingo (6) nunca devem ter slots."""
    ...
```

**Fixture Pattern:**
```python
@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
```
- In-memory SQLite used in `test_models.py`, `test_retry.py`, `test_remarketing.py`
- `db` fixture is the standard pattern for any test requiring database access
- Chained fixtures: `contact(db)` depends on the `db` fixture

**Module-level test client (webhook tests):**
```python
# tests/test_webhook.py
from fastapi import FastAPI
app = FastAPI()
app.include_router(webhook_router)
client = TestClient(app)
```
- `fastapi.testclient.TestClient` used for synchronous HTTP endpoint testing

## Mocking

**Primary Tool:** `unittest.mock` — `patch`, `MagicMock`, `AsyncMock`

**`@patch` as decorator (single dependency):**
```python
@patch("app.agents.dietbox_worker.consultar_slots_disponiveis", return_value=SLOTS_FAKE)
@patch("app.agents.dietbox_worker.processar_agendamento", return_value=AGENDAMENTO_OK)
def test_fluxo_atendimento_pix_completo(mock_agendar, mock_slots):
```
- Decorator order is bottom-up: lowest decorator → first mock parameter

**`patch` as context manager (multiple dependencies in one test):**
```python
with patch("app.agents.dietbox_worker._headers", return_value={}), \
     patch("requests.get", return_value=mock_resp), \
     patch("app.agents.dietbox_worker._carregar_locais"), \
     patch("app.agents.dietbox_worker._ID_LOCAL_PRESENCIAL", "LOCAL-001"):
    ...
```

**`patch.dict` for environment variables:**
```python
_FAKE_ENV = {"WHATSAPP_PHONE_NUMBER_ID": "123456789", "WHATSAPP_TOKEN": "fake-token"}

@patch.dict("os.environ", _FAKE_ENV)
async def test_route_message_atendimento(...)
```

**`AsyncMock` for async functions:**
```python
mock_meta.send_text = AsyncMock()
mock_escalar = AsyncMock()  # via new_callable=AsyncMock in @patch
```

**Helper function for repeated patch setup:**
```python
# tests/test_router.py
def _mock_classificacao(intencao: str, confianca: float = 0.9):
    """Helper: mocka _classificar_intencao para retornar intenção/confiança fixas."""
    return patch(
        "app.agents.orchestrator._classificar_intencao",
        return_value=(intencao, confianca),
    )

# Used as context manager:
with _mock_classificacao("remarcar"):
    rota = rotear(...)
```

**`respx` for HTTP interception:**
```python
@pytest.mark.asyncio
@respx.mock
async def test_send_text_calls_meta_api(client):
    route = respx.post("https://graph.facebook.com/v19.0/{PHONE_ID}/messages") \
        .mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.abc"}]}))
    result = await client.send_text(to="5531999999999", text="Olá!")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
```

**What is mocked:**
- All external HTTP calls (Dietbox API via `requests`, Meta API via `httpx`, Rede portal via Playwright)
- Claude API (`_classificar_intencao`, `_gerar_resposta_llm`) to avoid real API costs
- Database sessions (`SessionLocal`) in end-to-end integration tests
- Environment variables (`os.environ`) when testing credential-dependent code

**What is NOT mocked:**
- In-memory SQLite database (used as a real DB substitute in model/retry/remarketing tests)
- Pure logic functions (slot filtering, backoff calculation, plan identification)
- Agent state machine transitions (tested via real `AgenteAtendimento` / `AgenteRetencao` instances)

## Fixtures and Factories

**Test Data Constants (module-level):**
```python
# tests/test_integration.py
SLOTS_FAKE = [
    {"datetime": "2026-04-14T09:00:00", "data_fmt": "segunda, 14/04", "hora": "9h"},
    ...
]

AGENDAMENTO_OK = {
    "sucesso": True,
    "id_paciente": 42,
    "id_agenda": "agenda-uuid-001",
    "id_transacao": "fin-001",
}
```

**Agent Factory Helper:**
```python
def _fake_atendimento(telefone="5531999990000", phone_hash="hash001"):
    from app.agents.atendimento import AgenteAtendimento
    return AgenteAtendimento(telefone=telefone, phone_hash=phone_hash)
```

**Direct state injection:**
- Agent attributes are set directly before the step being tested:
```python
agente.nome = "João"
agente.plano_escolhido = "ouro"
agente.etapa = "agendamento"
agente._slots_oferecidos = SLOTS_FAKE
```

## Coverage

**Requirements:** Not enforced. No `pytest-cov` in `requirements.txt` and no coverage configuration in `pytest.ini`.

**View Coverage (if pytest-cov installed):**
```bash
python -m pytest tests/ --cov=app --cov-report=term-missing
```

## Test Types

**Unit Tests:**
- Tests of individual functions and pure logic
- Examples: `test_rede_worker.py` (valor/parcelas lookups), `test_router.py` (routing rules), `test_retry.py` (backoff calculation)
- No real I/O — all dependencies mocked or replaced with in-memory SQLite

**Integration Tests (`tests/test_integration.py`):**
- Full conversation flows exercising multiple agents in sequence
- Mocks only external I/O (Dietbox, Meta API, Rede)
- Agent state transitions are real — tests assert `agente.etapa`, `agente.forma_pagamento`, etc.
- File-level docstring documents the 8 flows covered

**API Tests:**
- `tests/test_webhook.py` — FastAPI HTTP endpoints via `TestClient`
- `tests/test_meta_api.py` — `MetaAPIClient` methods via `respx` HTTP mocking

**No E2E Tests:** There is no test layer that exercises a running server against real external APIs.

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
@patch.dict("os.environ", _FAKE_ENV)
@patch("app.router.rotear", return_value={...})
@patch("app.meta_api.MetaAPIClient")
@patch("app.router.SessionLocal")
async def test_route_message_atendimento(mock_db_cls, mock_meta_cls, mock_rotear):
    ...
    await route_message(phone, phone_hash, "oi", "msg-001")
    assert mock_meta.send_text.called
```

**Error/Failure Testing:**
```python
# Testing API failure returns structured failure dict
with patch("app.agents.dietbox_worker.buscar_paciente_por_telefone",
           side_effect=Exception("API indisponível")):
    result = processar_agendamento(...)
assert result["sucesso"] is False
assert "erro" in result

# Testing ValueError raised on bad data
with pytest.raises(ValueError):
    cadastrar_paciente({"nome": "Teste", "telefone": "5531900000000"})
```

**Database Integrity Testing:**
```python
from sqlalchemy.exc import IntegrityError
with pytest.raises(IntegrityError):
    msg2 = Message(meta_message_id="META_MSG_001", ...)
    db.add(msg2)
    db.commit()
```

**Conditional skip:**
```python
if not horarios:
    pytest.skip("Próximo dia é fim de semana")
```

## Test Gaps

**`app/main.py`:** No test file for the FastAPI app startup/lifespan.

**`app/media_handler.py`:** No test file — audio download and transcription via OpenAI untested.

**`app/escalation.py`:** Covered only indirectly via `test_integration.py`; no dedicated unit tests.

**`app/knowledge_base.py`:** No test file — KB loading logic and `system_prompt()` untested.

**`app/tags.py`:** No test file — tag state machine transitions untested.

**`app/ai_engine.py`:** No functional tests; `test_ai_engine.py` exists but relationship to current code unclear.

**LLM fallback paths:** `_gerar_resposta_llm` in `app/agents/atendimento.py` is never exercised in tests — the mock at the orchestrator level prevents reaching it.

**Playwright (Rede portal):** `_gerar_link_portal` is always mocked; the actual browser automation in `app/agents/rede_worker.py` has no test coverage.

---

*Testing analysis: 2026-04-07*
