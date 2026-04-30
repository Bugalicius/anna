"""
Processamento de mídia recebida via WhatsApp (Meta Cloud API).

Suporta:
  - Imagens (comprovantes de pagamento) → bytes + tamanho
  - PDFs (comprovantes)                 → bytes
  - Áudios (mensagens de voz)           → transcrição via OpenAI Whisper API

Fluxo:
  1. Meta envia webhook com media_id
  2. download_media(media_id) baixa os bytes via Graph API
  3. Para áudio: transcribe_audio(bytes, mime_type) chama Whisper
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path

import httpx

from app import llm_client

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com/v19.0"

# MIME types aceitos por categoria
MIME_IMAGENS = {"image/jpeg", "image/png", "image/webp"}
MIME_PDFS = {"application/pdf"}
MIME_AUDIOS = {"audio/ogg", "audio/mpeg", "audio/mp4", "audio/webm", "audio/wav"}


def _bearer() -> str:
    token = os.environ.get("WHATSAPP_TOKEN", "")
    if not token:
        raise RuntimeError("WHATSAPP_TOKEN não configurado")
    return f"Bearer {token}"


def download_media(media_id: str) -> tuple[bytes, str]:
    """
    Baixa a mídia do servidor Meta pelo media_id.

    Returns:
        (conteúdo em bytes, mime_type)

    Raises:
        httpx.HTTPError se o download falhar.
    """
    with httpx.Client(timeout=30) as client:
        # 1. Obtém a URL de download
        meta_resp = client.get(
            f"{_GRAPH_BASE}/{media_id}",
            headers={"Authorization": _bearer()},
        )
        meta_resp.raise_for_status()
        data = meta_resp.json()
        url = data["url"]
        mime_type = data.get("mime_type", "application/octet-stream")

        # 2. Baixa os bytes
        file_resp = client.get(
            url,
            headers={"Authorization": _bearer()},
            follow_redirects=True,
        )
        file_resp.raise_for_status()

    logger.info("Mídia %s baixada: %d bytes (%s)", media_id, len(file_resp.content), mime_type)
    return file_resp.content, mime_type


def transcribe_audio(audio_bytes: bytes, mime_type: str) -> str:
    """
    Transcreve áudio usando OpenAI Whisper API.

    Args:
        audio_bytes: conteúdo do arquivo de áudio
        mime_type: MIME do arquivo (ex: 'audio/ogg')

    Returns:
        Texto transcrito ou string vazia se falhar.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY não configurado — transcrição indisponível")
        return ""

    # Determina extensão para o nome do arquivo (Whisper exige extensão reconhecível)
    _ext_map = {
        "audio/ogg": "ogg",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/webm": "webm",
        "audio/wav": "wav",
    }
    ext = _ext_map.get(mime_type, "ogg")

    try:
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with httpx.Client(timeout=60) as client:
            with open(tmp_path, "rb") as f:
                resp = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    data={"model": "whisper-1", "language": "pt"},
                    files={"file": (Path(tmp_path).name, f, mime_type)},
                )
            resp.raise_for_status()
            texto = resp.json().get("text", "")

        logger.info("Áudio transcrito: %d chars", len(texto))
        return texto

    except Exception as e:
        logger.error("Erro ao transcrever áudio: %s", e)
        return ""
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


def classify_media(mime_type: str) -> str:
    """Retorna 'imagem', 'pdf', 'audio' ou 'desconhecido'."""
    if mime_type in MIME_IMAGENS:
        return "imagem"
    if mime_type in MIME_PDFS:
        return "pdf"
    if mime_type in MIME_AUDIOS:
        return "audio"
    return "desconhecido"


async def processar_midia(media_id: str) -> dict:
    """
    Pipeline completo: baixa + classifica + (transcreve se áudio).

    Returns:
        {
            "tipo": "imagem" | "pdf" | "audio" | "desconhecido",
            "bytes": bytes,
            "mime_type": str,
            "transcricao": str | None,   # preenchido apenas para áudio
        }
    """
    try:
        content, mime_type = download_media(media_id)
    except Exception as e:
        logger.error("Falha ao baixar mídia %s: %s", media_id, e)
        return {"tipo": "erro", "bytes": b"", "mime_type": "", "transcricao": None}

    tipo = classify_media(mime_type)
    transcricao = None

    if tipo == "audio":
        transcricao = transcribe_audio(content, mime_type)

    return {
        "tipo": tipo,
        "bytes": content,
        "mime_type": mime_type,
        "transcricao": transcricao,
    }


def analisar_comprovante_pagamento(content: bytes, mime_type: str) -> dict:
    """Lê comprovante em imagem e tenta extrair o valor pago."""
    if mime_type not in MIME_IMAGENS:
        return {"eh_comprovante": False, "valor": None, "texto_extraido": "", "favorecido": None}

    # llm_client cuida do provider; só validamos a chave do provider ativo abaixo no try
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower().strip()
    key_var = "GEMINI_API_KEY" if provider == "gemini" else "ANTHROPIC_API_KEY"
    if not os.environ.get(key_var, ""):
        logger.warning("%s não configurado — leitura de comprovante indisponível", key_var)
        return {"eh_comprovante": False, "valor": None, "texto_extraido": "", "favorecido": None}

    try:
        prompt = (
            "Analise a imagem e responda SOMENTE JSON válido com os campos "
            '{"eh_comprovante":true|false,"valor":number|null,"favorecido":string|null,"texto_extraido":string}. '
            "Se não parecer comprovante bancário/PIX, use eh_comprovante=false."
        )
        raw = llm_client.complete_with_image(
            user_text=prompt,
            image_bytes=content,
            mime_type=mime_type,
            max_tokens=300,
        )
        raw = llm_client.strip_json_fences(raw)
        data = json.loads(raw)
        valor = data.get("valor")
        try:
            valor = float(valor) if valor is not None else None
        except Exception:
            valor = _parse_brl_value(str(valor))
        return {
            "eh_comprovante": bool(data.get("eh_comprovante")),
            "valor": valor,
            "texto_extraido": str(data.get("texto_extraido", ""))[:1500],
            "favorecido": data.get("favorecido"),
        }
    except Exception as e:
        logger.error("Erro ao analisar comprovante: %s", e)
        return {"eh_comprovante": False, "valor": None, "texto_extraido": "", "favorecido": None}


def _parse_brl_value(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    m = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+(?:[.,]\d{2})?)", text)
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None
