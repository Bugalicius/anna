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


# ── Test 1: route_message carrega estado do Redis no início ──────────────────

@pytest.mark.asyncio
async def test_route_message_carrega_redis_no_inicio(state_mgr_mock, meta_mock):
    """Test 1: load() do state_mgr é chamado no início de route_message."""
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)

    agente_mock = MagicMock()
    agente_mock.processar = MagicMock(return_value=["olá"])
    agente_mock.etapa = "coleta_nome"

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "novo_lead",
             "confianca": 1.0,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteAtendimento") as MockAgente:
        instance = MockAgente.return_value
        instance.processar.return_value = ["oi paciente"]
        instance.etapa = "coleta_nome"
        instance.nome = None
        instance.to_dict = MagicMock(return_value={"_tipo": "atendimento", "etapa": "coleta_nome"})
        await router_module.route_message("5511999", "hash123", "oi", "msg-id-1")

    state_mgr_mock.load.assert_called_once_with("hash123")


# ── Test 2: route_message salva estado no Redis após processar ────────────────

@pytest.mark.asyncio
async def test_route_message_salva_redis_apos_processar(state_mgr_mock, meta_mock):
    """Test 2: save() do state_mgr é chamado após agente processar (etapa não finalizada)."""
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "novo_lead",
             "confianca": 1.0,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteAtendimento") as MockAgente:
        instance = MockAgente.return_value
        instance.processar.return_value = ["oi paciente"]
        instance.etapa = "coleta_nome"  # não finalizado
        instance.nome = None
        instance.to_dict = MagicMock(return_value={"_tipo": "atendimento", "etapa": "coleta_nome"})
        await router_module.route_message("5511999", "hash123", "oi", "msg-id-1")

    state_mgr_mock.save.assert_called_once()


# ── Test 3: route_message deleta estado quando fluxo finalizado ───────────────

@pytest.mark.asyncio
async def test_route_message_deleta_redis_em_finalizacao(state_mgr_mock, meta_mock):
    """Test 3: delete() chamado quando AgenteAtendimento.etapa == 'finalizacao'."""
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "novo_lead",
             "confianca": 1.0,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteAtendimento") as MockAgente:
        instance = MockAgente.return_value
        instance.processar.return_value = ["consulta agendada com sucesso!"]
        instance.etapa = "finalizacao"  # fluxo finalizado
        instance.nome = "Maria"
        instance.pagamento_confirmado = False
        # _tipo permite que _fluxo_finalizado identifique o tipo via getattr fallback
        instance._tipo = "AgenteAtendimento"
        instance.to_dict = MagicMock(return_value={"_tipo": "atendimento", "etapa": "finalizacao"})
        await router_module.route_message("5511999", "hash123", "ok", "msg-id-1")

    state_mgr_mock.delete.assert_called_once_with("hash123")
    state_mgr_mock.save.assert_not_called()


# ── Test 4: interrupt detection — remarcar troca de agente ────────────────────

@pytest.mark.asyncio
async def test_interrupt_remarcar_troca_agente(state_mgr_mock, meta_mock):
    """Test 4: com AgenteAtendimento ativo + intenção 'remarcar' → troca para AgenteRetencao."""
    from app.agents.atendimento import AgenteAtendimento
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    # Agente de atendimento ativo no Redis
    agente_ativo = AgenteAtendimento(telefone="5511999", phone_hash="hash123")
    agente_ativo.etapa = "escolha_plano"
    agente_ativo.nome = "Carlos"
    state_mgr_mock.load = AsyncMock(return_value=agente_ativo)

    contact = _make_contact(stage="presenting", collected_name="Carlos")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "retencao",
             "intencao": "remarcar",
             "confianca": 0.95,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteRetencao") as MockRetencao:
        instance = MockRetencao.return_value
        instance.processar_remarcacao.return_value = ["vamos remarcar!"]
        instance.etapa = "aguardando_slot"
        instance.to_dict = MagicMock(return_value={"_tipo": "retencao", "etapa": "aguardando_slot"})
        await router_module.route_message("5511999", "hash123", "quero remarcar", "msg-id-1")

    # Deve ter deletado o estado antigo e criado AgenteRetencao
    state_mgr_mock.delete.assert_called()
    MockRetencao.assert_called_once()


# ── Test 5: inline — tirar_duvida responde sem trocar de agente ───────────────

@pytest.mark.asyncio
async def test_tirar_duvida_em_etapa_sensivel_deixa_agente_responder(state_mgr_mock, meta_mock):
    """Com agente ativo em etapa sensível, dúvida contextual deve ser tratada pelo próprio agente."""
    from app.agents.atendimento import AgenteAtendimento
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    agente_ativo = AgenteAtendimento(telefone="5511999", phone_hash="hash123")
    agente_ativo.etapa = "escolha_plano"
    agente_ativo.nome = "Ana"
    state_mgr_mock.load = AsyncMock(return_value=agente_ativo)

    contact = _make_contact(stage="presenting", collected_name="Ana")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "tirar_duvida",
             "confianca": 0.88,
             "resposta_padrao": None,
         }):
        agente_ativo.processar = MagicMock(return_value=["explicação contextual"])
        await router_module.route_message("5511999", "hash123", "quanto custa?", "msg-id-1")

    agente_ativo.processar.assert_called_once_with("quanto custa?")
    state_mgr_mock.save.assert_called_once()
    # send_text deve ter sido chamado com a resposta do próprio agente
    meta_mock.send_text.assert_called_once()
    assert "explicação contextual" in str(meta_mock.send_text.call_args)


@pytest.mark.asyncio
async def test_agente_ativo_atendimento_atualiza_tag_e_nome_no_contact(state_mgr_mock, meta_mock):
    """Agente ativo de atendimento deve persistir stage e nome ao avançar o fluxo."""
    from app.agents.atendimento import AgenteAtendimento
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    agente_ativo = AgenteAtendimento(telefone="5511999", phone_hash="hash123")
    agente_ativo.etapa = "agendamento"
    agente_ativo.nome = "Ana Maria"
    agente_ativo.processar = MagicMock(return_value=["vamos para pagamento"])
    state_mgr_mock.load = AsyncMock(return_value=agente_ativo)

    contact = _make_contact(stage="novo_lead", collected_name=None)
    db_mock = _make_db_mock(contact)

    def _processar(_text):
        agente_ativo.etapa = "forma_pagamento"
        agente_ativo.nome = "Ana Maria"
        return ["vamos para pagamento"]

    agente_ativo.processar = MagicMock(side_effect=_processar)

    with patch("app.router.SessionLocal", return_value=db_mock), \
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "novo_lead",
             "confianca": 0.99,
             "resposta_padrao": None,
         }):
        await router_module.route_message("5511999", "hash123", "1", "msg-id-1")

    assert contact.stage == "aguardando_pagamento"
    assert contact.collected_name == "Ana Maria"
    assert contact.first_name == "Ana"
    state_mgr_mock.save.assert_called_once()


# ── Test 6: inline — fora_de_contexto mantém agente ativo ────────────────────

@pytest.mark.asyncio
async def test_inline_fora_contexto_mantem_agente_ativo(state_mgr_mock, meta_mock):
    """Test 6: com agente ativo + intenção 'fora_de_contexto' → responde inline, agente NÃO troca."""
    from app.agents.atendimento import AgenteAtendimento
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    agente_ativo = AgenteAtendimento(telefone="5511999", phone_hash="hash123")
    agente_ativo.etapa = "coleta_nome"
    state_mgr_mock.load = AsyncMock(return_value=agente_ativo)

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "padrao",
             "intencao": "fora_de_contexto",
             "confianca": 0.9,
             "resposta_padrao": "Posso ajudar com agendamentos 💚",
         }):
        await router_module.route_message("5511999", "hash123", "quem ganhou a copa?", "msg-id-1")

    # Agente deve ter sido salvo (não deletado)
    state_mgr_mock.save.assert_called_once()
    state_mgr_mock.delete.assert_not_called()
    meta_mock.send_text.assert_called_once()


# ── Test 7: paciente com first_name recebe saudação personalizada ─────────────

@pytest.mark.asyncio
async def test_paciente_retorno_saudacao_por_nome(state_mgr_mock, meta_mock):
    """Test 7: Contact.first_name='Marcela' → saudação personalizada com nome (D-14)."""
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    # Sem agente ativo no Redis (nova sessão)
    state_mgr_mock.load = AsyncMock(return_value=None)

    contact = _make_contact(
        first_name="Marcela",
        stage="agendado",  # não é primeiro contato
    )
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "retencao",
             "intencao": "remarcar",
             "confianca": 0.9,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteRetencao") as MockRetencao:
        instance = MockRetencao.return_value
        instance.processar_remarcacao.return_value = ["vamos remarcar!"]
        instance.etapa = "aguardando_slot"
        instance.to_dict = MagicMock(return_value={"_tipo": "retencao", "etapa": "aguardando_slot"})
        await router_module.route_message("5511999", "hash123", "oi quero remarcar", "msg-id-1")

    # Deve ter enviado saudação personalizada (primeiro send_text)
    calls = meta_mock.send_text.call_args_list
    assert len(calls) >= 1
    # Pelo menos uma das mensagens deve conter o nome
    textos = [str(c) for c in calls]
    assert any("Marcela" in t for t in textos), (
        f"Nome 'Marcela' não encontrado nas mensagens enviadas: {textos}"
    )


# ── Test 8: falha do Redis não trava o sistema ───────────────────────────────

@pytest.mark.asyncio
async def test_redis_failure_nao_trava(state_mgr_mock, meta_mock):
    """Test 8: Redis load retorna None (falha) → fluxo normal sem crash (D-15)."""
    import app.router as router_module
    router_module._state_mgr = state_mgr_mock

    # Redis retorna None (simulando falha ou ausência de estado)
    state_mgr_mock.load = AsyncMock(return_value=None)

    contact = _make_contact(stage="new")
    db_mock = _make_db_mock(contact)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.rotear", return_value={
             "agente": "atendimento",
             "intencao": "novo_lead",
             "confianca": 1.0,
             "resposta_padrao": None,
         }), \
         patch("app.router.AgenteAtendimento") as MockAgente:
        instance = MockAgente.return_value
        instance.processar.return_value = ["Olá! Bem-vinda!"]
        instance.etapa = "coleta_nome"
        instance.nome = None
        instance.to_dict = MagicMock(return_value={"_tipo": "atendimento", "etapa": "coleta_nome"})
        # Não deve lançar exceção
        await router_module.route_message("5511999", "hash123", "oi", "msg-id-1")

    # Deve ter criado novo agente e enviado resposta
    meta_mock.send_text.assert_called()
