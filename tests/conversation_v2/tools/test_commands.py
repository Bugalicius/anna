from __future__ import annotations

import pytest

from app.conversation.tools.commands import interpretar_comando
from app.conversation.tools.registry import call_tool


@pytest.mark.asyncio
async def test_interpretar_comando_sucesso(monkeypatch) -> None:
    async def _fake_complete_text_async(**kwargs) -> str:
        return (
            '{"comando_identificado":"cancelar_consulta",'
            '"parametros_extraidos":{"nome_paciente":"Maria"},'
            '"confidence":0.93}'
        )

    monkeypatch.setattr("app.llm_client.complete_text_async", _fake_complete_text_async)
    result = await interpretar_comando("Cancela a consulta da Maria", "5531992059211")
    assert result.sucesso is True
    assert result.dados["comando_identificado"] == "cancelar_consulta"
    assert result.dados["parametros_extraidos"]["nome_paciente"] == "Maria"


@pytest.mark.asyncio
async def test_interpretar_comando_fallback_nao_reconhecido(monkeypatch) -> None:
    async def _fake_complete_text_async(**kwargs) -> str:
        return "nao-json"

    monkeypatch.setattr("app.llm_client.complete_text_async", _fake_complete_text_async)
    result = await interpretar_comando("texto qualquer", "5531992059211")
    assert result.sucesso is True
    assert result.dados["comando_identificado"] == "nao_reconhecido"


@pytest.mark.asyncio
async def test_registry_call_tool(monkeypatch) -> None:
    async def _fake_complete_text_async(**kwargs) -> str:
        return '{"comando_identificado":"consultar_status_paciente","parametros_extraidos":{},"confidence":0.8}'

    monkeypatch.setattr("app.llm_client.complete_text_async", _fake_complete_text_async)
    result = await call_tool(
        "interpretar_comando",
        {"texto": "status da Maria", "remetente": "5531991394759"},
    )
    assert result.sucesso is True
    assert result.dados["comando_identificado"] == "consultar_status_paciente"

