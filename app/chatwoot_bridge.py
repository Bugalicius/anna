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
        await r.set(_conv_cache_key(phone), conversation_id, ex=_CONV_CACHE_TTL)
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
    relay_host = os.environ.get("CHATWOOT_RELAY_HOST", "").strip()
    relay_proto = os.environ.get("CHATWOOT_RELAY_PROTO", "https").strip() or "https"
    if relay_host:
        forward_headers["host"] = relay_host
        forward_headers["x-forwarded-proto"] = relay_proto
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


_CONV_CACHE_TTL = 3600  # 1 hora


def _chatwoot_api_url() -> str:
    return os.environ.get("CHATWOOT_API_URL", "").rstrip("/")


def _chatwoot_token() -> str:
    return os.environ.get("CHATWOOT_API_TOKEN", "")


def _chatwoot_account_id() -> str:
    return os.environ.get("CHATWOOT_ACCOUNT_ID", "1")


def _conv_cache_key(p: str) -> str:
    return "chatwoot:conv_id:" + phone_hash(p)


async def _get_chatwoot_conversation_id(p: str) -> str | None:
    """Retorna conversation_id do Chatwoot para o telefone, usando cache Redis."""
    api_url = _chatwoot_api_url()
    token = _chatwoot_token()
    account_id = _chatwoot_account_id()
    if not api_url or not token:
        return None

    cache_key = _conv_cache_key(p)
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        cached = await r.get(cache_key)
        await r.aclose()
        if cached:
            return cached
    except Exception:
        pass

    try:
        headers = {"api_access_token": token}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                api_url + "/api/v1/accounts/" + account_id + "/contacts/search",
                params={"q": p, "include_contacts": "true"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            payload = data.get("payload")
            if isinstance(payload, dict):
                contacts = payload.get("contacts") or []
            elif isinstance(payload, list):
                contacts = payload
            else:
                contacts = []
            if not contacts or not isinstance(contacts, list):
                return None
            contact_id = str(contacts[0]["id"])

            resp2 = await client.get(
                api_url + "/api/v1/accounts/" + account_id + "/contacts/" + contact_id + "/conversations",
                headers=headers,
            )
            resp2.raise_for_status()
            conversations = resp2.json().get("payload", [])
            if not conversations:
                return None
            conv = sorted(conversations, key=lambda c: c.get("id", 0), reverse=True)[0]
            conv_id = str(conv["id"])

        try:
            r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
            await r.set(cache_key, conv_id, ex=_CONV_CACHE_TTL)
            await r.aclose()
        except Exception:
            pass

        return conv_id
    except Exception as e:
        logger.warning("Falha ao buscar conversa Chatwoot para %s: %s", p[-4:], e)
        return None


async def log_bot_message(phone: str, text: str) -> None:
    """Registra mensagem da Ana como nota privada no Chatwoot."""
    if not _enabled():
        return

    api_url = _chatwoot_api_url()
    token = _chatwoot_token()
    account_id = _chatwoot_account_id()
    if not api_url or not token:
        return

    conv_id = await _get_chatwoot_conversation_id(phone)
    if not conv_id:
        logger.debug("Conversa Chatwoot nao encontrada para %s — nota nao registrada", phone[-4:])
        return

    try:
        headers = {"api_access_token": token}
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.post(
                api_url + "/api/v1/accounts/" + account_id + "/conversations/" + conv_id + "/messages",
                json={"content": text, "message_type": "outgoing", "private": True},
                headers=headers,
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning("Falha ao postar nota Chatwoot conv=%s: %s", conv_id, e)


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
