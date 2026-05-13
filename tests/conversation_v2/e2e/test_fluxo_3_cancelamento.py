from __future__ import annotations

import pytest

from app.conversation.state import _mem_store, create_state, load_state, save_state
from app.conversation import orchestrator
from app.conversation.tools import ToolResult


pytestmark = pytest.mark.asyncio


CONSULTA = {
    "id": 9876,
    "inicio": "2026-05-18T08:00:00",
    "data_fmt": "segunda, 18/05/2026",
    "hora": "08h",
    "modalidade": "online",
    "plano": "premium",
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
            if phone.endswith("003") and not input.get("identificador"):
                return ToolResult(sucesso=True, dados={"tipo_remarcacao": "nao_localizado"})
            if phone.endswith("004"):
                return ToolResult(sucesso=True, dados={"tipo_remarcacao": "sem_agendamento_confirmado"})
            return ToolResult(sucesso=True, dados={"tipo_remarcacao": "retorno", "consulta_atual": dict(CONSULTA), "paciente": {"nome": "Nina"}})
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
    state["fluxo_id"] = orchestrator.CANCELAMENTO_ID
    state["estado"] = estado
    state["appointment"]["consulta_atual"] = dict(CONSULTA)
    state["collected_data"]["nome"] = "Nina"
    state["collected_data"]["motivo_cancelamento"] = "viagem"
    state["collected_data"]["modalidade"] = "online"
    state["collected_data"]["plano"] = "premium"
    for key, value in updates.items():
        state[key] = value
    await save_state(phone_hash, state)
    return state


async def get_state(phone: str):
    return await load_state(orchestrator._phone_hash(phone), phone)


async def test_identifica_cancelamento_por_intencao_inicial():
    result = await send("553100001001", "quero cancelar")
    assert result.fluxo_id == "cancelamento"
    assert result.novo_estado == "cancelamento_aguardando_motivo"
    assert any("motivo" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_nao_localizado_pede_nome():
    result = await send("553100001003", "quero cancelar")
    assert result.novo_estado == "cancelamento_pedindo_nome"
    assert any("nome completo" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_nome_completo_localiza_e_pede_motivo():
    phone = "553100001003"
    await send(phone, "quero cancelar")
    result = await send(phone, "Nina Silva")
    assert result.novo_estado == "cancelamento_aguardando_motivo"


async def test_sem_consulta_ativa_nao_cancela():
    result = await send("553100001004", "quero cancelar")
    assert result.novo_estado == "cancelamento_concluido"
    assert any("não encontrei uma consulta ativa" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_motivo_leva_para_retencao():
    phone = "553100001005"
    await send(phone, "quero cancelar")
    result = await send(phone, "vou viajar")
    assert result.novo_estado == "cancelamento_tentativa_retencao"
    assert any("remarcar em vez de cancelar" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cancelamento_direto_apos_motivo_notifica_internos(isolate):
    phone = "553100001006"
    await send(phone, "quero cancelar")
    await send(phone, "vou viajar")
    result = await send(phone, "prefiro cancelar mesmo")
    assert result.novo_estado == "cancelamento_concluido"
    assert any(name == "cancelar_dietbox" for name, _ in isolate)
    assert any(name == "notificar_thaynara" for name, _ in isolate)
    assert any(name == "notificar_breno" for name, _ in isolate)


async def test_retencao_aceita_vira_remarcacao():
    phone = "553100001007"
    await send(phone, "quero cancelar")
    await send(phone, "conflito de agenda")
    result = await send(phone, "pode ser segunda 8h")
    state = await get_state(phone)
    assert state["fluxo_id"] == "remarcacao"
    assert result.novo_estado == "remarcacao_aguardando_escolha_slot"


async def test_paciente_pede_pra_pensar_mantem_consulta():
    phone = "553100001008"
    await send(phone, "quero cancelar")
    await send(phone, "agenda apertada")
    result = await send(phone, "vou pensar")
    assert result.novo_estado == "cancelamento_aguardando_decisao_final"
    assert any("segue marcada" in m.conteudo for m in result.mensagens_enviadas)


async def test_decisao_final_cancelar_executa():
    phone = "553100001009"
    await seed(phone, "cancelamento_aguardando_decisao_final")
    result = await send(phone, "cancela")
    assert result.novo_estado == "cancelamento_concluido"


async def test_cancelamento_silencioso_nao_manda_mensagem_paciente_e_notifica(isolate):
    phone = "553100001010"
    await seed(phone, "cancelamento_tentativa_retencao")
    result = await send(phone, "24h sem resposta")
    assert result.novo_estado == "cancelamento_concluido"
    assert result.mensagens_enviadas == []
    assert any(name == "notificar_thaynara" for name, _ in isolate)
    assert any(name == "notificar_breno" for name, _ in isolate)


async def test_respostas_ao_paciente_nao_informam_perda_de_valor():
    phone = "553100001011"
    await send(phone, "quero cancelar")
    await send(phone, "agenda apertada")
    result = await send(phone, "prefiro cancelar mesmo")
    texto = "\n".join(m.conteudo for m in result.mensagens_enviadas)
    assert "reembolso" not in texto.lower()
    assert "valor não" not in texto.lower()


async def test_decide_manter_consulta():
    phone = "553100001012"
    await send(phone, "quero cancelar")
    await send(phone, "agenda apertada")
    result = await send(phone, "vou manter")
    assert result.novo_estado == "cancelamento_concluido"
    assert any("segue marcada" in m.conteudo for m in result.mensagens_enviadas)

