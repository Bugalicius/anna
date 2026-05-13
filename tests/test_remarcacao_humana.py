import pytest


def _state_retorno():
    from app.conversation_legacy.state import create_state

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
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.responder import gerar_resposta

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
    assert "qual dia" in texto.lower() or "período" in texto.lower()
    assert "para seguirmos com o agendamento" not in texto.lower()
    assert "pagamento" not in texto.lower()


@pytest.mark.asyncio
async def test_remarcacao_com_preferencia_consulta_slots_sem_reiniciar_agendamento():
    from app.conversation_legacy.planner import decidir_acao

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
    from app.conversation_legacy.planner import decidir_acao

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
async def test_remarcacao_preferencia_corrigida_reconsulta_mesmo_apos_consultar_slots():
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "consultar_slots_remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "hora_especifica",
        "turno": None,
        "hora": "17h",
        "dia_semana": 0,
        "descricao": "segunda, 11/05 17h",
    }
    state["last_slots_offered"] = []
    turno = {
        "intent": "remarcar",
        "escolha_slot": None,
        "preferencia_horario": state["collected_data"]["preferencia_horario"],
        "correcao": {
            "campo": "preferencia_horario",
            "valor_novo": state["collected_data"]["preferencia_horario"],
        },
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "consultar_slots_remarcar"
    assert plano["params"]["preferencia"]["hora"] == "17h"


@pytest.mark.asyncio
async def test_remarcacao_escolha_slot_texto_visivel_confirma_remarcacao():
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "consultar_slots_remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "qualquer",
        "turno": None,
        "hora": None,
        "dia_semana": None,
        "descricao": "qualquer horario",
    }
    slot = {"datetime": "2026-05-11T17:00:00", "data_fmt": "segunda, 11/05", "hora": "17h"}
    state["last_slots_offered"] = [slot]
    turno = {
        "intent": "remarcar",
        "escolha_slot": 1,
        "preferencia_horario": None,
        "correcao": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "remarcar_dietbox"
    assert plano["params"]["novo_slot"] == slot
    assert plano["update_appointment"]["slot_escolhido"] == slot


@pytest.mark.asyncio
async def test_remarcacao_escolha_slot_retenta_apos_falha_da_tool():
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    slot = {"datetime": "2026-05-11T17:00:00", "data_fmt": "segunda, 11/05", "hora": "17h"}
    state["last_action"] = "remarcar_dietbox"
    state["last_tool_success"] = False
    state["last_slots_offered"] = [slot]
    state["appointment"]["slot_escolhido"] = slot
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "hora_especifica",
        "turno": None,
        "hora": "17h",
        "dia_semana": 0,
        "descricao": "segunda, 11/05 17h",
    }
    turno = {
        "intent": "remarcar",
        "escolha_slot": 1,
        "preferencia_horario": None,
        "correcao": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "remarcar_dietbox"
    assert plano["params"]["novo_slot"] == slot


@pytest.mark.asyncio
async def test_remarcacao_pede_outros_horarios_amplia_busca():
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "consultar_slots_remarcar"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "qualquer",
        "turno": None,
        "hora": None,
        "dia_semana": None,
        "descricao": "outras opções",
    }
    state["last_slots_offered"] = [
        {"datetime": "2026-05-06T10:00:00", "data_fmt": "quarta, 06/05", "hora": "10h"},
        {"datetime": "2026-05-12T10:00:00", "data_fmt": "terça, 12/05", "hora": "10h"},
    ]
    turno = {
        "intent": "remarcar",
        "escolha_slot": None,
        "preferencia_horario": {
            "tipo": "qualquer",
            "turno": None,
            "hora": None,
            "dia_semana": None,
            "descricao": "outras opções",
        },
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "preferencia_horario_remarcar"
    assert "O que não atende" in plano["draft_message"]


@pytest.mark.asyncio
async def test_remarcacao_pergunta_outros_horarios_nao_responde_politica():
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "consultar_slots_remarcar"
    state["last_slots_offered"] = [
        {"datetime": "2026-05-06T10:00:00", "data_fmt": "quarta, 06/05", "hora": "10h"},
        {"datetime": "2026-05-12T10:00:00", "data_fmt": "terça, 12/05", "hora": "10h"},
    ]
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "qualquer",
        "turno": None,
        "hora": None,
        "dia_semana": None,
        "descricao": "outras opções",
    }
    turno = {
        "intent": "remarcar",
        "_raw_message": "na semana do dia 11 só tem esses dois horários? nao tem nenhum outro?",
        "tem_pergunta": True,
        "topico_pergunta": "politica",
        "escolha_slot": None,
        "preferencia_horario": {
            "tipo": "qualquer",
            "turno": None,
            "hora": None,
            "dia_semana": None,
            "descricao": "outras opções",
        },
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "preferencia_horario_remarcar"


@pytest.mark.asyncio
async def test_confirmacao_remarcacao_usa_prontinho_e_data():
    from app.conversation_legacy.responder import gerar_resposta

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

    assert "Fiz a alteração da data e horário da consulta, tá bom?" in texto
    assert "30/04" in texto
    assert "18h" in texto


@pytest.mark.asyncio
async def test_remarcacao_sem_consulta_original_detecta_antes_de_remarcar():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "agendar_consulta"
    state["tipo_remarcacao"] = None
    turno = {
        "intent": "remarcar",
        "preferencia_horario": None,
        "escolha_slot": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"


@pytest.mark.asyncio
async def test_retorno_com_preferencia_nao_reinicia_onboarding():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "553186687010")
    state["goal"] = "agendar_consulta"
    state["collected_data"]["nome"] = "Ana"
    state["collected_data"]["status_paciente"] = "retorno"
    state["collected_data"]["preferencia_horario"] = {
        "tipo": "hora_especifica",
        "turno": "noite",
        "hora": "19:00",
        "dia_semana": None,
        "descricao": "dia 12 às 19h",
    }
    turno = {
        "intent": "agendar",
        "_raw_message": "quero no dia 12 às 19",
        "preferencia_horario": state["collected_data"]["preferencia_horario"],
        "escolha_slot": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"


@pytest.mark.asyncio
async def test_erro_remarcacao_operacional_escala_para_breno():
    from app.conversation_legacy.responder import gerar_resposta

    state = _state_retorno()
    respostas = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "remarcar_dietbox"},
        {"sucesso": False, "erro": "dados_remarcacao_incompletos", "escalar": True},
    )

    assert respostas == [{"_meta_action": "escalate", "motivo": "erro_remarcacao"}]


@pytest.mark.asyncio
async def test_remarcacao_nao_localizada_pede_nome_ou_email_sem_oferecer_nova_consulta():
    from app.conversation_legacy.responder import gerar_resposta

    state = _state_retorno()
    respostas = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "detectar_tipo_remarcacao"},
        {
            "tipo_remarcacao": "nao_localizado",
            "consulta_atual": None,
            "precisa_identificacao": True,
        },
    )
    texto = " ".join(respostas).lower()

    assert "número do whatsapp" in texto
    assert "nome completo" in texto
    assert "e-mail cadastrado" in texto
    assert "nova consulta" not in texto


@pytest.mark.asyncio
async def test_saudacao_inicial_nao_usa_draft_generico_do_llm():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531999990000")
    turno = {
        "intent": "tirar_duvida",
        "_raw_message": "oi",
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "nome"
    assert not plano.get("draft_message")


@pytest.mark.asyncio
async def test_saudacao_paciente_conhecido_e_curta_sem_llm():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531999990000")
    state["collected_data"]["nome"] = "Ana Assistente"
    state["goal"] = "agendar_consulta"
    turno = {
        "intent": "fora_de_contexto",
        "_raw_message": "oi",
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "respond_fora_de_contexto"
    assert plano["draft_message"] == "Oi Ana! Como posso te ajudar hoje? 💚"
    assert "👋" not in plano["draft_message"]
    assert "Claro" not in plano["draft_message"]


@pytest.mark.asyncio
async def test_bloqueia_confirmacao_remarcacao_sem_sucesso_da_tool(monkeypatch):
    from app.conversation_legacy.planner import decidir_acao

    state = _state_retorno()
    state["last_action"] = "remarcar_dietbox"
    state["last_tool_success"] = False
    state["appointment"]["slot_escolhido"] = {
        "datetime": "2026-05-04T15:00:00",
        "data_fmt": "segunda, 04/05",
        "hora": "15h",
    }
    turno = {
        "intent": "fora_de_contexto",
        "_raw_message": "oi",
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    async def _mock_llm(**kwargs):
        return '{"action":"send_confirmacao_remarcacao"}'

    monkeypatch.setattr(
        "app.conversation_legacy.planner.llm_client.complete_text_async",
        _mock_llm,
    )

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"


@pytest.mark.asyncio
async def test_remarcacao_nao_localizada_com_nome_invalido_pede_identificacao_de_novo():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "remarcar"
    state["tipo_remarcacao"] = "nao_localizado"
    state["collected_data"]["nome"] = "Ana Assistente"
    turno = {
        "intent": "remarcar",
        "nome": "Ana Assistente",
        "email": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "ask_field"
    assert plano["ask_context"] == "identificacao_remarcacao"
    assert "nome completo" in plano["draft_message"]


@pytest.mark.asyncio
async def test_remarcacao_nao_localizada_repetida_tenta_telefone_de_novo():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531986687010")
    state["goal"] = "remarcar"
    state["tipo_remarcacao"] = "nao_localizado"
    turno = {
        "intent": "remarcar",
        "nome": None,
        "email": None,
        "tem_pergunta": False,
        "topico_pergunta": None,
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"
    assert plano["params"]["telefone"] == "5531986687010"


@pytest.mark.asyncio
async def test_remarcacao_retorno_pede_preferencia_com_grade_de_horarios():
    from app.conversation_legacy.responder import gerar_resposta

    state = _state_retorno()
    respostas = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "detectar_tipo_remarcacao"},
        {
            "sucesso": True,
            "tipo_remarcacao": "retorno",
            "consulta_atual": {
                "id": "agenda-1",
                "inicio": "2026-05-04T15:00:00",
                "modalidade": "presencial",
            },
            "fim_janela": "2026-05-15",
        },
    )

    texto = respostas[0]
    assert "Qual dia ou período atende melhor sua rotina?" in texto
    assert "Manhã: 08h, 09h e 10h" not in texto
    assert "Tarde: 15h, 16h e 17h" not in texto


@pytest.mark.asyncio
async def test_pergunta_sobre_perda_retorno_explica_janela_sem_politica():
    from app.conversation_legacy.planner import decidir_acao
    from app.conversation_legacy.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "agendar_consulta"
    state["tipo_remarcacao"] = "perda_retorno"
    turno = {
        "intent": "tirar_duvida",
        "_raw_message": "pq não consegue marcar como retorno?",
        "tem_pergunta": True,
        "topico_pergunta": "politica",
    }

    plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano["ask_context"] == "perda_retorno"
    assert "90 dias" in plano["draft_message"]
    assert "PIX" not in plano["draft_message"]


@pytest.mark.asyncio
async def test_detectar_tipo_remarcacao_retorno_vencido_vira_perda(monkeypatch):
    from app.tools.patients import detectar_tipo_remarcacao

    monkeypatch.setattr(
        "app.integrations.dietbox.buscar_paciente_por_telefone",
        lambda telefone: {"id": 123, "nome": "Paciente"},
    )
    monkeypatch.setattr(
        "app.integrations.dietbox.buscar_paciente_por_identificador",
        lambda identificador: None,
    )
    monkeypatch.setattr(
        "app.integrations.dietbox.consultar_agendamento_ativo",
        lambda id_paciente: {"id": "agenda-1", "inicio": "2025-01-01T09:00:00"},
    )
    monkeypatch.setattr(
        "app.integrations.dietbox.verificar_lancamento_financeiro",
        lambda id_agenda: True,
    )

    result = await detectar_tipo_remarcacao("5531999990000")

    assert result["tipo"] == "perda_retorno"
    assert result["tipo_remarcacao"] == "perda_retorno"
