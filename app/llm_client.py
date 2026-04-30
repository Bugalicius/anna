"""
LLM Client — camada de abstração unificada.

Encapsula chamadas ao LLM provider (Gemini por padrão, Anthropic como fallback).
Para trocar de provider, basta mudar a env var LLM_PROVIDER ou editar o default.

Funções públicas:
  complete_text(system, user, max_tokens) -> str
  complete_with_image(system, user_text, image_bytes, mime_type, max_tokens) -> str

Provider atual padrão: Gemini 2.5 Flash-Lite ($0.10/$0.40 por 1M tokens, free tier 1500 req/dia)
Provider de fallback: Anthropic Claude Haiku 4.5

Configuração via env:
  LLM_PROVIDER=gemini|anthropic        (default: gemini)
  LLM_MODEL_TEXT=...                   (default: gemini-2.5-flash-lite)
  LLM_MODEL_VISION=...                 (default: gemini-2.5-flash-lite)
  GEMINI_API_KEY=...
  ANTHROPIC_API_KEY=...                (apenas se LLM_PROVIDER=anthropic)
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── Estado interno ────────────────────────────────────────────────────────────

_TEST_OVERRIDE: Any | None = None

# ── Configuração ──────────────────────────────────────────────────────────────


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "gemini").lower().strip()


def _model_text() -> str:
    return os.environ.get("LLM_MODEL_TEXT", "gemini-2.5-flash-lite")


def _model_vision() -> str:
    return os.environ.get("LLM_MODEL_VISION", "gemini-2.5-flash-lite")


def _model_text_anthropic() -> str:
    return os.environ.get("LLM_MODEL_TEXT_ANTHROPIC", "claude-haiku-4-5-20251001")


def _model_vision_anthropic() -> str:
    return os.environ.get("LLM_MODEL_VISION_ANTHROPIC", "claude-haiku-4-5-20251001")


# ── API pública ────────────────────────────────────────────────────────────────


def complete_text(
    system: str,
    user: str,
    max_tokens: int = 700,
    temperature: float = 0.0,
    cache_system: bool = False,
) -> str:
    """
    Chamada de texto puro. Retorna a string de resposta.

    cache_system: se True, usa prompt caching no system prompt (apenas Anthropic).
                  Em Gemini não tem efeito direto — Gemini tem cache implícito.
    """
    # Hook para testes: se _TEST_OVERRIDE estiver setado, usa ele
    if _TEST_OVERRIDE is not None:
        return _TEST_OVERRIDE(system=system, user=user, max_tokens=max_tokens)
    provider = _provider()
    if provider == "gemini":
        return _gemini_text(system, user, max_tokens, temperature)
    if provider == "anthropic":
        return _anthropic_text(system, user, max_tokens, temperature, cache_system)
    raise ValueError(f"LLM_PROVIDER inválido: {provider}")


def complete_with_image(
    user_text: str,
    image_bytes: bytes,
    mime_type: str,
    system: str = "",
    max_tokens: int = 300,
    temperature: float = 0.0,
) -> str:
    """
    Chamada multimodal (texto + imagem). Retorna a string de resposta.

    Usado para análise de comprovantes de pagamento.
    """
    provider = _provider()
    if provider == "gemini":
        return _gemini_vision(user_text, image_bytes, mime_type, system, max_tokens, temperature)
    if provider == "anthropic":
        return _anthropic_vision(user_text, image_bytes, mime_type, system, max_tokens, temperature)
    raise ValueError(f"LLM_PROVIDER inválido: {provider}")


# ── Implementação Gemini ──────────────────────────────────────────────────────


def _gemini_text(system: str, user: str, max_tokens: int, temperature: float) -> str:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurado")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system if system else None,
        max_output_tokens=max_tokens,
        temperature=temperature,
    )
    response = client.models.generate_content(
        model=_model_text(),
        contents=user,
        config=config,
    )
    return (getattr(response, "text", None) or "").strip()


def _gemini_vision(
    user_text: str,
    image_bytes: bytes,
    mime_type: str,
    system: str,
    max_tokens: int,
    temperature: float,
) -> str:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY não configurado")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(
        system_instruction=system if system else None,
        max_output_tokens=max_tokens,
        temperature=temperature,
    )
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    response = client.models.generate_content(
        model=_model_vision(),
        contents=[user_text, image_part],
        config=config,
    )
    return (getattr(response, "text", None) or "").strip()


# ── Implementação Anthropic (fallback) ────────────────────────────────────────


def _anthropic_text(
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    cache_system: bool,
) -> str:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurado")

    client = anthropic.Anthropic(api_key=api_key)

    system_arg: Any
    if system and cache_system:
        system_arg = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    elif system:
        system_arg = system
    else:
        system_arg = anthropic.NOT_GIVEN

    response = client.messages.create(
        model=_model_text_anthropic(),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_arg,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def _anthropic_vision(
    user_text: str,
    image_bytes: bytes,
    mime_type: str,
    system: str,
    max_tokens: int,
    temperature: float,
) -> str:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY não configurado")

    client = anthropic.Anthropic(api_key=api_key)
    encoded = base64.b64encode(image_bytes).decode("ascii")

    response = client.messages.create(
        model=_model_vision_anthropic(),
        max_tokens=max_tokens,
        temperature=temperature,
        system=system if system else anthropic.NOT_GIVEN,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": mime_type, "data": encoded},
                },
                {"type": "text", "text": user_text},
            ],
        }],
    )
    return response.content[0].text.strip()


# ── Helper para parse JSON-em-resposta ────────────────────────────────────────


def strip_json_fences(raw: str) -> str:
    """Remove cercas markdown ```json...``` que LLMs às vezes adicionam."""
    raw = raw.strip()
    if raw.startswith("```"):
        # pega o conteúdo entre as primeiras cercas
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            elif raw.startswith("JSON"):
                raw = raw[4:]
    return raw.strip()
