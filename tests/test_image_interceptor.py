"""
Testes — Fluxo 5: Interceptador de Imagens

Cenários cobertos (10):
  1.  Sticker → "Hihi 💚 Como posso te ajudar?" (sem LLM)
  2.  Sem bytes e sem media_id → não intercepta
  3.  Comprovante exato sinal → aprova + saldo restante
  4.  Comprovante acima sinal / abaixo total → aprova + saldo
  5.  Comprovante total quitado → aprova sem saldo
  6.  Comprovante abaixo sinal → pede complemento, não encaminha Thaynara
  7.  Comprovante ilegível → escala Breno + responde paciente
  8.  Foto não-comprovante quando estado=aguardando_pagamento_pix
  9.  Foto não-comprovante em outro estado
  10. Comprovante aprovado é encaminhado para Thaynara

Nota: call_tool é importado lazily dentro das funções do interceptor.
      Patchamos em app.conversation.tools.registry.call_tool (módulo de origem).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.conversation.interceptors.image_interceptor import interceptar_imagem

PATCH_CALL_TOOL = "app.conversation.tools.registry.call_tool"

FAKE_BYTES = b"\xff\xd8\xff"  # JPEG magic bytes (stub)


def _tool_result(dados: dict, sucesso: bool = True) -> MagicMock:
    r = MagicMock()
    r.sucesso = sucesso
    r.dados = dados
    r.erro = None
    return r


# ── 1. Sticker ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sticker_retorna_hihi():
    mensagem = {"type": "sticker", "image_bytes": b""}
    result = await interceptar_imagem(mensagem, {})
    assert result.interceptado
    assert "Hihi" in result.mensagens[0]["conteudo"]


# ── 2. Sem bytes e sem media_id ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sem_bytes_sem_media_id_nao_intercepta():
    mensagem = {"type": "image", "image_bytes": b"", "media_id": ""}
    result = await interceptar_imagem(mensagem, {})
    assert not result.interceptado


# ── 3. Comprovante exato sinal ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_comprovante_exato_sinal_aprovado():
    dados_tool = {
        "eh_comprovante": True,
        "situacao": "exato_sinal",
        "valor": 150.0,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 150.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial", "nome": "Ana"},
    }

    chamadas: list[str] = []

    async def fake_call(name, params):
        chamadas.append(name)
        if name == "analisar_comprovante":
            return _tool_result(dados_tool)
        return _tool_result({"encaminhado": True})

    with patch(PATCH_CALL_TOOL, fake_call):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "150" in conteudo
    assert result.salvar_no_estado.get("flags.pagamento_confirmado") is True
    assert result.proximo_estado == "aguardando_cadastro"


# ── 4. Comprovante acima sinal / abaixo total ────────────────────────────────

@pytest.mark.asyncio
async def test_comprovante_acima_sinal_abaixo_total():
    dados_tool = {
        "eh_comprovante": True,
        "situacao": "acima_sinal",
        "valor": 200.0,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 100.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial", "nome": "Bia"},
    }

    async def fake_call(name, params):
        if name == "analisar_comprovante":
            return _tool_result(dados_tool)
        return _tool_result({"encaminhado": True})

    with patch(PATCH_CALL_TOOL, fake_call):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    assert result.salvar_no_estado.get("flags.pagamento_confirmado") is True
    conteudo = result.mensagens[0]["conteudo"]
    assert "200" in conteudo
    assert "100" in conteudo  # saldo restante


# ── 5. Total quitado ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_comprovante_total_quitado():
    dados_tool = {
        "eh_comprovante": True,
        "situacao": "total_quitado",
        "valor": 300.0,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 0.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial", "nome": "Cla"},
    }

    async def fake_call(name, params):
        if name == "analisar_comprovante":
            return _tool_result(dados_tool)
        return _tool_result({"encaminhado": True})

    with patch(PATCH_CALL_TOOL, fake_call):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "quitado" in conteudo.lower() or "integral" in conteudo.lower()
    assert result.salvar_no_estado.get("flags.pago_integral") is True


# ── 6. Abaixo do sinal — pede complemento, não encaminha Thaynara ───────────

@pytest.mark.asyncio
async def test_comprovante_abaixo_sinal_pede_complemento():
    dados_tool = {
        "eh_comprovante": True,
        "situacao": "abaixo_sinal",
        "valor": 80.0,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 220.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial"},
    }

    chamadas: list[str] = []

    async def fake_call(name, params):
        chamadas.append(name)
        return _tool_result(dados_tool)

    with patch(PATCH_CALL_TOOL, fake_call):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "80" in conteudo
    assert "150" in conteudo
    assert "PIX" in conteudo
    assert "encaminhar_comprovante_thaynara" not in chamadas


# ── 7. Comprovante ilegível — escala Breno ────────────────────────────────────

@pytest.mark.asyncio
async def test_comprovante_ilegivel_escala_breno():
    dados_ilegivel = {
        "eh_comprovante": True,
        "situacao": "ilegivel",
        "valor": None,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 0.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {"estado": "aguardando_pagamento_pix", "collected_data": {}}

    chamadas: list[str] = []

    async def fake_call(name, params):
        chamadas.append(name)
        return _tool_result({"notificado": True})

    # analisar_comprovante retorna ilegivel via patch de segundo nível
    async def fake_call_with_dados(name, params):
        chamadas.append(name)
        if name == "analisar_comprovante":
            return _tool_result(dados_ilegivel)
        return _tool_result({"notificado": True})

    with patch(PATCH_CALL_TOOL, fake_call_with_dados):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "confirmar" in conteudo.lower() or "equipe" in conteudo.lower()
    assert "escalar_breno_silencioso" in chamadas


# ── 8. Foto não-comprovante quando aguardando PIX ─────────────────────────────

@pytest.mark.asyncio
async def test_foto_nao_comprovante_estado_pix():
    dados_tool = {"eh_comprovante": False, "situacao": "ilegivel", "valor": None}
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial"},
    }

    with patch(PATCH_CALL_TOOL, AsyncMock(return_value=_tool_result(dados_tool))):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "comprovante" in conteudo.lower()
    assert "PIX" in conteudo or "comprovante" in conteudo.lower()


# ── 9. Foto qualquer em outro estado ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_foto_nao_comprovante_outro_estado():
    dados_tool = {"eh_comprovante": False, "situacao": "ilegivel", "valor": None}
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {"estado": "aguardando_nome", "collected_data": {}}

    with patch(PATCH_CALL_TOOL, AsyncMock(return_value=_tool_result(dados_tool))):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    conteudo = result.mensagens[0]["conteudo"]
    assert "comprovante" in conteudo.lower()


# ── 10. Comprovante aprovado é encaminhado para Thaynara ─────────────────────

@pytest.mark.asyncio
async def test_comprovante_aprovado_encaminhado_thaynara():
    dados_tool = {
        "eh_comprovante": True,
        "situacao": "exato_sinal",
        "valor": 150.0,
        "valor_sinal": 150.0,
        "valor_total": 300.0,
        "valor_restante": 150.0,
    }
    mensagem = {"type": "image", "image_bytes": FAKE_BYTES, "mime_type": "image/jpeg"}
    state = {
        "estado": "aguardando_pagamento_pix",
        "collected_data": {"plano": "ouro", "modalidade": "presencial", "nome": "Eva"},
    }

    chamadas: list[str] = []

    async def fake_call(name, params):
        chamadas.append(name)
        if name == "analisar_comprovante":
            return _tool_result(dados_tool)
        return _tool_result({"encaminhado": True})

    with patch(PATCH_CALL_TOOL, fake_call):
        result = await interceptar_imagem(mensagem, state)

    assert result.interceptado
    assert "encaminhar_comprovante_thaynara" in chamadas
    # encaminhar ocorre depois de analisar
    assert chamadas.index("encaminhar_comprovante_thaynara") > chamadas.index("analisar_comprovante")
