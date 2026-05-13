from __future__ import annotations

from unittest.mock import patch

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
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"agendar","escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("slot_2", state)

    assert turno["escolha_slot"] == 2


@pytest.mark.asyncio
async def test_interpreter_pix_button_no_fluxo_extrai_forma_pagamento():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"agendar","forma_pagamento":null,"escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("pix", state)

    assert turno["forma_pagamento"] == "pix"
    assert turno["intent"] == "agendar"


@pytest.mark.asyncio
async def test_interpreter_lista_planos_extrai_id_curto():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"agendar","plano":null,"confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("ouro", state)

    assert turno["plano"] == "ouro"
    assert turno["intent"] == "agendar"


@pytest.mark.asyncio
async def test_interpreter_texto_visivel_do_slot_resolve_escolha():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"fora_de_contexto","escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("terça, 05/05 15h", state)

    assert turno["escolha_slot"] == 2
    assert turno["intent"] == "agendar"


@pytest.mark.asyncio
async def test_interpreter_slot_visivel_prioriza_escolha_sobre_preferencia():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "qualquer",
        "turno": None,
        "hora": None,
        "dia_semana": None,
        "descricao": "qualquer horario",
    }
    state["last_slots_offered"] = [
        {"datetime": "2026-05-11T17:00:00", "data_fmt": "segunda, 11/05", "hora": "17h"},
    ]

    with patch(
        "app.conversation_legacy.interpreter.llm_client.complete_text",
        return_value=(
            '{"intent":"remarcar","escolha_slot":null,"confirmou_pagamento":false,'
            '"tem_pergunta":false,"preferencia_horario":null}'
        ),
    ):
        turno = await interpretar_turno("segunda, 11/05 17h", state)

    assert turno["escolha_slot"] == 1
    assert turno["preferencia_horario"] is None
    assert turno["correcao"] is None


@pytest.mark.asyncio
async def test_interpreter_fallback_com_erro_llm_preserva_slots_do_estado():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = [
        {"datetime": "2026-05-25T08:00:00", "data_fmt": "segunda, 25/05", "hora": "8h"},
    ]

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", side_effect=RuntimeError("sem credito")):
        turno = await interpretar_turno("segunda, 25/05 8h", state)

    assert turno["intent"] == "remarcar"
    assert turno["escolha_slot"] == 1
    assert turno["preferencia_horario"] is None
    assert turno["correcao"] is None


@pytest.mark.asyncio
async def test_interpreter_remarcacao_clara_nao_chama_llm():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text") as mock_complete:
        turno = await interpretar_turno("quero remarcar minha consulta", state)

    assert turno["intent"] == "remarcar"
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_interpreter_preferencia_remarcacao_nao_chama_llm():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = []

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text") as mock_complete:
        turno = await interpretar_turno("qualquer horário na semana seguinte", state)

    assert turno["preferencia_horario"]["tipo"] == "qualquer"
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_interpreter_escolha_slot_nao_chama_llm():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = [
        {"datetime": "2026-05-25T08:00:00", "data_fmt": "segunda, 25/05", "hora": "8h"},
    ]

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text") as mock_complete:
        turno = await interpretar_turno("segunda, 25/05 8h", state)

    assert turno["escolha_slot"] == 1
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_interpreter_midia_em_pagamento_confirma_pagamento():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["status"] = "aguardando_pagamento"
    state["collected_data"]["forma_pagamento"] = "pix"
    state["last_action"] = "await_payment"

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"fora_de_contexto","confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("[comprovante valor=240.00 favorecido=Thaynara]", state)

    assert turno["confirmou_pagamento"] is True
    assert turno["intent"] == "confirmar_pagamento"
    assert turno["valor_comprovante"] == 240.0


@pytest.mark.asyncio
async def test_interpreter_extrai_email_e_data_nascimento_do_cadastro():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    msg = "Meu e-mail é breno@email.com e nasci em 20/04/1990"
    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"agendar","confirmou_pagamento":false,"tem_pergunta":false,"email":null,"data_nascimento":null}'):
        turno = await interpretar_turno(msg, state)

    assert turno["email"] == "breno@email.com"
    assert turno["data_nascimento"] == "1990-04-20"


@pytest.mark.asyncio
async def test_interpreter_extrai_data_nascimento_em_formato_curto():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"agendar","confirmou_pagamento":false,"tem_pergunta":false,"data_nascimento":null}'):
        turno = await interpretar_turno("nasci em 2/3/93", state)

    assert turno["data_nascimento"] == "1993-03-02"


@pytest.mark.asyncio
async def test_interpreter_alterar_consulta_forca_remarcacao_mesmo_se_llm_cancelar():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "desconhecido"

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"cancelar","confirmou_pagamento":false,"tem_pergunta":false}'):
        turno = await interpretar_turno("quero alterar a minha consulta", state)

    assert turno["intent"] == "remarcar"


@pytest.mark.asyncio
async def test_interpreter_outros_horarios_amplia_preferencia():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "turno",
        "turno": "manha",
        "descricao": "manhã",
    }

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false,"preferencia_horario":null}'):
        turno = await interpretar_turno("na semana do dia 11 só tem esses dois horários? nao tem nenhum outro?", state)

    assert turno["preferencia_horario"]["tipo"] == "qualquer"
    assert turno["correcao"]["campo"] == "preferencia_horario"


@pytest.mark.asyncio
async def test_interpreter_texto_horario_visivel_extrai_hora_e_dia():
    from app.conversation_legacy.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = []

    with patch("app.conversation_legacy.interpreter.llm_client.complete_text", return_value='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false,"preferencia_horario":null}'):
        turno = await interpretar_turno("segunda, 11/05 17h", state)

    assert turno["preferencia_horario"]["tipo"] == "hora_especifica"
    assert turno["preferencia_horario"]["hora"] == "17h"
    assert turno["preferencia_horario"]["dia_semana"] == 0
