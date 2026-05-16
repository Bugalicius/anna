from __future__ import annotations

import pytest

from app.conversation.tools.notifications import (
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
    chamadas = {}

    async def _fake_alertar_escalacao(phone: str, nome: str, motivo: str, resumo: str = ""):
        chamadas["motivo"] = motivo

    monkeypatch.setattr("app.conversation.tools.notifications.alertar_escalacao", _fake_alertar_escalacao)

    result = await escalar_breno_silencioso({"paciente": "Maria", "motivo": "duvida"})

    assert result.sucesso is True
    assert result.dados["notificado"] is True
    assert result.dados["registro"]["status"] == "pendente"
    assert chamadas["motivo"] == "duvida"


@pytest.mark.asyncio
async def test_escalar_breno_silencioso_loop_usa_alerta_de_loop(monkeypatch) -> None:
    chamadas = {}

    async def _fake_alertar_loop(phone: str, nome: str, mensagem_repetida: str):
        chamadas["mensagem_repetida"] = mensagem_repetida

    monkeypatch.setattr("app.conversation.tools.notifications.alertar_loop_mensagem", _fake_alertar_loop)

    result = await escalar_breno_silencioso(
        {
            "telefone": "5531999999999",
            "motivo": "loop_fallback_2x",
            "resposta_repetida": "Pode me mandar de outro jeito?",
        }
    )

    assert result.sucesso is True
    assert chamadas["mensagem_repetida"] == "Pode me mandar de outro jeito?"
