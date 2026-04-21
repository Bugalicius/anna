"""
Testes do roteamento — Orquestrador (Agente 0) + Redis state integration.
Todos os testes usam mock do Claude e do Redis para não fazer chamadas reais.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ── rotear — primeiro contato ─────────────────────────────────────────────────

def test_primeiro_contato_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="oi", stage_atual=None, primeiro_contato=True)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "novo_lead"


def test_stage_cold_lead_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="quero informações", stage_atual="cold_lead", primeiro_contato=True)
    assert rota["agente"] == "atendimento"


def test_stage_new_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="olá", stage_atual="new", primeiro_contato=True)
    assert rota["agente"] == "atendimento"


# ── rotear — intenções via LLM (mock) ─────────────────────────────────────────

def _mock_classificacao(intencao: str, confianca: float = 0.9):
    """Helper: mocka _classificar_intencao para retornar intenção/confiança fixas."""
    return patch(
        "app.agents.orchestrator._classificar_intencao",
        return_value=(intencao, confianca),
    )


def test_intencao_agendar_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("agendar"):
        rota = rotear("quero marcar uma consulta", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "agendar"


def test_intencao_pagar_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("pagar"):
        rota = rotear("como faço o pagamento?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"


def test_intencao_tirar_duvida_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("tirar_duvida"):
        rota = rotear("qual o valor da consulta?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"


def test_intencao_remarcar_vai_para_retencao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("remarcar"):
        rota = rotear("preciso remarcar", stage_atual="agendado", primeiro_contato=False)
    assert rota["agente"] == "retencao"
    assert rota["intencao"] == "remarcar"


def test_intencao_cancelar_vai_para_retencao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("cancelar"):
        rota = rotear("quero cancelar minha consulta", stage_atual="agendado", primeiro_contato=False)
    assert rota["agente"] == "retencao"
    assert rota["intencao"] == "cancelar"


def test_intencao_duvida_clinica_vai_para_escalacao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("duvida_clinica"):
        rota = rotear("tenho diabetes posso comer açúcar?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "escalacao"


def test_intencao_fora_de_contexto_retorna_resposta_padrao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("fora_de_contexto"):
        rota = rotear("qual o resultado do flamengo?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "padrao"
    assert rota["resposta_padrao"] is not None
    assert len(rota["resposta_padrao"]) > 10


def test_confianca_preenchida():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("agendar", confianca=0.95):
        rota = rotear("quero agendar", stage_atual="presenting", primeiro_contato=False)
    assert rota["confianca"] == pytest.approx(0.95)


def test_fallback_erro_llm_vai_para_atendimento():
    """Se a chamada ao Claude falhar, deve fazer fallback para atendimento (novo_lead)."""
    from app.agents.orchestrator import rotear
    with patch(
        "app.agents.orchestrator._classificar_intencao",
        side_effect=Exception("API error"),
    ):
        rota = rotear("qualquer coisa", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "novo_lead"


# ── Test 9: rotear() aceita parâmetro agente_ativo ───────────────────────────

def test_rotear_aceita_parametro_agente_ativo():
    """Test 9: rotear() deve aceitar agente_ativo como contexto sem erro."""
    from app.agents.orchestrator import rotear
    with _mock_classificacao("agendar"):
        rota = rotear(
            "quero marcar",
            stage_atual="presenting",
            primeiro_contato=False,
            agente_ativo="atendimento",
        )
    assert rota["agente"] == "atendimento"


def test_rotear_agente_ativo_none_funciona():
    """Test 9: rotear() com agente_ativo=None funciona igual ao padrão."""
    from app.agents.orchestrator import rotear
    with _mock_classificacao("remarcar"):
        rota = rotear(
            "preciso remarcar",
            stage_atual="agendado",
            primeiro_contato=False,
            agente_ativo=None,
        )
    assert rota["agente"] == "retencao"


# ── Fixtures para testes de route_message ────────────────────────────────────

def _make_contact(
    first_name: str | None = None,
    collected_name: str | None = None,
    push_name: str | None = None,
    stage: str = "presenting",
):
    contact = MagicMock()
    contact.first_name = first_name
    contact.collected_name = collected_name
    contact.push_name = push_name
    contact.stage = stage
    contact.id = "contact-id-123"
    return contact


def _make_db_mock(contact):
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter_by.return_value.first.return_value = contact
    return db


@pytest.fixture
def state_mgr_mock():
    mgr = MagicMock()
    mgr.load = AsyncMock(return_value=None)
    mgr.save = AsyncMock()
    mgr.delete = AsyncMock()
    return mgr


@pytest.fixture
def meta_mock():
    meta = MagicMock()
    meta.send_text = AsyncMock()
    return meta


# ── Test 10: _AGENT_STATE dict não existe mais em router.py ──────────────────

def test_agent_state_dict_removido():
    """Test 10: _AGENT_STATE não deve existir em app.router."""
    import app.router as router_module
    assert not hasattr(router_module, "_AGENT_STATE"), (
        "_AGENT_STATE dict ainda presente em router.py — deve ser removido"
    )


# ── Helpers de estado ────────────────────────────────────────────────────────


def _make_state(
    goal: str = "desconhecido",
    status: str = "coletando",
    nome: str | None = None,
    id_agenda: str | None = None,
):
    """Cria um state dict mínimo para mocks de load_state."""
    return {
        "goal": goal,
        "status": status,
        "collected_data": {"nome": nome},
        "appointment": {"id_agenda": id_agenda},
        "history": [],
        "flags": {},
    }


# ── Test 1: engine.handle_message chamado com args corretos ──────────────────

@pytest.mark.asyncio
async def test_engine_chamado_com_args_corretos():
    """route_message deve chamar engine.handle_message(phone_hash, text, phone=phone)."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["oi"]) as mock_engine, \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_engine.assert_called_once_with("hash123", "oi", phone="5511999")


# ── Test 2: respostas de texto enviadas ao paciente ──────────────────────────

@pytest.mark.asyncio
async def test_respostas_texto_enviadas():
    """Strings retornadas pelo engine são enviadas via meta.send_text."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["msg A", "msg B"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    assert meta.send_text.call_count == 2
    textos = [call.args[1] for call in meta.send_text.call_args_list]
    assert textos == ["msg A", "msg B"]


# ── Test 3: sentinel de escalação aciona escalar_para_humano ─────────────────

@pytest.mark.asyncio
async def test_sentinel_escalacao():
    """Sentinel {"_meta_action": "escalate"} deve acionar escalar_para_humano."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=[{"_meta_action": "escalate"}]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock), \
         patch("app.escalation.escalar_para_humano", new_callable=AsyncMock) as mock_escalar:
        await route_message("5511999", "hash123", "tenho diabetes", "msg-id-1")

    mock_escalar.assert_called_once()


# ── Test 4: paciente de retorno tem nome pré-populado no state ────────────────

@pytest.mark.asyncio
async def test_paciente_retorno_prepopula_nome():
    """Contato com collected_name deve ter nome pré-populado no state antes do engine."""
    from app.router import route_message

    contact = _make_contact(
        first_name="Marcela", collected_name="Marcela Silva", stage="agendado"
    )
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    state_vazio = _make_state()  # nome=None
    state_gravado: dict = {}

    async def fake_save(phone_hash, state):
        state_gravado.update(state)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["olá"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=state_vazio), \
         patch("app.conversation.state.save_state", side_effect=fake_save):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    # _reconhecer_paciente_retorno deve ter preenchido o nome no state
    assert state_vazio["collected_data"].get("nome") == "Marcela Silva"


# ── Test 5: contato não encontrado retorna sem crash ─────────────────────────

@pytest.mark.asyncio
async def test_contato_nao_encontrado_retorna_sem_crash():
    """Quando contact não existe no banco, route_message retorna silenciosamente."""
    from app.router import route_message

    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.query.return_value.filter_by.return_value.first.return_value = None

    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock) as mock_engine:
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_engine.assert_not_called()
    meta.send_text.assert_not_called()


# ── Test 6: _atualizar_contact persiste nome e stage após engine ──────────────

@pytest.mark.asyncio
async def test_atualizar_contact_persiste_nome_e_stage():
    """Após engine processar, nome e stage do Contact são atualizados no banco."""
    from app.router import route_message

    contact = _make_contact(stage="presenting", collected_name=None)
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    state_concluido = _make_state(
        goal="agendar_consulta", status="concluido",
        nome="Ana Maria", id_agenda="agenda-001",
    )

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["agendado!"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=state_concluido), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "ok", "msg-id-1")

    assert contact.collected_name == "Ana Maria"
    assert contact.first_name == "Ana"
    assert contact.stage == "agendado"


# ── Test 7: remarketing — contato no stage remarketing cancela fila ───────────

@pytest.mark.asyncio
async def test_remarketing_stage_cancela_fila_pendente():
    """Contato em stage=remarketing deve ter cancel_pending_remarketing chamado."""
    from app.router import route_message

    contact = _make_contact(stage="remarketing")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.router.cancel_pending_remarketing") as mock_cancel, \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["olá"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_cancel.assert_called_once()


# ── Test 8: Redis indisponível não trava o sistema ────────────────────────────

@pytest.mark.asyncio
async def test_redis_failure_nao_trava():
    """load_state retornando estado vazio (Redis indisponível) não causa crash."""
    from app.router import route_message

    contact = _make_contact(stage="new")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=["Olá! Bem-vinda!"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        # Não deve lançar exceção
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    meta.send_text.assert_called()
