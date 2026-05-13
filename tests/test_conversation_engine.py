from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


def _state() -> dict:
    return {
        "phone_hash": "hash123",
        "phone": "5511999",
        "goal": "agendar_consulta",
        "status": "coletando",
        "collected_data": {"nome": "Ana Maria"},
        "appointment": {"id_agenda": "agenda-1"},
        "flags": {},
        "history": [],
        "last_action": None,
        "last_slots_offered": [],
    }


@pytest.mark.asyncio
async def test_engine_salva_estado_concluido_para_router_persistir_contato():
    from app.conversation_legacy.engine import ConversationEngine

    state = _state()
    plano = {"action": "send_confirmacao", "new_status": "concluido"}

    with patch("app.conversation_legacy.engine.load_state", new_callable=AsyncMock, return_value=state), \
         patch("app.conversation_legacy.engine.interpretar_turno", new_callable=AsyncMock, return_value={"intent": "agendar"}), \
         patch("app.conversation_legacy.engine.decidir_acao", new_callable=AsyncMock, return_value=plano), \
         patch("app.conversation_legacy.engine.gerar_resposta", new_callable=AsyncMock, return_value=["ok"]), \
         patch("app.conversation_legacy.engine.save_state", new_callable=AsyncMock) as mock_save:
        respostas = await ConversationEngine().handle_message("hash123", "ok", phone="5511999")

    assert respostas == ["ok"]
    mock_save.assert_awaited_once()
    saved_state = mock_save.await_args.args[1]
    assert saved_state["status"] == "concluido"


def test_apply_tool_result_remarcacao_sucesso_conclui_estado():
    from app.conversation_legacy.state import apply_tool_result

    state = _state()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = [{"datetime": "2026-05-11T17:00:00"}]
    state["slots_pool"] = [{"datetime": "2026-05-11T17:00:00"}]

    apply_tool_result(state, "remarcar_dietbox", {"sucesso": True})

    assert state["status"] == "concluido"
    assert state["last_tool_success"] is True
    assert state["last_slots_offered"] == []
    assert state["slots_pool"] == []
