"""
LLM Client — camada Gemini.

Encapsula chamadas ao Gemini para texto e visão.

Funções públicas:
  complete_text(system, user, max_tokens) -> str
  complete_text_async(system, user, max_tokens) -> str
  complete_with_image(system, user_text, image_bytes, mime_type, max_tokens) -> str
  complete_with_image_async(system, user_text, image_bytes, mime_type, max_tokens) -> str

Configuração via env:
  LLM_MODEL_TEXT=...    (default: gemini-2.5-flash-lite)
  LLM_MODEL_VISION=...  (default: gemini-2.5-flash-lite)
  GEMINI_API_KEY=...
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


_TEST_OVERRIDE: Any | None = None
_LLM_CALLS: ContextVar[int] = ContextVar("llm_calls", default=0)


def reset_llm_call_count() -> None:
    _LLM_CALLS.set(0)


def get_llm_call_count() -> int:
    return _LLM_CALLS.get()


def _increment_llm_call_count() -> None:
    _LLM_CALLS.set(_LLM_CALLS.get() + 1)


def _model_text() -> str:
    return os.environ.get("LLM_MODEL_TEXT", "gemini-2.5-flash-lite")


def _model_vision() -> str:
    return os.environ.get("LLM_MODEL_VISION", "gemini-2.5-flash-lite")


def complete_text(
    system: str,
    user: str,
    max_tokens: int = 700,
    temperature: float = 0.0,
    cache_system: bool = False,
) -> str:
    """
    Chamada de texto puro. Retorna a string de resposta.

    cache_system é aceito apenas por compatibilidade com chamadas existentes.
    """
    if _TEST_OVERRIDE is not None:
        return _TEST_OVERRIDE(system=system, user=user, max_tokens=max_tokens)
    _increment_llm_call_count()
    return _gemini_text(system, user, max_tokens, temperature)


async def complete_text_async(
    system: str,
    user: str,
    max_tokens: int = 700,
    temperature: float = 0.0,
    cache_system: bool = False,
) -> str:
    """Versão async-safe: executa o SDK síncrono do Gemini em thread."""
    if _TEST_OVERRIDE is not None:
        return _TEST_OVERRIDE(system=system, user=user, max_tokens=max_tokens)
    _increment_llm_call_count()
    return await asyncio.to_thread(
        _gemini_text,
        system,
        user,
        max_tokens,
        temperature,
    )


def complete_with_image(
    user_text: str,
    image_bytes: bytes,
    mime_type: str,
    system: str = "",
    max_tokens: int = 300,
    temperature: float = 0.0,
) -> str:
    """Chamada multimodal Gemini. Retorna a string de resposta."""
    _increment_llm_call_count()
    return _gemini_vision(user_text, image_bytes, mime_type, system, max_tokens, temperature)


async def complete_with_image_async(
    user_text: str,
    image_bytes: bytes,
    mime_type: str,
    system: str = "",
    max_tokens: int = 300,
    temperature: float = 0.0,
) -> str:
    """Versão async-safe: executa o SDK síncrono do Gemini em thread."""
    _increment_llm_call_count()
    return await asyncio.to_thread(
        _gemini_vision,
        user_text,
        image_bytes,
        mime_type,
        system,
        max_tokens,
        temperature,
    )


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
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0, 2, 4, 8]):
        if delay:
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=_model_text(),
                contents=user,
                config=config,
            )
            return (getattr(response, "text", None) or "").strip()
        except Exception as e:
            is_429 = "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower()
            if is_429 and attempt < 3:
                logger.warning(
                    "Gemini 429 (tentativa %d/3), aguardando %ds...",
                    attempt + 1,
                    [2, 4, 8][attempt],
                )
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]


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
    last_exc: Exception | None = None
    for attempt, delay in enumerate([0, 2, 4, 8]):
        if delay:
            time.sleep(delay)
        try:
            response = client.models.generate_content(
                model=_model_vision(),
                contents=[user_text, image_part],
                config=config,
            )
            return (getattr(response, "text", None) or "").strip()
        except Exception as e:
            is_429 = "429" in str(e) or "quota" in str(e).lower() or "rate" in str(e).lower()
            if is_429 and attempt < 3:
                logger.warning(
                    "Gemini vision 429 (tentativa %d/3), aguardando %ds...",
                    attempt + 1,
                    [2, 4, 8][attempt],
                )
                last_exc = e
                continue
            raise
    raise last_exc  # type: ignore[misc]


def strip_json_fences(raw: str) -> str:
    """Remove cercas markdown ```json...``` que LLMs às vezes adicionam."""
    raw = raw.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        if len(parts) >= 2:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
            elif raw.startswith("JSON"):
                raw = raw[4:]
    return raw.strip()
