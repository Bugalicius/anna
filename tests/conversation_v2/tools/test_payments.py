from __future__ import annotations

import pytest

from app.conversation_v2.tools.payments import (
    analisar_comprovante,
    encaminhar_comprovante_thaynara,
    gerar_link_pagamento,
)


@pytest.mark.asyncio
async def test_gerar_link_pagamento_sucesso(monkeypatch) -> None:
    async def _fake_gerar_link(plano: str, modalidade: str, phone_hash: str) -> dict:
        return {
            "sucesso": True,
            "link_url": "https://rede.exemplo/pag/123",
            "parcelas": 6,
            "parcela_valor": 128.0,
        }

    monkeypatch.setattr("app.tools.payments.gerar_link", _fake_gerar_link)
    result = await gerar_link_pagamento(plano="ouro", modalidade="presencial", phone_hash="abc")
    assert result.sucesso is True
    assert result.dados["url"] == "https://rede.exemplo/pag/123"
    assert result.dados["parcelas"] == 6


@pytest.mark.asyncio
async def test_analisar_comprovante_classifica_situacao_exato_sinal(monkeypatch) -> None:
    async def _fake_analise(content: bytes, mime_type: str) -> dict:
        return {"eh_comprovante": True, "valor": 345.0, "favorecido": "Thaynara"}

    monkeypatch.setattr("app.media_handler.analisar_comprovante_pagamento_async", _fake_analise)
    result = await analisar_comprovante(
        imagem_bytes=b"fake",
        mime_type="image/jpeg",
        plano="ouro",
        modalidade="presencial",
    )
    assert result.sucesso is True
    assert result.dados["eh_comprovante"] is True
    assert result.dados["situacao"] == "exato_sinal"


@pytest.mark.asyncio
async def test_encaminhar_comprovante_thaynara(monkeypatch) -> None:
    chamadas = {"ok": 0}

    class FakeMeta:
        async def encaminhar_midia(self, to: str, image_bytes: bytes, mime_type: str, caption: str) -> None:
            chamadas["ok"] += 1

    monkeypatch.setattr("app.meta_api.MetaAPIClient", FakeMeta)
    result = await encaminhar_comprovante_thaynara(imagem_bytes=b"x", resumo_formatado="resumo")
    assert result.sucesso is True
    assert chamadas["ok"] == 1

