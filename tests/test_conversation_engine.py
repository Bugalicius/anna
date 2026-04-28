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
    from app.conversation.engine import ConversationEngine

    state = _state()
    plano = {"action": "send_confirmacao", "new_status": "concluido"}

    with patch("app.conversation.engine.load_state", new_callable=AsyncMock, return_value=state), \
         patch("app.conversation.engine.interpretar_turno", new_callable=AsyncMock, return_value={"intent": "agendar"}), \
         patch("app.conversation.engine.decidir_acao", new_callable=AsyncMock, return_value=plano), \
         patch("app.conversation.engine.gerar_resposta", new_callable=AsyncMock, return_value=["ok"]), \
         patch("app.conversation.engine.save_state", new_callable=AsyncMock) as mock_save:
        respostas = await ConversationEngine().handle_message("hash123", "ok", phone="5511999")

    assert respostas == ["ok"]
    mock_save.assert_awaited_once()
    saved_state = mock_save.await_args.args[1]
    assert saved_state["status"] == "concluido"
