from __future__ import annotations

import pytest

from app.conversation_v2.tools.media import classificar_imagem, transcrever_audio


@pytest.mark.asyncio
async def test_transcrever_audio_retorna_texto(monkeypatch) -> None:
    async def _fake_transcribe(audio_bytes: bytes, mime_type: str) -> str:
        return "quero agendar consulta"

    monkeypatch.setattr("app.media_handler.transcribe_audio_async", _fake_transcribe)
    result = await transcrever_audio(audio_bytes=b"abc", mime_type="audio/ogg")
    assert result.sucesso is True
    assert result.dados["transcricao"] == "quero agendar consulta"


@pytest.mark.asyncio
async def test_classificar_imagem_normaliza_resposta_invalida(monkeypatch) -> None:
    async def _fake_complete(**kwargs) -> str:
        return "categoria_desconhecida"

    monkeypatch.setattr("app.llm_client.complete_with_image_async", _fake_complete)
    result = await classificar_imagem(imagem_bytes=b"img", contexto="teste")
    assert result.sucesso is True
    assert result.dados["categoria"] == "outro"


@pytest.mark.asyncio
async def test_classificar_imagem_respeita_mime_type(monkeypatch) -> None:
    chamado = {}

    async def _fake_complete(**kwargs) -> str:
        chamado["mime_type"] = kwargs["mime_type"]
        return "```comprovante_pagamento```"

    monkeypatch.setattr("app.llm_client.complete_with_image_async", _fake_complete)
    result = await classificar_imagem(
        imagem_bytes=b"img",
        contexto="pagamento",
        mime_type="image/png",
    )
    assert result.sucesso is True
    assert result.dados["categoria"] == "comprovante_pagamento"
    assert chamado["mime_type"] == "image/png"
