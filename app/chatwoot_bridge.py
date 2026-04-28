from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_PAUSE_TTL_SECONDS = int(os.environ.get("CHATWOOT_HUMAN_PAUSE_TTL_SECONDS", "86400"))


def _enabled() -> bool:
    return os.environ.get("CHATWOOT_RELAY_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


def _pause_key(phone_hash_value: str) -> str:
    return f"handoff:human:{phone_hash_value}"


def _conversation_key(conversation_id: str) -> str:
    return f"handoff:conversation:{conversation_id}"


def extract_conversation_id_from_chatwoot_payload(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation") or {}
    value = conversation.get("id") or payload.get("conversation_id")
    return str(value) if value else ""


async def set_human_handoff(phone: str, active: bool, reason: str = "chatwoot") -> None:
    """Marca ou remove pausa da Ana para um telefone."""
    if not phone:
        return

    key = _pause_key(phone_hash(phone))
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        if active:
            await r.set(key, reason, ex=_PAUSE_TTL_SECONDS)
        else:
            await r.delete(key)
        await r.aclose()
    except Exception as e:
        logger.warning("Falha ao atualizar handoff humano no Redis: %s", e)


async def bind_chatwoot_conversation(conversation_id: str, phone: str) -> None:
    if not conversation_id or not phone:
        return

    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        await r.set(_conversation_key(conversation_id), phone, ex=_PAUSE_TTL_SECONDS)
        await r.aclose()
    except Exception as e:
        logger.warning("Falha ao salvar vinculo conversa Chatwoot no Redis: %s", e)


async def resolve_phone_from_chatwoot_conversation(conversation_id: str) -> str:
    if not conversation_id:
        return ""

    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        phone = await r.get(_conversation_key(conversation_id))
        await r.aclose()
        return phone or ""
    except Exception as e:
        logger.warning("Falha ao buscar vinculo conversa Chatwoot no Redis: %s", e)
        return ""


async def is_human_handoff_active(phone_hash_value: str) -> bool:
    """Retorna True quando a Ana deve ficar silenciosa para esse contato."""
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        value = await r.get(_pause_key(phone_hash_value))
        await r.aclose()
        return bool(value)
    except Exception as e:
        logger.warning("Falha ao consultar handoff humano no Redis: %s", e)
        return False


async def relay_meta_webhook_to_chatwoot(body: bytes, headers: dict[str, str]) -> None:
    """Encaminha o POST bruto da Meta para o webhook do Chatwoot."""
    if not _enabled():
        return

    url = os.environ.get("CHATWOOT_WHATSAPP_WEBHOOK_URL", "").strip()
    if not url:
        logger.info("CHATWOOT_WHATSAPP_WEBHOOK_URL nao configurado; relay desativado")
        return

    forward_headers = {
        "content-type": headers.get("content-type", "application/json"),
    }
    signature = headers.get("x-hub-signature-256")
    if signature:
        forward_headers["x-hub-signature-256"] = signature

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, content=body, headers=forward_headers)
            response.raise_for_status()
    except Exception as e:
        logger.error("Falha ao encaminhar webhook Meta para Chatwoot: %s", e)


def extract_phone_from_chatwoot_payload(payload: dict[str, Any]) -> str:
    """Extrai telefone em formato numerico de eventos comuns do Chatwoot."""
    candidates = [
        payload.get("contact", {}).get("phone_number"),
        payload.get("conversation", {}).get("contact_inbox", {}).get("source_id"),
        payload.get("conversation", {}).get("meta", {}).get("sender", {}).get("phone_number"),
        payload.get("conversation", {}).get("meta", {}).get("sender", {}).get("identifier"),
        payload.get("sender", {}).get("phone_number"),
    ]

    for candidate in candidates:
        if not candidate:
            continue
        digits = "".join(ch for ch in str(candidate) if ch.isdigit())
        if digits:
            return digits
    return ""


def chatwoot_event_sets_handoff(payload: dict[str, Any]) -> bool | None:
    """
    Interpreta eventos do Chatwoot.

    True  -> pausar Ana.
    False -> liberar Ana.
    None  -> evento sem efeito.
    """
    event = str(payload.get("event", ""))
    status = str(payload.get("status") or payload.get("conversation", {}).get("status") or "")

    if event in ("conversation_status_changed", "conversation_updated"):
        if status in ("open", "pending"):
            return True
        if status == "resolved":
            return False

    if event == "message_created":
        message_type = str(payload.get("message_type", ""))
        sender_type = str(payload.get("sender", {}).get("type", "")).lower()
        private = bool(payload.get("private", False))
        if message_type == "outgoing" and not private and sender_type in ("user", "agent", "administrator"):
            return True

    return None
