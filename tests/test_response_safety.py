from app.conversation.responder import sanitize_patient_responses


def test_sanitiza_texto_com_termo_interno_de_planner():
    state = {"goal": "remarcar", "tipo_remarcacao": "retorno"}
    mensagens = [
        "Paciente rejeita os slots oferecidos e solicita outras opções de manhã."
    ]

    result = sanitize_patient_responses(mensagens, state)

    assert "Paciente rejeita" not in result[0]
    assert "slots oferecidos" not in result[0]
    assert "prazo de remarcação" in result[0]


def test_sanitiza_body_interativo_preservando_botoes():
    state = {"goal": "remarcar", "tipo_remarcacao": "retorno"}
    mensagens = [{
        "_interactive": "button",
        "body": (
            "Não encontrei opções Paciente rejeita os slots oferecidos "
            "e solicita outras opções.\n\nQual horário funciona melhor pra você?"
        ),
        "buttons": [
            {"id": "slot_1", "title": "terça, 12/05 10h"},
            {"id": "slot_2", "title": "quarta, 13/05 15h"},
        ],
    }]

    result = sanitize_patient_responses(mensagens, state)

    assert result[0]["buttons"] == mensagens[0]["buttons"]
    assert "Paciente rejeita" not in result[0]["body"]
    assert "slots oferecidos" not in result[0]["body"]
    assert "Qual horário funciona melhor" in result[0]["body"]


def test_nao_sanitiza_mensagem_legitima_de_pagamento():
    state = {"goal": "agendar_consulta", "tipo_remarcacao": None}
    mensagem = "Para confirmar seu agendamento, é necessário o pagamento antecipado."

    result = sanitize_patient_responses([mensagem], state)

    assert result == [mensagem]
