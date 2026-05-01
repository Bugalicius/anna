"""
Processamento de mídia recebida via WhatsApp (Meta Cloud API).

Suporta:
  - Imagens (comprovantes de pagamento) → bytes + tamanho
  - PDFs (comprovantes)                 → bytes
  - Áudios (mensagens de voz)           → transcrição via Gemini (nativo)

Fluxo:
  1. Meta envia webhook com media_id
  2. download_media(media_id) baixa os bytes via Graph API
  3. Para áudio: transcribe_audio(bytes, mime_type) chama Gemini
"""
from __future__ import annotations

import json
import logging
import os
import re

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
    Transcreve áudio usando Gemini (nativo — suporta audio/ogg, audio/mp4, audio/mpeg).

    Args:
        audio_bytes: conteúdo do arquivo de áudio
        mime_type: MIME do arquivo (ex: 'audio/ogg')

    Returns:
        Texto transcrito ou string vazia se falhar.
    """
    if not os.environ.get("GEMINI_API_KEY", ""):
        logger.warning("GEMINI_API_KEY não configurado — transcrição indisponível")
        return ""

    try:
        texto = llm_client.complete_with_image(
            user_text=(
                "Transcreva o áudio exatamente como foi falado, em português do Brasil. "
                "Retorne apenas o texto transcrito, sem comentários adicionais."
            ),
            image_bytes=audio_bytes,
            mime_type=mime_type,
            max_tokens=1000,
        )
        logger.info("Áudio transcrito via Gemini: %d chars", len(texto))
        return texto
    except Exception as e:
        logger.error("Erro ao transcrever áudio: %s", e)
        return ""


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
        logger.debug("Raw LLM response para análise de comprovante: %s", raw[:300])
        raw = llm_client.strip_json_fences(raw)
        data = json.loads(raw)
        valor = data.get("valor")
        logger.debug("Valor bruto extraído do LLM: %s (tipo: %s)", valor, type(valor).__name__)

        try:
            valor = float(valor) if valor is not None else None
        except (TypeError, ValueError):
            valor_str = str(valor).strip() if valor is not None else ""
            logger.debug("Tentando parse BRL de: %s", valor_str)
            valor = _parse_brl_value(valor_str)
            if valor is not None:
                logger.info("Valor BRL parseado com sucesso: %s → %.2f", valor_str, valor)
            else:
                logger.warning("Falha ao parsear valor BRL: %s", valor_str)

        return {
            "eh_comprovante": bool(data.get("eh_comprovante")),
            "valor": valor,
            "texto_extraido": str(data.get("texto_extraido", ""))[:1500],
            "favorecido": data.get("favorecido"),
        }
    except Exception as e:
        logger.error("Erro ao analisar comprovante: %s (raw até agora: %s)", e, locals().get("raw", "N/A")[:200])
        return {"eh_comprovante": False, "valor": None, "texto_extraido": "", "favorecido": None}


def _parse_brl_value(text: str) -> float | None:
    """
    Parse valor em reais em múltiplos formatos:
    - R$ 150,00 (com símbolo e vírgula)
    - 150.00 (ponto decimal)
    - 150,00 (vírgula decimal)
    - 150 (inteiro)
    """
    text = text.strip()
    if not text:
        return None

    # Remove R$, espaços e símbolos de moeda
    text = re.sub(r"[R$\s]+", "", text)

    # Detecta se usa ponto ou vírgula como separador decimal
    # Padrão: 1.234,56 (europeu) vs 1,234.56 (americano)
    pontos = text.count(".")
    virgulas = text.count(",")

    if pontos > 0 and virgulas > 0:
        # Ambos presentes: o último é o decimal
        if text.rfind(".") > text.rfind(","):
            # Ponto é decimal: 1.234.567,89 → remove pontos, troca vírgula por ponto
            text = text.replace(".", "").replace(",", ".")
        else:
            # Vírgula é decimal: 1.234,56 → remove pontos, vírgula vira ponto
            text = text.replace(".", "").replace(",", ".")
    elif virgulas > 0:
        # Apenas vírgulas: tratar como decimal
        text = text.replace(",", ".")
    # elif pontos > 0: mantém como está (já em formato decimal)

    # Tenta fazer parse
    try:
        return float(text)
    except ValueError:
        return None
