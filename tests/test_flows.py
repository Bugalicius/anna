import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.flows import get_flow_response, FLOWS


def test_planos_list_builder_retorna_lista_curta():
    from app.conversation_legacy.responder import _build_planos_list

    response = _build_planos_list()

    assert response["_interactive"] == "list"
    assert "Hoje temos estas opções" in response["body"]
    assert [row["id"] for row in response["rows"]] == ["premium", "ouro", "com_retorno", "unica"]
    assert response["rows"][0]["title"] == "Premium - 6 consultas"
    assert response["rows"][1]["title"] == "Ouro - 3 consultas"


def test_modalidade_list_builder_retorna_lista():
    from app.conversation_legacy.responder import _build_modalidade_list

    response = _build_modalidade_list()

    assert response["_interactive"] == "button"
    assert "como você prefere fazer sua consulta" in response["body"]
    assert [button["id"] for button in response["buttons"]] == ["presencial", "online"]


@pytest.mark.asyncio
async def test_planner_pix_em_contexto_de_pagamento_nao_reinicia_fluxo():
    from app.conversation_legacy.planner import decidir_acao

    state = {
        "goal": "agendar_consulta",
        "status": "aguardando_pagamento",
        "phone": "5531999990000",
        "phone_hash": "hash001",
        "tipo_remarcacao": None,
        "last_action": "gerar_link_cartao",
        "collected_data": {
            "nome": "Breno Alvim",
            "status_paciente": "novo",
            "objetivo": "emagrecer",
            "plano": "ouro",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manhã"},
            "forma_pagamento": "cartao",
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
        "last_slots_offered": [],
    }
    turno = {
        "intent": "agendar",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": "pix",
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": False,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "await_payment"
    assert plano["update_data"]["forma_pagamento"] == "pix"
    assert plano["new_status"] == "aguardando_pagamento"


@pytest.mark.asyncio
async def test_planner_comprovante_em_pagamento_avanca_para_agendar():
    from app.conversation_legacy.planner import decidir_acao

    state = {
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
            "plano": "com_retorno",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manhã"},
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
        "last_slots_offered": [],
    }
    turno = {
        "intent": "confirmar_pagamento",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": True,
        "valor_comprovante": 240.0,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "cadastro"
    assert plano["update_flags"]["pagamento_confirmado"] is True


@pytest.mark.asyncio
async def test_planner_nao_retrocede_para_await_payment_quando_comprovante_tambem_indica_pix():
    from app.conversation_legacy.planner import decidir_acao

    state = {
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
            "plano": "com_retorno",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manhã"},
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
        "last_slots_offered": [],
    }
    turno = {
        "intent": "confirmar_pagamento",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": "pix",
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": True,
        "valor_comprovante": 240.0,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "cadastro"


@pytest.mark.asyncio
async def test_planner_comprovante_com_valor_divergente_nao_agenda():
    from app.conversation_legacy.planner import decidir_acao

    state = {
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
            "plano": "com_retorno",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manhã"},
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
        "last_slots_offered": [],
    }
    turno = {
        "intent": "confirmar_pagamento",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": True,
        "valor_comprovante": 200.0,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert "R$200.00" in plano["draft_message"]


@pytest.mark.asyncio
async def test_planner_comprovante_maior_que_sinal_aceita_valor_pago():
    from app.conversation_legacy.planner import decidir_acao

    state = {
        "goal": "agendar_consulta",
        "status": "aguardando_pagamento",
        "phone": "5531999990000",
        "phone_hash": "hash001",
        "tipo_remarcacao": None,
        "last_action": "await_payment",
        "collected_data": {
            "nome": "Ana Assistente",
            "status_paciente": "novo",
            "objetivo": "lipedema",
            "plano": "unica",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "tarde", "descricao": "tarde"},
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
                "datetime": "2026-05-04T15:00:00",
                "data_fmt": "segunda, 04/05",
                "hora": "15h",
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
        "last_slots_offered": [],
    }
    turno = {
        "intent": "confirmar_pagamento",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": True,
        "valor_comprovante": 150.0,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "cadastro"
    assert plano["update_flags"]["pagamento_confirmado"] is True
    assert plano["update_appointment"]["valor_pago_sinal"] == 150.0


@pytest.mark.asyncio
async def test_planner_bloqueia_agendamento_quando_ha_dois_telefones():
    from app.conversation_legacy.planner import decidir_acao

    state = {
        "goal": "agendar_consulta",
        "status": "aguardando_pagamento",
        "phone": "553186687010",
        "phone_hash": "hash001",
        "tipo_remarcacao": None,
        "last_action": "await_payment",
        "collected_data": {
            "nome": "Ana Assistente",
            "status_paciente": "novo",
            "objetivo": "lipedema",
            "plano": "unica",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "tarde", "descricao": "tarde"},
            "forma_pagamento": "pix",
            "data_nascimento": "1993-03-02",
            "email": "mail.bugadj@gmail.com",
            "telefone_contato": None,
            "instagram": None,
            "profissao": None,
            "cep_endereco": None,
            "indicacao_origem": None,
            "motivo_cancelamento": None,
        },
        "appointment": {
            "slot_escolhido": {"datetime": "2026-05-04T15:00:00", "data_fmt": "segunda, 04/05", "hora": "15h"},
            "id_paciente": None,
            "id_agenda": None,
            "id_transacao": None,
            "consulta_atual": None,
        },
        "flags": {
            "upsell_oferecido": True,
            "planos_enviados": True,
            "pagamento_confirmado": True,
            "aguardando_motivo_cancel": False,
            "aguardando_escolha_telefone": True,
            "telefone_opcoes": ["5531992059211", "5531986687010"],
        },
        "last_slots_offered": [],
    }
    turno = {
        "intent": "agendar",
        "confirmou_pagamento": False,
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "telefone_contato"


@pytest.mark.asyncio
async def test_planner_agenda_apos_pagamento_confirmado_e_cadastro_obrigatorio_completo():
    from app.conversation_legacy.planner import decidir_acao

    state = {
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
            "plano": "com_retorno",
            "modalidade": "presencial",
            "preferencia_horario": {"tipo": "turno", "turno": "manha", "descricao": "manhã"},
            "forma_pagamento": "pix",
            "data_nascimento": "1990-04-20",
            "email": "breno@email.com",
            "instagram": "@breno",
            "profissao": "Analista",
            "cep_endereco": "Vespasiano/MG",
            "indicacao_origem": "Instagram",
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
            "pagamento_confirmado": True,
            "aguardando_motivo_cancel": False,
        },
        "last_slots_offered": [],
    }
    turno = {
        "intent": "agendar",
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": None,
        "data_nascimento": None,
        "email": None,
        "instagram": None,
        "profissao": None,
        "cep_endereco": None,
        "indicacao_origem": None,
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": False,
        "valor_comprovante": None,
        "correcao": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "agendar"
    assert plano["params"]["email"] == "breno@email.com"


def test_new_stage_returns_welcome_message():
    response = get_flow_response("new", "oi")
    assert response is not None
    assert "Ana" in response or "Thaynara" in response


def test_awaiting_payment_returns_pix_info():
    response = get_flow_response("awaiting_payment", "")
    assert response is not None
    assert "PIX" in response or "pix" in response.lower() or "comprovante" in response.lower()


def test_scheduling_returns_available_times():
    response = get_flow_response("scheduling", "")
    assert response is not None
    # Deve conter horários
    assert any(h in response for h in ["08h", "9h", "10h", "15h", "16h", "17h", "18h", "19h"])


def test_confirmed_returns_confirmation():
    response = get_flow_response("confirmed", "")
    assert response is not None
    assert len(response) > 20


def test_archived_returns_none():
    response = get_flow_response("archived", "")
    assert response is None


def test_answer_faq_from_message_responde_lilly():
    from app.conversation_legacy.responder import _answer_faq_from_message

    response = _answer_faq_from_message("o que é a Lilly?")

    assert response is not None
    assert "assistente virtual" in response.lower()
    assert "ouro" in response.lower()
