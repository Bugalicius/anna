from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _state_base() -> dict:
    return {
        "goal": "agendar_consulta",
        "status": "coletando",
        "collected_data": {
            "nome": "Breno Alvim",
            "status_paciente": "novo",
            "objetivo": "emagrecer",
            "plano": "unica",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "qualquer", "descricao": "qualquer horário"},
            "forma_pagamento": None,
            "motivo_cancelamento": None,
        },
        "appointment": {
            "slot_escolhido": {
                "datetime": "2026-05-04T10:00:00",
                "data_fmt": "segunda, 04/05",
                "hora": "10h",
            },
            "id_paciente": None,
            "id_agenda": None,
            "id_transacao": None,
            "consulta_atual": None,
        },
        "flags": {
            "upsell_oferecido": True,
            "planos_enviados": True,
            "pagamento_confirmado": False,
            "aguardando_motivo_cancel": False,
        },
        "last_action": "ask_forma_pagamento",
        "last_slots_offered": [
            {"datetime": "2026-05-04T10:00:00", "data_fmt": "segunda, 04/05", "hora": "10h"},
            {"datetime": "2026-05-05T15:00:00", "data_fmt": "terça, 05/05", "hora": "15h"},
            {"datetime": "2026-05-06T19:00:00", "data_fmt": "quarta, 06/05", "hora": "19h"},
        ],
        "history": [
            {"role": "assistant", "content": "Qual horário funciona melhor pra você?"},
            {"role": "user", "content": "slot_1"},
            {"role": "assistant", "content": "Qual opção prefere? PIX ou cartão?"},
        ],
    }


@pytest.mark.asyncio
async def test_interpreter_button_slot_id_nao_quebra_e_extrai_escolha():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"agendar","escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("slot_2", state)

    assert turno["escolha_slot"] == 2


@pytest.mark.asyncio
async def test_interpreter_pix_button_no_fluxo_extrai_forma_pagamento():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"agendar","forma_pagamento":null,"escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("pix", state)

    assert turno["forma_pagamento"] == "pix"
    assert turno["intent"] == "agendar"
