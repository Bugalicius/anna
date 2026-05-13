from __future__ import annotations

import pytest

from app.conversation.tools.scheduling import (
    ConsultarSlotsInput,
    cancelar_dietbox,
    consultar_slots,
)


@pytest.mark.asyncio
async def test_consultar_slots_aplica_filtro_distribuicao(monkeypatch) -> None:
    fake_pool = [
        {"datetime": "2026-05-12T08:00:00", "data_fmt": "terça, 12/05", "hora": "8h"},
        {"datetime": "2026-05-12T09:00:00", "data_fmt": "terça, 12/05", "hora": "9h"},
        {"datetime": "2026-05-12T15:00:00", "data_fmt": "terça, 12/05", "hora": "15h"},
        {"datetime": "2026-05-13T08:00:00", "data_fmt": "quarta, 13/05", "hora": "8h"},
    ]

    monkeypatch.setattr(
        "app.integrations.dietbox.consultar_slots_disponiveis",
        lambda modalidade, dias_a_frente: fake_pool,
    )
    monkeypatch.setattr("app.tools.scheduling._selecionar_slots", lambda slots, preferencia: (slots[:3], None))

    result = await consultar_slots(
        ConsultarSlotsInput(modalidade="presencial", preferencia={}, max_resultados=3)
    )
    assert result.sucesso is True
    slots = result.dados["slots"]
    # Regra remove slot consecutivo 9h e mantém até 3 opções
    assert len(slots) == 3
    horas = [s["hora"] for s in slots]
    assert "9h" not in horas
    assert "2026-05-13T08:00:00" in [s["datetime"] for s in slots]


@pytest.mark.asyncio
async def test_cancelar_dietbox_faz_put_sem_delete(monkeypatch) -> None:
    chamadas = {"put": 0, "delete": 0}

    class Resp:
        def __init__(self, status_code: int, data: dict):
            self.status_code = status_code
            self._data = data

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._data

    monkeypatch.setattr("app.agents.dietbox_worker._headers", lambda: {"Authorization": "x"})
    monkeypatch.setattr(
        "requests.get",
        lambda *args, **kwargs: Resp(
            200,
            {
                "Data": {
                    "inicio": "2026-05-20T10:00:00",
                    "fim": "2026-05-20T11:00:00",
                    "timezone": "America/Sao_Paulo",
                    "idPaciente": 123,
                    "idLocalAtendimento": "AAA",
                    "idServico": "BBB",
                    "tipo": 1,
                    "isOnline": False,
                    "isVideoConference": False,
                }
            },
        ),
    )

    def _put(*args, **kwargs):
        chamadas["put"] += 1
        return Resp(200, {})

    monkeypatch.setattr("requests.put", _put)
    monkeypatch.setattr("requests.delete", lambda *args, **kwargs: chamadas.__setitem__("delete", chamadas["delete"] + 1))

    result = await cancelar_dietbox(id_agenda="agenda-uuid-999")
    assert result.sucesso is True
    assert chamadas["put"] == 1
    assert chamadas["delete"] == 0
    assert result.dados["id_agenda"] == "agenda-uuid-999"
