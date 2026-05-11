from __future__ import annotations

import pytest

from app.conversation.state import _mem_store, create_state, load_state, save_state
from app.conversation_v2 import orchestrator
from app.conversation_v2.tools import ToolResult


pytestmark = pytest.mark.asyncio


CONSULTA = {
    "id": 4321,
    "inicio": "2026-05-18T08:00:00",
    "data_fmt": "segunda, 18/05/2026",
    "hora": "08h",
    "modalidade": "presencial",
    "plano": "ouro",
    "ja_remarcada": False,
}
SLOTS = [
    {"datetime": "2026-05-19T08:00:00", "data_fmt": "terça, 19/05/2026", "hora": "08h"},
    {"datetime": "2026-05-20T15:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "15h"},
    {"datetime": "2026-05-21T18:00:00", "data_fmt": "quinta, 21/05/2026", "hora": "18h"},
]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _mem_store.clear()
    calls: list[tuple[str, dict]] = []

    async def fake_call_tool(name: str, input: dict):
        calls.append((name, input))
        if name == "detectar_tipo_remarcacao":
            phone = input.get("telefone") or ""
            if phone.endswith("002"):
                consulta = dict(CONSULTA, ja_remarcada=True)
                return ToolResult(sucesso=True, dados={"tipo_remarcacao": "retorno", "consulta_atual": consulta, "paciente": {"nome": "Lia"}})
            if phone.endswith("003") and not input.get("identificador"):
                return ToolResult(sucesso=True, dados={"tipo_remarcacao": "nao_localizado"})
            if phone.endswith("004"):
                return ToolResult(sucesso=True, dados={"tipo_remarcacao": "sem_agendamento_confirmado"})
            return ToolResult(sucesso=True, dados={"tipo_remarcacao": "retorno", "consulta_atual": dict(CONSULTA), "paciente": {"nome": "Lia"}})
        if name == "consultar_slots":
            return ToolResult(sucesso=True, dados={"slots": SLOTS, "match_exato": True, "slots_count": 3})
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call_tool)
    return calls


async def send(phone: str, text: str):
    return await orchestrator.processar_turno(phone, {"type": "text", "text": text})


async def seed(phone: str, estado: str, **updates):
    phone_hash = orchestrator._phone_hash(phone)
    state = orchestrator._ensure_v2_state(create_state(phone_hash, phone), phone)
    state["fluxo_id"] = orchestrator.REMARCACAO_ID
    state["estado"] = estado
    for key, value in updates.items():
        state[key] = value
    await save_state(phone_hash, state)
    return state


async def get_state(phone: str):
    return await load_state(orchestrator._phone_hash(phone), phone)


async def test_identifica_remarcacao_por_intencao_inicial():
    result = await send("553100000001", "quero remarcar")
    state = await get_state("553100000001")
    assert result.fluxo_id == "remarcacao"
    assert state["estado"] == "remarcacao_oferecendo_seguranca"
    assert any("consulta atual" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_fluxo_feliz_remarca_e_confirma_data_hora(isolate):
    phone = "553100000011"
    await send(phone, "quero remarcar")
    await send(phone, "quarta 15h")
    result = await send(phone, "slot_2")
    assert result.novo_estado == "remarcacao_concluida"
    assert any("quarta, 20/05/2026" in m.conteudo and "15h" in m.conteudo for m in result.mensagens_enviadas)
    assert any(name == "remarcar_dietbox" for name, _ in isolate)


async def test_janela_limite_bloqueia_data_fora_do_prazo():
    phone = "553100000012"
    await send(phone, "quero remarcar")
    result = await send(phone, "semana que vem")
    assert result.novo_estado == "remarcacao_oferecendo_seguranca"
    assert any("disponibilidade até" in m.conteudo for m in result.mensagens_enviadas)


async def test_segunda_tentativa_de_remarcacao_e_bloqueada():
    result = await send("553100000002", "quero remarcar")
    assert result.novo_estado == "remarcacao_concluida"
    assert any("já foi remarcada" in m.conteudo for m in result.mensagens_enviadas)


async def test_nao_localizado_pede_nome_completo():
    result = await send("553100000003", "preciso mudar horário")
    assert result.novo_estado == "remarcacao_pedindo_nome_completo"
    assert any("nome completo" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_nome_completo_localiza_e_segue():
    phone = "553100000003"
    await send(phone, "quero remarcar")
    result = await send(phone, "Lia Souza")
    assert result.novo_estado == "remarcacao_oferecendo_seguranca"


async def test_sem_consulta_ativa_oferece_agendamento_novo():
    result = await send("553100000004", "quero remarcar")
    assert result.novo_estado == "remarcacao_aguardando_decisao_nova_consulta"
    assert any("agendar uma nova" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_aceita_nova_consulta_volta_para_fluxo_1():
    phone = "553100000014"
    await seed(phone, "remarcacao_aguardando_decisao_nova_consulta")
    result = await send(phone, "sim")
    state = await get_state(phone)
    assert state["fluxo_id"] == "agendamento_paciente_novo"
    assert result.novo_estado == "inicio"


async def test_decide_manter_horario_original():
    phone = "553100000015"
    await send(phone, "quero remarcar")
    result = await send(phone, "vou manter")
    assert result.novo_estado == "remarcacao_concluida"
    assert any("segue marcada" in m.conteudo for m in result.mensagens_enviadas)


async def test_sexta_noite_recusada_na_remarcacao():
    phone = "553100000016"
    await send(phone, "quero remarcar")
    result = await send(phone, "sexta noite")
    assert result.novo_estado == "remarcacao_oferecendo_seguranca"
    assert any("Sexta à noite" in m.conteudo for m in result.mensagens_enviadas)


async def test_rejeita_slots_incrementa_rodada():
    phone = "553100000017"
    await seed(
        phone,
        "remarcacao_aguardando_escolha_slot",
        last_slots_offered=SLOTS,
        appointment={"consulta_atual": dict(CONSULTA), "slot_escolhido": None, "slot_escolhido_novo": None},
    )
    result = await send(phone, "outro horário")
    state = await get_state(phone)
    assert result.novo_estado == "remarcacao_aguardando_escolha_slot"
    assert state["rodada_negociacao"] == 1
    assert len(state["slots_rejeitados"]) == 3

