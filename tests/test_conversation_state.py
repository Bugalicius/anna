from __future__ import annotations


def test_apply_tool_result_nova_consulta_converte_goal_de_remarcacao():
    from app.conversation.state import apply_tool_result, create_state

    state = create_state("hash123", "5531999999999")
    state["goal"] = "remarcar"
    state["collected_data"]["status_paciente"] = "retorno"
    state["appointment"]["consulta_atual"] = {"id": "agenda-antiga"}
    state["appointment"]["id_agenda"] = "agenda-antiga"

    apply_tool_result(
        state,
        "detectar_tipo_remarcacao",
        {"tipo_remarcacao": "nova_consulta"},
    )

    assert state["tipo_remarcacao"] == "nova_consulta"
    assert state["goal"] == "agendar_consulta"
    assert state["collected_data"]["status_paciente"] == "novo"
    assert state["appointment"]["consulta_atual"] is None
    assert state["appointment"]["id_agenda"] is None
