from __future__ import annotations

import pytest

from app.conversation_v2.tools.notifications import (
    escalar_breno_silencioso,
    notificar_thaynara,
)


@pytest.mark.asyncio
async def test_notificar_thaynara_usa_mime_type(monkeypatch) -> None:
    chamadas = {}

    class FakeMeta:
        async def encaminhar_midia(self, to: str, image_bytes: bytes, mime_type: str, caption: str) -> None:
            chamadas["to"] = to
            chamadas["mime_type"] = mime_type

    monkeypatch.setattr("app.meta_api.MetaAPIClient", FakeMeta)

    result = await notificar_thaynara("ok", anexo_imagem=b"img", mime_type="image/png")

    assert result.sucesso is True
    assert chamadas["mime_type"] == "image/png"


@pytest.mark.asyncio
async def test_escalar_breno_silencioso_cria_registro(monkeypatch) -> None:
    async def _fake_notificar_breno(mensagem: str):
        from app.conversation_v2.tools import ToolResult

        return ToolResult(sucesso=True, dados={"destino": "breno"})

    monkeypatch.setattr("app.conversation_v2.tools.notifications.notificar_breno", _fake_notificar_breno)

    result = await escalar_breno_silencioso({"paciente": "Maria", "motivo": "duvida"})

    assert result.sucesso is True
    assert result.dados["notificado"] is True
    assert result.dados["registro"]["status"] == "pendente"

