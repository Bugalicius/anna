from __future__ import annotations

import pytest

from app.conversation_v2.tools.patients import detectar_tipo_remarcacao


@pytest.mark.asyncio
async def test_detectar_tipo_remarcacao_nao_localizado(monkeypatch) -> None:
    monkeypatch.setattr("app.integrations.dietbox.buscar_paciente_por_telefone", lambda telefone: None)

    result = await detectar_tipo_remarcacao("5531999999999")

    assert result.sucesso is True
    assert result.dados["tipo_remarcacao"] == "nao_localizado"
    assert result.dados["consulta_atual"] is None


@pytest.mark.asyncio
async def test_detectar_tipo_remarcacao_retorno_com_ja_remarcada(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.integrations.dietbox.buscar_paciente_por_telefone",
        lambda telefone: {"id": 123, "nome": "Maria"},
    )
    monkeypatch.setattr(
        "app.integrations.dietbox.consultar_agendamento_ativo",
        lambda id_paciente: {
            "id": "agenda-1",
            "inicio": "2026-05-20T10:00:00",
            "descricao": "Remarcado pelo Agente Ana",
        },
    )

    result = await detectar_tipo_remarcacao("5531999999999")

    assert result.sucesso is True
    assert result.dados["tipo_remarcacao"] == "retorno"
    assert result.dados["ja_remarcada"] is True
    assert result.dados["consulta_atual"]["ja_remarcada"] is True

