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

from unittest.mock import patch

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


@pytest.mark.asyncio
async def test_preferencia_horario_ignora_draft_generico_do_planner():
    """Pergunta de preferência de horário deve usar tabela fixa, não texto livre do planner."""
    from app.conversation.responder import gerar_resposta

    state = _state_agendamento_sem_consulta()
    state["history"] = [
        {"role": "user", "content": "quero marcar uma consulta presencial"},
        {"role": "assistant", "content": "Claro"},
    ]
    state["collected_data"]["preferencia_horario"] = None
    plano = {
        "action": "ask_field",
        "ask_context": "preferencia_horario",
        "draft_message": (
            "Ótimo, Ana! Para agendar sua consulta, qual sua preferência de horário? "
            "(manhã, tarde ou flexível?)"
        ),
    }

    respostas = await gerar_resposta(state, plano, resultado_tool=None)

    r = respostas[0]
    # Agora retorna botões interativos em vez de lista de horários
    assert isinstance(r, dict) and r.get("_interactive") == "button"
    assert "turno" in r["body"].lower()
    assert any(b["id"] == "manha" for b in r["buttons"])
    assert any(b["id"] == "tarde" for b in r["buttons"])
    assert any(b["id"] == "noite" for b in r["buttons"])


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


@pytest.mark.asyncio
async def test_cancelamento_com_reembolso_ou_conflito_escala_sem_executar_tool():
    """Pedido de reembolso/conflito no motivo deve ir para humano, não tentar cancelar."""
    from app.conversation.planner import decidir_acao

    state = _state_cancelamento_aguardando_motivo()
    state["history"][-1]["content"] = "vc é muito burro. queor meu dinheiro de volta"
    turno = _turno_cancelar()
    turno["_raw_message"] = "vc é muito burro. queor meu dinheiro de volta"

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "escalate"
    assert plano.get("tool") is None
    assert plano["update_data"]["motivo_cancelamento"] == "vc é muito burro. queor meu dinheiro de volta"


# ── Teste 4: "Trocar o plano" → correção, não cancelamento ──────────────


@pytest.mark.asyncio
async def test_trocar_plano_gera_correcao_no_interpreter():
    """'Quero trocar o plano' durante agendamento → correcao com plano=null."""
    from app.conversation.interpreter import interpretar_turno

    state = _state_agendamento_sem_consulta()
    state["status"] = "coletando"

    # LLM pode errar e classificar como remarcar
    with patch("app.conversation.interpreter.llm_client.complete_text", return_value='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false}'):
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

    with patch("app.conversation.interpreter.llm_client.complete_text", return_value='{"intent":"cancelar","confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("Não quero apenas trocar o plano", state)

    assert turno["intent"] == "agendar"
    assert turno["correcao"]["campo"] == "plano"


@pytest.mark.asyncio
async def test_mudar_plano_variacao():
    """'Mudar o plano' também deve funcionar."""
    from app.conversation.interpreter import interpretar_turno

    state = _state_agendamento_sem_consulta()

    with patch("app.conversation.interpreter.llm_client.complete_text", return_value='{"intent":"fora_de_contexto","confirmou_pagamento":false,"tem_pergunta":false}'):
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


@pytest.mark.asyncio
async def test_horario_funcionamento_responde_sem_escalar():
    """Pergunta operacional sobre funcionamento não pode virar escalação."""
    from app.conversation.planner import decidir_acao
    from app.conversation.responder import gerar_resposta
    from app.conversation.state import create_state

    state = create_state("hash", "553186687010")
    state["history"] = [
        {"role": "user", "content": "Oi"},
        {"role": "assistant", "content": "Oi oi! Como posso te ajudar hoje? 💚"},
        {"role": "user", "content": "Qual horário de funcionamento?"},
    ]
    turno = _turno_fora_contexto("Qual horário de funcionamento?")
    turno["intent"] = "duvida_clinica"  # simula alucinação do interpretador/LLM
    turno["tem_pergunta"] = True
    turno["topico_pergunta"] = "clinica"

    plano = await decidir_acao(turno, state)
    respostas = await gerar_resposta(state, plano, None)
    texto = " ".join(r for r in respostas if isinstance(r, str)).lower()

    assert plano["action"] == "answer_question"
    assert plano["ask_context"] == "horarios"
    assert "segunda a quinta" in texto
    assert "sábado" in texto or "sabados" in texto


@pytest.mark.asyncio
async def test_como_e_atendimento_thaynara_responde_sem_escalar():
    """Pergunta sobre o atendimento da profissional não é dúvida clínica."""
    from app.conversation.planner import decidir_acao
    from app.conversation.responder import gerar_resposta
    from app.conversation.state import create_state

    state = create_state("hash", "553186687010")
    state["history"] = [
        {"role": "user", "content": "Oi"},
        {"role": "assistant", "content": "Oi oi! Como posso te ajudar hoje? 💚"},
        {"role": "user", "content": "Como é o atendimento da Thaynara?"},
    ]
    turno = _turno_fora_contexto("Como é o atendimento da Thaynara?")
    turno["intent"] = "duvida_clinica"
    turno["tem_pergunta"] = True
    turno["topico_pergunta"] = "clinica"

    plano = await decidir_acao(turno, state)
    respostas = await gerar_resposta(state, plano, None)
    texto = " ".join(r for r in respostas if isinstance(r, str)).lower()

    assert plano["action"] == "answer_question"
    assert plano["ask_context"] == "atendimento_profissional"
    assert "nutritransforma" in texto
    assert "presencial" in texto
    assert "online" in texto


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

    with patch("app.conversation.responder.llm_client.complete_text", return_value="✅ Consulta remarcada com sucesso!\n\n📅 Nova data: segunda, 27/04 às 19h"):
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

    with patch("app.conversation.responder.llm_client.complete_text_async", return_value="A Aura Clinic fica na Rua Melo Franco, 204 em Vespasiano 😊"):
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


@pytest.mark.asyncio
async def test_pergunta_reputacao_nao_escala_duvida_clinica():
    """Pergunta sobre conhecer a profissional/depoimentos não deve enviar contato da nutri."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    state["goal"] = "desconhecido"
    state["collected_data"]["nome"] = None
    state["collected_data"]["status_paciente"] = None

    turno = {
        "intent": "duvida_clinica",
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
        "tem_pergunta": True,
        "topico_pergunta": "clinica",
        "preferencia_horario": None,
        "_raw_message": "você conhece a thaynara a muito tempo? o que os pacientes dizem dela?",
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano["action"] != "escalate"
    assert "depoimentos individuais" in plano["draft_message"]


@pytest.mark.asyncio
async def test_nova_consulta_sai_do_loop_de_remarcacao_nao_localizada():
    """Pedido explícito de nova consulta deve limpar remarcação não localizada."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    state["goal"] = "remarcar"
    state["tipo_remarcacao"] = "nao_localizado"
    state["appointment"]["consulta_atual"] = None
    state["appointment"]["id_agenda"] = None
    state["collected_data"]["status_paciente"] = "retorno"
    state["collected_data"]["objetivo"] = None

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
        "_raw_message": "quero agendar uma nova consulta",
    }

    plano = await decidir_acao(turno, state)

    assert state["goal"] == "agendar_consulta"
    assert state["tipo_remarcacao"] == "nova_consulta"
    assert state["collected_data"]["status_paciente"] == "novo"
    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "objetivo"


@pytest.mark.asyncio
async def test_paciente_retorno_ao_escolher_plano_nao_dispara_dietbox():
    """Escolha explícita de plano no menu deve seguir agendamento, sem detectar remarcação."""
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    state["goal"] = "agendar_consulta"
    state["tipo_remarcacao"] = None
    state["collected_data"]["status_paciente"] = "retorno"
    state["collected_data"]["plano"] = "com_retorno"
    state["collected_data"]["modalidade"] = None
    state["flags"]["upsell_oferecido"] = False
    state["appointment"]["consulta_atual"] = None
    state["appointment"]["id_agenda"] = None

    turno = {
        "intent": "agendar",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": "com_retorno",
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
        "_raw_message": "com_retorno",
    }

    plano = await decidir_acao(turno, state)

    assert plano["tool"] != "detectar_tipo_remarcacao"
    assert plano["action"] == "offer_upsell"
    assert plano["ask_context"] == "com_retorno"
    assert state["tipo_remarcacao"] == "nova_consulta"
    assert state["collected_data"]["status_paciente"] == "novo"


def test_engine_agendar_nova_consulta_reseta_goal_remarcar():
    """O motor deve persistir a troca de goal antes do planner."""
    from app.conversation.engine import ConversationEngine

    engine = ConversationEngine()
    state = _state_agendamento_sem_consulta()
    state["goal"] = "remarcar"
    state["tipo_remarcacao"] = "nao_localizado"
    state["appointment"]["id_agenda"] = "agenda-antiga"
    state["appointment"]["consulta_atual"] = {"id": "agenda-antiga"}
    state["collected_data"]["status_paciente"] = "retorno"

    engine._atualizar_goal(
        state,
        {"intent": "agendar", "_raw_message": "quero agendar uma nova consulta"},
    )

    assert state["goal"] == "agendar_consulta"
    assert state["tipo_remarcacao"] == "nova_consulta"
    assert state["appointment"]["id_agenda"] is None
    assert state["appointment"]["consulta_atual"] is None
    assert state["collected_data"]["status_paciente"] == "novo"


@pytest.mark.asyncio
async def test_gestante_recebe_recusa_de_atendimento():
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    turno = {
        "intent": "tirar_duvida",
        "tem_pergunta": True,
        "topico_pergunta": "politica",
        "_raw_message": "estou grávida, consigo consultar?",
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano["new_status"] == "concluido"
    assert "gestantes" in plano["draft_message"]


@pytest.mark.asyncio
async def test_menor_de_16_recebe_recusa_de_atendimento():
    from app.conversation.planner import decidir_acao

    state = _state_agendamento_sem_consulta()
    turno = {
        "intent": "tirar_duvida",
        "tem_pergunta": True,
        "topico_pergunta": "politica",
        "_raw_message": "tenho 15 anos, posso marcar?",
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert "menores de 16" in plano["draft_message"]
