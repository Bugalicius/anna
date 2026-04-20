from __future__ import annotations

import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient


class _FakeStateManager:
    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    async def load(self, phone_hash: str) -> object | None:
        return self._store.get(phone_hash)

    async def save(self, phone_hash: str, agent: object) -> None:
        self._store[phone_hash] = agent

    async def delete(self, phone_hash: str) -> None:
        self._store.pop(phone_hash, None)


def _route_atendimento(*args, **kwargs):
    return {
        "agente": "atendimento",
        "intencao": "novo_lead",
        "confianca": 1.0,
        "resposta_padrao": None,
    }


def test_test_chat_oferece_slots_sem_duplo_waiting():
    from app.agents.atendimento import AgenteAtendimento
    import app.router as router_module
    from app.main import app

    phone = "5500000001010"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
    state_mgr = _FakeStateManager()

    agente = AgenteAtendimento(telefone=phone, phone_hash=phone_hash)
    agente.etapa = "preferencia_horario"
    agente.nome = "Maria"
    agente.modalidade = "presencial"
    agente.plano_escolhido = "unica"

    state_mgr._store[phone_hash] = agente
    router_module._state_mgr = state_mgr

    slots_fake = [
        {"datetime": "2026-04-22T09:00:00", "data_fmt": "quarta, 22/04", "hora": "9h"},
        {"datetime": "2026-04-23T10:00:00", "data_fmt": "quinta, 23/04", "hora": "10h"},
        {"datetime": "2026-04-24T15:00:00", "data_fmt": "sexta, 24/04", "hora": "15h"},
    ]

    with patch("app.router.rotear", side_effect=_route_atendimento), \
         patch("app.agents.atendimento.consultar_slots_disponiveis", return_value=slots_fake):
        with TestClient(app) as client:
            router_module._state_mgr = state_mgr
            response = client.post("/test/chat", json={"phone": phone, "message": "prefiro manhã"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["responses"]) == 2
    assert any(palavra in payload["responses"][0].lower() for palavra in ["instante", "minutinho", "aguarda"])
    assert "Só um minutinho, já verifico pra você" not in payload["responses"][1]
    assert "Tenho essas opções disponíveis" in payload["responses"][1]


def test_test_chat_cancelamento_funciona_em_dois_turnos():
    from app.agents.retencao import AgenteRetencao
    import app.router as router_module
    from app.main import app

    phone = "5500000002020"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
    state_mgr = _FakeStateManager()
    router_module._state_mgr = state_mgr

    agente = AgenteRetencao(telefone=phone, nome="Roberto", modalidade="presencial")
    agente.etapa = "aguardando_motivo"
    state_mgr._store[phone_hash] = agente

    agenda_mock = {
        "id": "AGENDA-HTTP-001",
        "inicio": "2026-04-23T10:00:00",
        "fim": "2026-04-23T11:00:00",
        "id_servico": "SVC-001",
    }
    paciente_mock = {"id": 77, "nome": "Roberto", "telefone": phone}

    with patch("app.router.rotear", return_value={
            "agente": "retencao",
            "intencao": "novo_lead",
            "confianca": 0.99,
            "resposta_padrao": None,
         }), \
         patch("app.agents.retencao.buscar_paciente_por_telefone", return_value=paciente_mock), \
         patch("app.agents.retencao.consultar_agendamento_ativo", return_value=agenda_mock), \
         patch("app.agents.retencao.cancelar_agendamento", return_value=True):
        with TestClient(app) as client:
            router_module._state_mgr = state_mgr
            r2 = client.post("/test/chat", json={"phone": phone, "message": "tive um imprevisto"})

    assert r2.status_code == 200
    respostas2 = r2.json()["responses"]
    assert any("cancelad" in resposta.lower() for resposta in respostas2)
    assert phone_hash not in state_mgr._store
