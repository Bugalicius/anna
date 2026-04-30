import pytest


@pytest.mark.asyncio
async def test_remarcacao_prioriza_semana_seguinte_a_consulta(monkeypatch):
    from app.tools import scheduling

    slots = [
        {"datetime": "2026-05-05T15:00:00", "data_fmt": "terça, 05/05", "hora": "15h"},
        {"datetime": "2026-05-06T15:00:00", "data_fmt": "quarta, 06/05", "hora": "15h"},
        {"datetime": "2026-05-11T09:00:00", "data_fmt": "segunda, 11/05", "hora": "9h"},
        {"datetime": "2026-05-12T10:00:00", "data_fmt": "terça, 12/05", "hora": "10h"},
    ]

    async def _fake_executor(*args, **kwargs):
        return slots

    class _Loop:
        async def run_in_executor(self, _executor, func):
            return func()

    monkeypatch.setattr(scheduling.asyncio, "get_event_loop", lambda: _Loop())
    monkeypatch.setattr(
        "app.integrations.dietbox.consultar_slots_disponiveis",
        lambda **kwargs: slots,
    )

    result = await scheduling.consultar_slots_remarcar(
        modalidade="presencial",
        preferencia={"tipo": "qualquer", "descricao": "qualquer horário"},
        fim_janela="2026-05-15",
        consulta_atual_inicio="2026-05-04T15:00:00-03:00",
    )

    assert [s["datetime"] for s in result["slots"][:2]] == [
        "2026-05-11T09:00:00",
        "2026-05-12T10:00:00",
    ]
    assert result["slots_mesma_semana"] is True


@pytest.mark.asyncio
async def test_remarcacao_mesma_semana_usa_frase_desistencias():
    from app.conversation.responder import gerar_resposta
    from app.conversation.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "remarcar"
    resposta = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "consultar_slots_remarcar"},
        {
            "slots_mesma_semana": True,
            "slots": [
                {"datetime": "2026-05-05T15:00:00", "data_fmt": "terça, 05/05", "hora": "15h"},
            ],
        },
    )

    assert len(resposta) == 1
    assert resposta[0]["_interactive"] == "button"
    assert resposta[0]["body"].startswith("Tive desistências essa semana:")


@pytest.mark.asyncio
async def test_remarcacao_slots_sem_aviso_envia_apenas_botoes():
    from app.conversation.responder import gerar_resposta
    from app.conversation.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "remarcar"
    resposta = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "consultar_slots_remarcar"},
        {
            "slots": [
                {"datetime": "2026-05-18T16:00:00", "data_fmt": "segunda, 18/05", "hora": "16h"},
            ],
        },
    )

    assert len(resposta) == 1
    assert resposta[0]["_interactive"] == "button"
    assert "Olhei aqui" not in resposta[0]["body"]


@pytest.mark.asyncio
async def test_fallback_preferencia_remarcacao_envia_uma_mensagem_humana():
    from app.conversation.responder import gerar_resposta
    from app.conversation.state import create_state

    state = create_state("hash", "5531999990000")
    state["goal"] = "remarcar"
    resposta = await gerar_resposta(
        state,
        {"action": "execute_tool", "tool": "consultar_slots_remarcar"},
        {
            "aviso_preferencia": (
                "Olha, infelizmente não tenho disponibilidade com essa preferência.\n\n"
                "Mas, para não te deixar sem opção, separei os 3 horários mais próximos disponíveis:"
            ),
            "slots": [
                {"datetime": "2026-05-11T17:00:00", "data_fmt": "segunda, 11/05", "hora": "17h"},
                {"datetime": "2026-05-12T10:00:00", "data_fmt": "terça, 12/05", "hora": "10h"},
            ],
        },
    )

    assert len(resposta) == 1
    assert resposta[0]["_interactive"] == "button"
    assert resposta[0]["body"].startswith("Olha, infelizmente")
    assert "Olhei aqui" not in resposta[0]["body"]
