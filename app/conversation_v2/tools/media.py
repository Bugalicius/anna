from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ConfigDict

from app.conversation_v2.tools import ToolResult

logger = logging.getLogger(__name__)


class TranscreverAudioInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_bytes: bytes
    mime_type: str


class ClassificarImagemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imagem_bytes: bytes
    contexto: str = ""
    mime_type: str = "image/jpeg"


async def transcrever_audio(audio_bytes: bytes, mime_type: str) -> ToolResult:
    """Transcreve áudio via Gemini."""
    from app.media_handler import transcribe_audio_async

    try:
        texto = await transcribe_audio_async(audio_bytes, mime_type)
        return ToolResult(sucesso=True, dados={"transcricao": texto or ""})
    except Exception as exc:
        logger.exception("Erro ao transcrever áudio: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


def _normalizar_categoria(raw: str) -> str:
    texto = (raw or "").strip().lower()
    texto = re.sub(r"```(?:json)?|```", "", texto).strip()
    texto = texto.strip('"\'`.,;: ')
    permitidas = {"comprovante_pagamento", "figurinha", "foto_pessoal", "documento", "outro"}
    if texto in permitidas:
        return texto
    for categoria in permitidas:
        if categoria in texto:
            return categoria
    return "outro"


async def classificar_imagem(
    imagem_bytes: bytes,
    contexto: str,
    mime_type: str = "image/jpeg",
) -> ToolResult:
    """Classifica: comprovante_pagamento, figurinha, foto_pessoal, documento, outro."""
    from app import llm_client

    try:
        prompt = (
            "Classifique a imagem em apenas uma categoria e responda SOMENTE a palavra da categoria:\n"
            "comprovante_pagamento | figurinha | foto_pessoal | documento | outro.\n"
            f"Contexto opcional: {contexto or 'nenhum'}"
        )
        raw = await llm_client.complete_with_image_async(
            user_text=prompt,
            image_bytes=imagem_bytes,
            mime_type=mime_type,
            max_tokens=20,
        )
        categoria = _normalizar_categoria(raw)
        return ToolResult(sucesso=True, dados={"categoria": categoria})
    except Exception as exc:
        logger.exception("Erro ao classificar imagem: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))
