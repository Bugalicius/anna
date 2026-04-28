import pytest


def _state_retorno():
    from app.conversation.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "remarcar"
    state["tipo_remarcacao"] = "retorno"
    state["fim_janela_remarcar"] = "2026-05-01"
    state["appointment"]["id_agenda"] = "AGENDA-123"
    state["appointment"]["consulta_atual"] = {
        "id": "AGENDA-123",
        "inicio": "2026-04-24T09:00:00",
    }
    return state


@pytest.mark.asyncio
async def test_remarcacao_pede_preferencia_com_tom_humano_sem_menu_agendamento():
    from app.conversation.planner import decidir_acao
    from app.conversation.responder import gerar_resposta

    state = _state_retorno()
    turno = {
        "intent": "remarcar",
        "preferencia_horario": None,
        "escolha_slot": None,
    }

    plano = await decidir_acao(turno, state)
    respostas = await gerar_resposta(state, plano, None)
    texto = " ".join(r for r in respostas if isinstance(r, str))

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "preferencia_horario_remarcar"
    assert "sem problema" in texto.lower() or "te ajudar" in texto.lower()
    assert "para seguirmos com o agendamento" not in texto.lower()
    assert "pagamento" not in texto.lower()


@pytest.mark.asyncio
async def test_remarcacao_com_preferencia_consulta_slots_sem_reiniciar_agendamento():
    from app.conversation.planner import decidir_acao

    state = _state_retorno()
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "turno",
        "turno": "tarde",
        "hora": None,
        "dia_semana": None,
        "descricao": "prefere tarde",
    }
    turno = {
        "intent": "remarcar",
        "preferencia_horario": state["collected_data"]["preferencia_horario"],
        "escolha_slot": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "consultar_slots_remarcar"
    assert plano["params"]["preferencia"]["turno"] == "tarde"


@pytest.mark.asyncio
async def test_remarcacao_rejeita_slots_com_nova_preferencia_busca_outra_janela():
    from app.conversation.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "consultar_slots_remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "turno",
        "turno": "manha",
        "hora": None,
        "dia_semana": None,
        "descricao": "prefere manhã",
    }
    state["last_slots_offered"] = [
        {"datetime": "2026-04-28T09:00:00", "data_fmt": "terça, 28/04", "hora": "9h"},
        {"datetime": "2026-04-29T10:00:00", "data_fmt": "quarta, 29/04", "hora": "10h"},
    ]
    turno = {
        "intent": "remarcar",
        "escolha_slot": None,
        "preferencia_horario": {
            "tipo": "turno",
            "turno": "noite",
            "hora": None,
            "dia_semana": None,
            "descricao": "agora prefere noite",
        },
    }

    plano = await decidir_acao(turno, state)

    assert plano["tool"] == "consultar_slots_remarcar"
    assert plano["params"]["preferencia"]["turno"] == "noite"
    assert state["last_slots_offered"] == []
    assert state["rodada_negociacao"] == 0


@pytest.mark.asyncio
async def test_confirmacao_remarcacao_usa_prontinho_e_data():
    from app.conversation.responder import gerar_resposta

    state = _state_retorno()
    state["appointment"]["slot_escolhido"] = {
        "datetime": "2026-04-30T18:00:00",
        "data_fmt": "quinta, 30/04",
        "hora": "18h",
    }
    state["collected_data"]["modalidade"] = "online"

    respostas = await gerar_resposta(
        state,
        {"action": "send_confirmacao_remarcacao"},
        None,
    )
    texto = " ".join(respostas)

    assert "Prontinho" in texto
    assert "30/04" in texto
    assert "18h" in texto
