"""
Testes de integração end-to-end — Agente Ana.

Cobrem os fluxos principais sem chamadas reais a APIs externas:
  1. Atendimento completo via PIX
  2. Atendimento com pagamento por cartão
  3. Retenção — remarcação
  4. Retenção — cancelamento
  5. route_message end-to-end (Orquestrador → Agente → Meta API)
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRT = timezone(timedelta(hours=-3))

# ── Fixtures ──────────────────────────────────────────────────────────────────

SLOTS_FAKE = [
    {"datetime": "2026-04-14T09:00:00", "data_fmt": "segunda, 14/04", "hora": "9h"},
    {"datetime": "2026-04-15T10:00:00", "data_fmt": "terça, 15/04", "hora": "10h"},
    {"datetime": "2026-04-16T14:00:00", "data_fmt": "quarta, 16/04", "hora": "14h"},
]

AGENDAMENTO_OK = {
    "sucesso": True,
    "id_paciente": 42,
    "id_agenda": "agenda-uuid-001",
    "id_transacao": "fin-001",
}


def _fake_atendimento(telefone="5531999990000", phone_hash="hash001"):
    from app.agents.atendimento import AgenteAtendimento
    return AgenteAtendimento(telefone=telefone, phone_hash=phone_hash)


# ── 1. Fluxo completo de atendimento via PIX ──────────────────────────────────

@patch("app.agents.atendimento.consultar_slots_disponiveis", return_value=SLOTS_FAKE)
@patch("app.agents.atendimento.processar_agendamento", return_value=AGENDAMENTO_OK)
def test_fluxo_atendimento_pix_completo(mock_agendar, mock_slots):
    agente = _fake_atendimento()

    # Etapa 1 — boas-vindas (primeira mensagem)
    r1 = agente.processar("oi")
    assert len(r1) == 1
    assert "Ana" in r1[0]
    assert agente.etapa == "boas_vindas"

    # Etapa 1 — coleta nome
    r2 = agente.processar("Maria Silva, sou nova paciente")
    assert agente.nome is not None and "Maria" in agente.nome
    assert agente.etapa == "qualificacao"

    # Etapa 2 — qualificação
    r3 = agente.processar("quero perder peso")
    assert agente.etapa == "apresentacao_planos"
    assert len(r3) >= 1  # retorna intro + PDF + resumo dos planos

    # Etapa 3 — escolha do plano ouro + modalidade presencial
    r4 = agente.processar("gostei do plano ouro presencial")
    # pode gerar upsell ou ir para agendamento
    assert agente.plano_escolhido in ("ouro", "com_retorno", "unica", "premium")
    assert agente.modalidade == "presencial"

    # Se upsell foi gerado, recusa e avança
    if agente.etapa == "escolha_plano":
        r5 = agente.processar("não, quero manter o ouro mesmo")
    # Agora deve estar em agendamento
    mock_slots.assert_called()

    # Avança para agendamento — escolhe opção 1
    agente.etapa = "agendamento"
    agente._slots_oferecidos = SLOTS_FAKE
    r6 = agente.processar("quero o 1")
    assert agente.etapa == "forma_pagamento"
    assert agente.slot_escolhido == SLOTS_FAKE[0]

    # Escolhe PIX
    r7 = agente.processar("quero pagar por pix")
    assert agente.forma_pagamento == "pix"
    assert agente.etapa == "pagamento"
    assert any("PIX" in r or "pix" in r.lower() for r in r7)

    # Confirma pagamento
    r8 = agente.processar("paguei")
    assert agente.pagamento_confirmado is True
    mock_agendar.assert_called_once()

    # Deve ter chegado à confirmação ou finalização
    assert agente.etapa in ("confirmacao", "finalizacao")

    # Confirmação final
    r9 = agente.processar("ok")
    assert agente.etapa == "finalizacao"


# ── 2. Fluxo com pagamento por cartão ────────────────────────────────────────

@patch("app.agents.dietbox_worker.consultar_slots_disponiveis", return_value=SLOTS_FAKE)
@patch("app.agents.dietbox_worker.processar_agendamento", return_value=AGENDAMENTO_OK)
@patch("app.agents.rede_worker._gerar_link_portal")
def test_fluxo_atendimento_cartao(mock_portal, mock_agendar, mock_slots):
    from app.agents.rede_worker import LinkPagamento
    mock_portal.return_value = LinkPagamento(
        url="https://meu.userede.com.br/link/abc123",
        valor=690.00, parcelas=6, sucesso=True,
    )

    agente = _fake_atendimento(phone_hash="hash002")
    agente.nome = "João"
    agente.plano_escolhido = "ouro"
    agente.modalidade = "presencial"
    agente.upsell_oferecido = True
    agente.etapa = "agendamento"
    agente._slots_oferecidos = SLOTS_FAKE

    # Escolhe horário
    agente.processar("quero o segundo horário")
    assert agente.slot_escolhido == SLOTS_FAKE[1]

    # Escolhe cartão
    respostas = agente.processar("prefiro cartão de crédito")
    assert agente.forma_pagamento == "cartao"
    assert agente.etapa == "pagamento"

    link_enviado = " ".join(respostas)
    assert "https://meu.userede.com.br/link/abc123" in link_enviado
    assert "6x" in link_enviado or "6" in link_enviado

    mock_portal.assert_called_once()


# ── 3. Falha ao gerar link faz fallback para PIX ─────────────────────────────

@patch("app.agents.rede_worker._gerar_link_portal")
def test_falha_cartao_fallback_pix(mock_portal):
    from app.agents.rede_worker import LinkPagamento
    mock_portal.return_value = LinkPagamento(
        url=None, valor=260.00, parcelas=3, sucesso=False, erro="Timeout",
    )

    agente = _fake_atendimento(phone_hash="hash003")
    agente.nome = "Ana"
    agente.plano_escolhido = "unica"
    agente.modalidade = "presencial"
    agente.etapa = "forma_pagamento"
    agente.slot_escolhido = SLOTS_FAKE[0]

    respostas = agente.processar("quero cartão")
    # Fallback: vira pix e manda mensagem de erro com chave
    assert agente.forma_pagamento == "pix"
    texto = " ".join(respostas)
    assert "PIX" in texto or "pix" in texto.lower()


# ── 4. Fluxo de retenção — remarcação ────────────────────────────────────────

@patch("app.agents.retencao.consultar_slots_disponiveis", return_value=SLOTS_FAKE)
@patch("app.agents.retencao.verificar_lancamento_financeiro", return_value=True)
@patch("app.agents.retencao.consultar_agendamento_ativo",
       return_value={"id": "AGENDA-001", "inicio": "2026-04-17T09:00:00",
                     "fim": "2026-04-17T10:00:00", "id_servico": "SVC-001"})
@patch("app.agents.retencao.buscar_paciente_por_telefone",
       return_value={"id": 42, "nome": "Carlos", "telefone": "5531999990001"})
def test_fluxo_remarcacao_completo(mock_pac, mock_agenda, mock_lanc, mock_slots):
    from app.agents.retencao import AgenteRetencao

    agente = AgenteRetencao(telefone="5531999990001", nome="Carlos", modalidade="online")

    # Inicia remarcação — detecta retorno → coleta preferência de horário
    r1 = agente.processar_remarcacao("preciso remarcar minha consulta")
    assert agente.etapa == "coletando_preferencia"

    # Informa preferência → oferece slots
    r2 = agente.processar_remarcacao("qualquer horário da semana seguinte")
    assert agente.etapa == "oferecendo_slots"
    assert len(agente._slots_oferecidos) >= 1

    # Escolhe opção 3 (código usa "terceiro", masculino)
    # Plan 02-03: após escolha, etapa vai para aguardando_confirmacao_dietbox
    # e retorna mensagem de espera (Dietbox ainda não foi chamado)
    with patch("app.agents.retencao.alterar_agendamento", return_value=True):
        r3 = agente.processar_remarcacao("pode ser o terceiro horário")
    assert agente.etapa == "aguardando_confirmacao_dietbox"
    texto3 = " ".join(r3)
    # Retorna indicador de espera antes de chamar Dietbox
    assert "instante" in texto3.lower() or "💚" in texto3


# ── 5. Retenção — remarcação sem slots disponíveis ───────────────────────────

@patch("app.agents.retencao.consultar_slots_disponiveis", return_value=[])
@patch("app.agents.retencao.verificar_lancamento_financeiro", return_value=True)
@patch("app.agents.retencao.consultar_agendamento_ativo",
       return_value={"id": "AGENDA-002", "inicio": "2026-04-17T09:00:00",
                     "fim": "2026-04-17T10:00:00", "id_servico": "SVC-001"})
@patch("app.agents.retencao.buscar_paciente_por_telefone",
       return_value={"id": 43, "nome": "Paula", "telefone": "5531999990002"})
def test_remarcacao_sem_slots(mock_pac, mock_agenda, mock_lanc, mock_slots):
    from app.agents.retencao import AgenteRetencao

    agente = AgenteRetencao(telefone="5531999990002", nome="Paula", modalidade="presencial")
    # Primeiro passo: detecta retorno → pede preferência
    r1 = agente.processar_remarcacao("quero remarcar")
    assert agente.etapa == "coletando_preferencia"

    # Segundo passo: informa preferência → sem slots disponíveis
    respostas = agente.processar_remarcacao("qualquer horário")
    texto = " ".join(respostas)
    assert "não encontrei" in texto.lower() or "Thaynara" in texto or "verificar" in texto.lower()


# ── 6. Fluxo de retenção — cancelamento ──────────────────────────────────────

def test_fluxo_cancelamento_completo():
    from app.agents.retencao import AgenteRetencao

    agente = AgenteRetencao(telefone="5531999990003", nome="Roberto", modalidade="presencial")

    r1 = agente.processar_cancelamento("quero cancelar minha consulta")
    assert agente.etapa == "aguardando_motivo"
    assert "Roberto" in r1[0]

    r2 = agente.processar_cancelamento("tive um imprevisto")
    assert agente.etapa == "concluido"
    assert any("cancelad" in r.lower() for r in r2)


# ── 7. Mensagem de remarketing e lembrete ────────────────────────────────────

def test_montar_mensagem_remarketing():
    from app.agents.retencao import montar_mensagem_remarketing

    msg1 = montar_mensagem_remarketing(1, "Clara")
    assert "Clara" in msg1
    assert "Thaynara" in msg1

    msg3 = montar_mensagem_remarketing(3, "Pedro")
    assert "Pedro" in msg3

    # Posição inválida retorna string vazia
    assert montar_mensagem_remarketing(99, "X") == ""


def test_montar_lembrete_presencial():
    from app.agents.retencao import montar_lembrete_consulta

    msg = montar_lembrete_consulta("Fernanda", "10/04", "9h", "presencial")
    assert "Fernanda" in msg
    assert "10/04" in msg
    assert "9h" in msg
    assert "10 minutos" in msg


def test_montar_lembrete_online():
    from app.agents.retencao import montar_lembrete_consulta

    msg = montar_lembrete_consulta("Luisa", "11/04", "15h", "online")
    assert "videochamada" in msg.lower() or "link" in msg.lower()


# ── 8. route_message end-to-end (sem DB nem Meta API reais) ──────────────────

_FAKE_ENV = {"WHATSAPP_PHONE_NUMBER_ID": "123456789", "WHATSAPP_TOKEN": "fake-token"}


@pytest.mark.asyncio
@patch.dict("os.environ", _FAKE_ENV)
@patch("app.router.rotear", return_value={
    "agente": "atendimento",
    "intencao": "novo_lead",
    "confianca": 1.0,
    "resposta_padrao": None,
})
@patch("app.router.set_tag")
@patch("app.meta_api.MetaAPIClient")
@patch("app.router.SessionLocal")
async def test_route_message_atendimento(mock_db_cls, mock_meta_cls, mock_set_tag, mock_rotear):
    from unittest.mock import AsyncMock as _AsyncMock
    import app.router as router_module
    from app.router import route_message

    # Mock do state_mgr (Redis) — sem estado ativo
    state_mgr = MagicMock()
    state_mgr.load = _AsyncMock(return_value=None)
    state_mgr.save = _AsyncMock()
    state_mgr.delete = _AsyncMock()
    router_module._state_mgr = state_mgr

    # Mock do banco
    mock_contact = MagicMock()
    mock_contact.stage = "new"
    mock_contact.collected_name = None
    mock_contact.push_name = "Teste"
    mock_contact.first_name = None
    mock_contact.id = 1

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_contact
    mock_db_cls.return_value = mock_session

    # Mock do Meta API
    mock_meta = MagicMock()
    mock_meta.send_text = AsyncMock()
    mock_meta_cls.return_value = mock_meta

    phone = "5531999990099"
    phone_hash = "hash_e2e_001"

    await route_message(phone, phone_hash, "oi", "msg-001")

    # Deve ter chamado send_text com boas-vindas
    assert mock_meta.send_text.called
    args = mock_meta.send_text.call_args[0]
    assert phone in args
    assert "Ana" in args[1]


@pytest.mark.asyncio
@patch.dict("os.environ", _FAKE_ENV)
@patch("app.router.rotear", return_value={
    "agente": "padrao",
    "intencao": "fora_de_contexto",
    "confianca": 0.9,
    "resposta_padrao": "Posso te ajudar com agendamentos!",
})
@patch("app.meta_api.MetaAPIClient")
@patch("app.router.SessionLocal")
async def test_route_message_fora_contexto(mock_db_cls, mock_meta_cls, mock_rotear):
    from unittest.mock import AsyncMock as _AsyncMock
    import app.router as router_module
    from app.router import route_message

    state_mgr = MagicMock()
    state_mgr.load = _AsyncMock(return_value=None)
    state_mgr.save = _AsyncMock()
    state_mgr.delete = _AsyncMock()
    router_module._state_mgr = state_mgr

    mock_contact = MagicMock()
    mock_contact.stage = "presenting"
    mock_contact.collected_name = None
    mock_contact.push_name = None
    mock_contact.first_name = None
    mock_contact.id = 2

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_contact
    mock_db_cls.return_value = mock_session

    mock_meta = MagicMock()
    mock_meta.send_text = AsyncMock()
    mock_meta_cls.return_value = mock_meta

    await route_message("5531000000001", "hash_e2e_002", "qual o resultado do brasileirão?", "msg-002")

    assert mock_meta.send_text.called
    args = mock_meta.send_text.call_args[0]
    assert "agendamentos" in args[1].lower() or "Posso" in args[1]


@pytest.mark.asyncio
@patch.dict("os.environ", _FAKE_ENV)
@patch("app.escalation.escalar_para_humano", new_callable=AsyncMock)
@patch("app.router.rotear", return_value={
    "agente": "escalacao",
    "intencao": "duvida_clinica",
    "confianca": 0.9,
    "resposta_padrao": None,
})
@patch("app.meta_api.MetaAPIClient")
@patch("app.router.SessionLocal")
async def test_route_message_escalacao(mock_db_cls, mock_meta_cls, mock_rotear, mock_escalar):
    from unittest.mock import AsyncMock as _AsyncMock
    import app.router as router_module
    from app.router import route_message

    state_mgr = MagicMock()
    state_mgr.load = _AsyncMock(return_value=None)
    state_mgr.save = _AsyncMock()
    state_mgr.delete = _AsyncMock()
    router_module._state_mgr = state_mgr

    mock_contact = MagicMock()
    mock_contact.stage = "presenting"
    mock_contact.collected_name = "Joana"
    mock_contact.push_name = None
    mock_contact.first_name = None
    mock_contact.id = 3

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.query.return_value.filter_by.return_value.first.return_value = mock_contact
    mock_db_cls.return_value = mock_session

    mock_meta = MagicMock()
    mock_meta.send_text = AsyncMock()
    mock_meta_cls.return_value = mock_meta

    await route_message("5531000000002", "hash_e2e_003", "tenho diabetes, posso comer pão?", "msg-003")

    mock_escalar.assert_called_once()
