"""
Testes para os bug fixes do fluxo conversacional.

Cenários testados:
  1. Desistir sem consulta agendada → abandon_process (não pede motivo, não envia política)
  2. Cancelar com consulta existente → fluxo completo (pede motivo, envia política)
  3. Motivo de cancelamento processado sem loop
  4. "Trocar o plano" no meio do agendamento → correção, não cancelamento
  5. "Acertar no consultório" → explicar política de pagamento antecipado
  6. Saudação após fluxo de cancelamento travado → resetar goal
  7. Respostas alucinadas bloqueadas no _resposta_livre
  8. Correção de plano com valor None reseta estado dependente
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _state_agendamento_sem_consulta() -> dict:
    """Paciente no meio do agendamento, SEM consulta no Dietbox."""
    return {
        "goal": "agendar_consulta",
        "status": "aguardando_pagamento",
        "phone": "5531999990000",
        "phone_hash": "hash001",
        "tipo_remarcacao": None,
        "last_action": "await_payment",
        "collected_data": {
            "nome": "Breno Alvim",
            "status_paciente": "novo",
            "objetivo": "emagrecer",
            "plano": "premium",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manha"},
            "forma_pagamento": "pix",
            "data_nascimento": None,
            "email": None,
            "instagram": None,
            "profissao": None,
            "cep_endereco": None,
            "indicacao_origem": None,
            "motivo_cancelamento": None,
        },
        "appointment": {
            "slot_escolhido": {
                "datetime": "2026-04-27T19:00:00",
                "data_fmt": "segunda, 27/04",
                "hora": "19h",
            },
            "id_paciente": None,
            "id_agenda": None,       # SEM consulta agendada
            "id_transacao": None,
            "consulta_atual": None,   # SEM consulta existente
        },
        "flags": {
            "upsell_oferecido": True,
            "planos_enviados": True,
            "pagamento_confirmado": False,
            "aguardando_motivo_cancel": False,
        },
        "last_slots_offered": [
            {"datetime": "2026-04-27T19:00:00", "data_fmt": "segunda, 27/04", "hora": "19h"},
        ],
        "slots_pool": [],
        "rodada_negociacao": 0,
        "history": [
            {"role": "assistant", "content": "Segue a chave PIX para pagamento..."},
        ],
    }


def _state_com_consulta_existente() -> dict:
    """Paciente COM consulta agendada no Dietbox."""
    state = _state_agendamento_sem_consulta()
    state["appointment"]["id_agenda"] = "agenda-123"
    state["appointment"]["consulta_atual"] = {
        "id": "agenda-123",
        "inicio": "2026-04-27T19:00:00",
    }
    return state


def _state_cancelamento_aguardando_motivo() -> dict:
    """Paciente no fluxo de cancelamento, já pediu motivo."""
    state = _state_com_consulta_existente()
    state["goal"] = "cancelar"
    state["flags"]["aguardando_motivo_cancel"] = True
    state["last_action"] = "ask_motivo_cancelamento"
    state["history"].append({"role": "assistant", "content": "Qual foi o motivo?"})
    state["history"].append({"role": "user", "content": "muito caro"})
    return state


def _turno_cancelar() -> dict:
    return {
        "intent": "cancelar",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": False,
        "valor_comprovante": None,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
        "_raw_message": "quero desistir",
    }


def _turno_fora_contexto(msg: str = "Oi") -> dict:
    return {
        "intent": "fora_de_contexto",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": False,
        "valor_comprovante": None,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
        "_raw_message": msg,
    }


# ── Teste 1: Desistir SEM consulta → abandon_process ─────────────────────


@pytest.mark.asyncio
async def test_desistir_sem_consulta_retorna_abandon_process():
    """Paciente sem consulta agendada diz 'quero desistir' → encerra graciosamente."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    turno = _turno_cancelar()

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "abandon_process"
    assert plano["new_status"] == "concluido"
    assert plano.get("draft_message") is not None
    assert "sem problemas" in plano["draft_message"].lower() or "tudo bem" in plano["draft_message"].lower()


@pytest.mark.asyncio
async def test_desistir_sem_consulta_nao_envia_politica():
    """abandon_process não deve gerar mensagem com política de cancelamento."""
    from app.conversation.responder import gerar_resposta

    state = _state_agendamento_sem_consulta()
    plano = {
        "action": "abandon_process",
        "tool": None,
        "params": {},
        "ask_context": None,
        "new_status": "concluido",
        "update_data": {},
        "update_appointment": {},
        "update_flags": {},
        "meta": {},
        "draft_message": "Tudo bem, sem problemas! 😊\n\nSe mudar de ideia, é só me chamar 💚",
    }

    respostas = await gerar_resposta(state, plano, None)

    assert len(respostas) >= 1
    texto_completo = " ".join(str(r) for r in respostas)
    assert "Política de cancelamento" not in texto_completo
    assert "24h de antecedência" not in texto_completo


# ── Teste 2: Cancelar COM consulta → pede motivo + política ──────────────


@pytest.mark.asyncio
async def test_cancelar_com_consulta_pede_motivo():
    """Paciente com consulta diz cancelar → ask_motivo_cancelamento."""
    from app.conversation.planner import decidir_acao

    state = _state_com_consulta_existente()
    turno = _turno_cancelar()

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_motivo_cancelamento"
    assert plano["update_flags"]["aguardando_motivo_cancel"] is True


@pytest.mark.asyncio
async def test_cancelar_com_consulta_envia_politica():
    """ask_motivo_cancelamento com consulta existente DEVE enviar política."""
    from app.conversation.responder import gerar_resposta

    state = _state_com_consulta_existente()
    plano = {
        "action": "ask_motivo_cancelamento",
        "tool": None,
        "params": {},
        "ask_context": None,
        "new_status": None,
        "update_data": {},
        "update_appointment": {},
        "update_flags": {"aguardando_motivo_cancel": True},
        "meta": {},
        "draft_message": None,
    }

    respostas = await gerar_resposta(state, plano, None)

    texto_completo = " ".join(str(r) for r in respostas)
    assert "Política de cancelamento" in texto_completo or "cancelamento" in texto_completo.lower()


# ── Teste 3: Motivo de cancelamento processado → avança sem loop ─────────


@pytest.mark.asyncio
async def test_motivo_cancelamento_avanca_para_executar_cancelar():
    """Após dar motivo, planner deve avançar para executar tool cancelar."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    turno = _turno_cancelar()
    turno["_raw_message"] = "muito caro"

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "cancelar"
    assert "motivo" in plano["params"]
    assert plano["params"]["motivo"] == "muito caro"


@pytest.mark.asyncio
async def test_motivo_cancelamento_nao_repete_pergunta():
    """Após dar motivo, NÃO deve repetir ask_motivo_cancelamento."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    turno = _turno_cancelar()

    plano = await decidir_acao(turno, state)

    assert plano["action"] != "ask_motivo_cancelamento"


# ── Teste 4: "Trocar o plano" → correção, não cancelamento ──────────────


@pytest.mark.asyncio
async def test_trocar_plano_gera_correcao_no_interpreter():
    """'Quero trocar o plano' durante agendamento → correcao com plano=null."""
    from app.conversation.interpreter import interpretar_turno

    state = _state_agendamento_sem_consulta()
    state["status"] = "coletando"

    fake_response = MagicMock()
    # LLM pode errar e classificar como remarcar
    fake_response.content = [MagicMock(text='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("quero trocar o plano", state)

    assert turno["intent"] == "agendar"
    assert turno["correcao"] is not None
    assert turno["correcao"]["campo"] == "plano"
    assert turno["correcao"]["valor_novo"] is None


@pytest.mark.asyncio
async def test_trocar_plano_nao_dispara_para_cancelar():
    """'Trocar plano' não deve gerar intent=cancelar."""
    from app.conversation.interpreter import interpretar_turno

    state = _state_agendamento_sem_consulta()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"cancelar","confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("Não quero apenas trocar o plano", state)

    assert turno["intent"] == "agendar"
    assert turno["correcao"]["campo"] == "plano"


@pytest.mark.asyncio
async def test_mudar_plano_variacao():
    """'Mudar o plano' também deve funcionar."""
    from app.conversation.interpreter import interpretar_turno

    state = _state_agendamento_sem_consulta()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"fora_de_contexto","confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("quero mudar a opção", state)

    assert turno["intent"] == "agendar"
    assert turno["correcao"]["campo"] == "plano"


# ── Teste 5: Correção de plano com valor None reseta estado ──────────────


def test_correcao_plano_none_reseta_estado_dependente():
    """Correção plano=None deve limpar plano, forma_pagamento, slots, flags."""
    from app.conversation.state import apply_correction, create_state

    state = create_state("hash001", "5531999990000")
    state["collected_data"]["plano"] = "premium"
    state["collected_data"]["forma_pagamento"] = "pix"
    state["flags"]["planos_enviados"] = True
    state["flags"]["upsell_oferecido"] = True
    state["flags"]["pagamento_confirmado"] = True
    state["last_slots_offered"] = [{"datetime": "2026-05-01T10:00:00"}]
    state["appointment"]["slot_escolhido"] = {"datetime": "2026-05-01T10:00:00"}

    apply_correction(state, "plano", None)

    assert state["collected_data"]["plano"] is None
    assert state["collected_data"]["forma_pagamento"] is None
    assert state["flags"]["planos_enviados"] is False
    assert state["flags"]["upsell_oferecido"] is False
    assert state["flags"]["pagamento_confirmado"] is False
    assert state["last_slots_offered"] == []
    assert state["appointment"]["slot_escolhido"] is None


def test_correcao_plano_com_valor_seta_normalmente():
    """Correção plano='ouro' deve setar normalmente."""
    from app.conversation.state import apply_correction, create_state

    state = create_state("hash001", "5531999990000")
    state["collected_data"]["plano"] = "premium"

    apply_correction(state, "plano", "ouro")

    assert state["collected_data"]["plano"] == "ouro"


# ── Teste 6: "Acertar no consultório" → explica pagamento antecipado ────


@pytest.mark.asyncio
async def test_acertar_no_consultorio_explica_politica():
    """Paciente pede para pagar no consultório → resposta explicando política."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    turno = _turno_fora_contexto("eu acerto o restante no consultório, pode ser?")
    turno["intent"] = "agendar"

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano.get("draft_message") is not None
    assert "antecipado" in plano["draft_message"].lower() or "política" in plano["draft_message"].lower()


@pytest.mark.asyncio
async def test_pagar_na_hora_explica_politica():
    """'posso pagar lá na hora?' → resposta explicando política."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    turno = _turno_fora_contexto("posso pagar lá na hora?")
    turno["intent"] = "agendar"

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert "antecipado" in plano["draft_message"].lower() or "reserva" in plano["draft_message"].lower()


# ── Teste 7: Saudação após cancelamento travado → reseta goal ────────────


@pytest.mark.asyncio
async def test_saudacao_apos_cancelamento_reseta_goal():
    """Paciente diz 'Oi' com goal=cancelar → reseta para desconhecido."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    turno = _turno_fora_contexto("Oi")

    plano = await decidir_acao(turno, state)

    # Não deve continuar no fluxo de cancelamento
    assert plano["action"] != "ask_motivo_cancelamento"
    assert plano["action"] != "execute_tool" or plano.get("tool") != "cancelar"
    # O goal deve ter sido resetado
    assert state["goal"] != "cancelar"


@pytest.mark.asyncio
async def test_saudacao_apos_cancelamento_nao_envia_politica():
    """Saudação após cancelamento NÃO deve enviar política de cancelamento."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    turno = _turno_fora_contexto("Oi")

    plano = await decidir_acao(turno, state)

    assert plano["action"] != "ask_motivo_cancelamento"


@pytest.mark.asyncio
async def test_intent_agendar_apos_cancelamento_reseta():
    """Paciente com goal=cancelar mas intent=agendar → reseta e segue agendamento."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    turno = _turno_fora_contexto("quero agendar uma consulta")
    turno["intent"] = "agendar"

    plano = await decidir_acao(turno, state)

    assert state["goal"] != "cancelar"
    assert plano["action"] != "ask_motivo_cancelamento"


# ── Teste 8: Guardrail da resposta livre ─────────────────────────────────


@pytest.mark.asyncio
async def test_resposta_livre_bloqueia_confirmacao_alucinada():
    """_resposta_livre deve bloquear respostas que parecem confirmações."""
    from app.conversation.responder import _resposta_livre

    state = {
        "collected_data": {"nome": "Breno"},
        "history": [
            {"role": "user", "content": "Oi"},
            {"role": "assistant", "content": "Como posso ajudar?"},
            {"role": "user", "content": "quero remarcar"},
        ],
    }

    fake_response = MagicMock()
    fake_response.content = [MagicMock(
        text="✅ Consulta remarcada com sucesso!\n\n📅 Nova data: segunda, 27/04 às 19h"
    )]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.responder.anthropic.Anthropic", return_value=fake_client):
        resultado = await _resposta_livre(state)

    # Deve ter sido bloqueada e retornar mensagem genérica
    assert "remarcada com sucesso" not in resultado
    assert "confirmada" not in resultado.lower() or "ajudar" in resultado.lower()


@pytest.mark.asyncio
async def test_resposta_livre_permite_resposta_normal():
    """_resposta_livre deve permitir respostas normais."""
    from app.conversation.responder import _resposta_livre

    state = {
        "collected_data": {"nome": "Breno"},
        "history": [
            {"role": "user", "content": "qual o endereço?"},
        ],
    }

    fake_response = MagicMock()
    fake_response.content = [MagicMock(
        text="A Aura Clinic fica na Rua Melo Franco, 204 em Vespasiano 😊"
    )]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.responder.anthropic.Anthropic", return_value=fake_client):
        resultado = await _resposta_livre(state)

    assert "Aura Clinic" in resultado


# ── Teste 9: Cenário completo do bug report ──────────────────────────────


@pytest.mark.asyncio
async def test_cenario_desistir_durante_pagamento_novo_paciente():
    """
    Cenário real do bug: paciente novo diz 'quero desistir' durante
    aguardando_pagamento, sem ter consulta no sistema.
    Deve encerrar sem pedir motivo e sem enviar política.
    """
    from app.conversation.planner import decidir_acao
    from app.conversation.responder import gerar_resposta

    state = _state_agendamento_sem_consulta()
    turno = _turno_cancelar()
    turno["_raw_message"] = "quero desistir"

    # Planner decide
    plano = await decidir_acao(turno, state)
    assert plano["action"] == "abandon_process"

    # Responder gera
    respostas = await gerar_resposta(state, plano, None)
    texto_completo = " ".join(str(r) for r in respostas)

    assert "Política de cancelamento" not in texto_completo
    assert "24h de antecedência" not in texto_completo
    assert len(respostas) == 1  # Apenas uma mensagem, não duas


@pytest.mark.asyncio
async def test_cenario_trocar_plano_retorna_ao_fluxo():
    """
    Cenário real: paciente diz 'quero trocar o plano' no meio do agendamento.
    Deve resetar plano e re-perguntar, não cancelar/remarcar.
    """
    from app.conversation.planner import decidir_acao
    from app.conversation.state import apply_correction

    state = _state_agendamento_sem_consulta()
    state["status"] = "coletando"

    # Simular a correção que o engine aplicaria
    apply_correction(state, "plano", None)

    # Verificar que o estado foi limpo
    assert state["collected_data"]["plano"] is None
    assert state["flags"]["planos_enviados"] is False

    # Agora o planner deve enviar planos novamente
    turno = {
        "intent": "agendar",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": False,
        "valor_comprovante": None,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
        "_raw_message": "quero trocar o plano",
    }

    plano = await decidir_acao(turno, state)
    assert plano["action"] == "send_planos"
