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


@pytest.mark.asyncio
async def test_interpreter_lista_planos_extrai_id_curto():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"agendar","plano":null,"confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("ouro", state)

    assert turno["plano"] == "ouro"
    assert turno["intent"] == "agendar"


@pytest.mark.asyncio
async def test_interpreter_texto_visivel_do_slot_resolve_escolha():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"fora_de_contexto","escolha_slot":null,"confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("terça, 05/05 15h", state)

    assert turno["escolha_slot"] == 2
    assert turno["intent"] == "fora_de_contexto"


@pytest.mark.asyncio
async def test_interpreter_midia_em_pagamento_confirma_pagamento():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()
    state["status"] = "aguardando_pagamento"
    state["collected_data"]["forma_pagamento"] = "pix"
    state["last_action"] = "await_payment"

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"fora_de_contexto","confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("[comprovante valor=240.00 favorecido=Thaynara]", state)

    assert turno["confirmou_pagamento"] is True
    assert turno["intent"] == "confirmar_pagamento"
    assert turno["valor_comprovante"] == 240.0


@pytest.mark.asyncio
async def test_interpreter_extrai_email_e_data_nascimento_do_cadastro():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"agendar","confirmou_pagamento":false,"tem_pergunta":false,"email":null,"data_nascimento":null}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    msg = "Meu e-mail é breno@email.com e nasci em 20/04/1990"
    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno(msg, state)

    assert turno["email"] == "breno@email.com"
    assert turno["data_nascimento"] == "1990-04-20"


@pytest.mark.asyncio
async def test_interpreter_extrai_data_nascimento_em_formato_curto():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"agendar","confirmou_pagamento":false,"tem_pergunta":false,"data_nascimento":null}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("nasci em 2/3/93", state)

    assert turno["data_nascimento"] == "1993-03-02"


@pytest.mark.asyncio
async def test_interpreter_alterar_consulta_forca_remarcacao_mesmo_se_llm_cancelar():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "desconhecido"

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"cancelar","confirmou_pagamento":false,"tem_pergunta":false}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("quero alterar a minha consulta", state)

    assert turno["intent"] == "remarcar"


@pytest.mark.asyncio
async def test_interpreter_outros_horarios_amplia_preferencia():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "turno",
        "turno": "manha",
        "descricao": "manhã",
    }

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false,"preferencia_horario":null}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("na semana do dia 11 só tem esses dois horários? nao tem nenhum outro?", state)

    assert turno["preferencia_horario"]["tipo"] == "qualquer"
    assert turno["correcao"]["campo"] == "preferencia_horario"


@pytest.mark.asyncio
async def test_interpreter_texto_horario_visivel_extrai_hora_e_dia():
    from app.conversation.interpreter import interpretar_turno

    state = _state_base()
    state["goal"] = "remarcar"
    state["last_slots_offered"] = []

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"intent":"remarcar","confirmou_pagamento":false,"tem_pergunta":false,"preferencia_horario":null}')]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch("app.conversation.interpreter.anthropic.Anthropic", return_value=fake_client):
        turno = await interpretar_turno("segunda, 11/05 17h", state)

    assert turno["preferencia_horario"]["tipo"] == "hora_especifica"
    assert turno["preferencia_horario"]["hora"] == "17h"
    assert turno["preferencia_horario"]["dia_semana"] == 0
