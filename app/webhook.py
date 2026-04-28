from __future__ import annotations

import logging
import os
import hashlib as _hashlib
import asyncio
import json as _json
import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from app.meta_api import verify_signature

router = APIRouter()
logger = logging.getLogger(__name__)

APP_SECRET = os.environ.get("META_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "")

_DEDUP_TTL = 14400  # 4 horas em segundos
_DEBOUNCE_TTL = 60


async def _is_duplicate_message(meta_message_id: str) -> bool:
    """
    Retorna True se mensagem ja foi processada (duplicata).
    Redis SET NX EX atomico. Graceful degradation: False se Redis falhar.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        key = f"dedup:msg:{meta_message_id}"
        result = await r.set(key, "1", nx=True, ex=_DEDUP_TTL)
        await r.aclose()
        return result is None  # None = key ja existia = duplicata — fail open
    except Exception as e:
        logger.warning("Redis dedup indisponivel: %s — prosseguindo sem dedup", e)
        return False  # fail open


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta verifica o endpoint ao configurar o webhook."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe mensagens da Meta. Retorna 200 imediatamente, processa em background."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature, APP_SECRET):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = _json.loads(body)  # usar body já lido, não re-ler o stream
    logger.info("WEBHOOK PAYLOAD: %s", _json.dumps(payload)[:500])

    from app.chatwoot_bridge import relay_meta_webhook_to_chatwoot
    background_tasks.add_task(
        relay_meta_webhook_to_chatwoot,
        body,
        {k.lower(): v for k, v in request.headers.items()},
    )

    # Extrair mensagens do payload aninhado da Meta
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                background_tasks.add_task(process_message_debounced, message, value.get("metadata", {}))

    return {"status": "ok"}


@router.get("/webhooks/whatsapp/{phone_number}")
async def verify_webhook_chatwoot_path(phone_number: str, request: Request):
    """Alias para verificacao do webhook Meta no formato usado pelo Chatwoot."""
    return await verify_webhook(request)


@router.post("/webhooks/whatsapp/{phone_number}")
async def receive_webhook_chatwoot_path(
    phone_number: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Alias para o webhook Meta quando a URL esta no formato do Chatwoot."""
    return await receive_webhook(request, background_tasks)


@router.post("/webhook/chatwoot")
async def receive_chatwoot_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe eventos do Chatwoot para controlar handoff humano.

    Configure no Chatwoot um webhook apontando para:
    https://anna.vps-kinghost.net/webhook/chatwoot
    """
    payload = await request.json()

    expected_token = os.environ.get("CHATWOOT_WEBHOOK_VERIFY_TOKEN", "")
    received_token = request.headers.get("X-Chatwoot-Webhook-Token") or request.query_params.get("token")
    if expected_token and received_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid Chatwoot webhook token")

    from app.chatwoot_bridge import (
        bind_chatwoot_conversation,
        chatwoot_event_sets_handoff,
        extract_conversation_id_from_chatwoot_payload,
        extract_phone_from_chatwoot_payload,
        resolve_phone_from_chatwoot_conversation,
        set_human_handoff,
    )

    if _is_incoming_chatwoot_message(payload):
        phone = extract_phone_from_chatwoot_payload(payload)
        if phone:
            message = _chatwoot_payload_to_meta_message(payload, phone)
            background_tasks.add_task(process_message_debounced, message, {})
            conversation_id = extract_conversation_id_from_chatwoot_payload(payload)
            if conversation_id:
                background_tasks.add_task(bind_chatwoot_conversation, conversation_id, phone)
        else:
            logger.warning(
                "Chatwoot enviou mensagem incoming, mas telefone nao foi encontrado "
                "(event=%s conversation_id=%s)",
                payload.get("event"),
                extract_conversation_id_from_chatwoot_payload(payload),
            )

    action = chatwoot_event_sets_handoff(payload)
    phone = extract_phone_from_chatwoot_payload(payload)
    conversation_id = extract_conversation_id_from_chatwoot_payload(payload)
    if not phone and action is False:
        phone = await resolve_phone_from_chatwoot_conversation(conversation_id)

    if action is not None and phone:
        await set_human_handoff(phone, action, reason=f"chatwoot:{payload.get('event', 'event')}")
        if action:
            await bind_chatwoot_conversation(conversation_id, phone)
        logger.info("Chatwoot handoff %s para telefone %s", "ON" if action else "OFF", phone[-4:])
    elif action is not None:
        logger.warning(
            "Chatwoot pediu handoff, mas telefone nao foi encontrado no payload "
            "(event=%s status=%s conversation_id=%s)",
            payload.get("event"),
            payload.get("status") or payload.get("conversation", {}).get("status"),
            conversation_id,
        )

    return {"status": "ok"}


def _is_incoming_chatwoot_message(payload: dict) -> bool:
    """Retorna True para mensagens recebidas do paciente pelo Chatwoot."""
    return (
        payload.get("event") == "message_created"
        and payload.get("message_type") == "incoming"
        and not payload.get("private", False)
    )


def _chatwoot_payload_to_meta_message(payload: dict, phone: str) -> dict:
    """Adapta um payload incoming do Chatwoot para o formato usado por process_message."""
    message_id = payload.get("id") or payload.get("message", {}).get("id")
    content = payload.get("content") or payload.get("message", {}).get("content")
    sender = payload.get("sender") or payload.get("contact") or {}
    name = sender.get("name") or sender.get("push_name")
    attachment = _first_chatwoot_attachment(payload)
    fallback_basis = f"{phone}:{content or attachment.get('data_url', '')}"
    fallback_id = _hashlib.sha256(fallback_basis.encode()).hexdigest()[:24]
    message = {
        "id": f"chatwoot:{message_id}" if message_id else f"chatwoot:{fallback_id}",
        "from": phone,
        "type": "text",
        "text": {"body": content or "[mídia]"},
        "profile": {"name": name},
    }
    if attachment:
        content_type = attachment.get("content_type") or ""
        file_type = str(attachment.get("file_type") or "").lower()
        media_type = "image" if file_type == "image" or content_type.startswith("image/") else "document"
        message["type"] = media_type
        message[media_type] = {
            "chatwoot_url": attachment.get("data_url") or attachment.get("download_url"),
            "mime_type": content_type or "application/octet-stream",
        }
    return message


def _first_chatwoot_attachment(payload: dict) -> dict:
    """Extrai o primeiro anexo do payload de webhook do Chatwoot."""
    candidates = [
        payload.get("attachments"),
        payload.get("message", {}).get("attachments"),
    ]
    for msg in payload.get("conversation", {}).get("messages", []) or []:
        candidates.append(msg.get("attachments"))

    for attachments in candidates:
        if isinstance(attachments, list) and attachments:
            first = attachments[0]
            return first if isinstance(first, dict) else {}
    return {}


async def _download_chatwoot_attachment(url: str) -> bytes:
    """Baixa anexo exposto pelo Chatwoot/ActiveStorage."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


def _digits_only(numero: str) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isdigit())


def _sem_nono_digito_brasil(numero: str) -> str:
    digits = _digits_only(numero)
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return digits[:4] + digits[5:]
    return digits


def _is_internal_number_local(numero: str) -> bool:
    recebido = _digits_only(numero)
    interno = _digits_only(os.environ.get("NUMERO_INTERNO", "5531992059211"))
    return recebido in {interno, _sem_nono_digito_brasil(interno)}


def _should_debounce_message(message: dict) -> bool:
    """Agrupa apenas textos de pacientes; mídia e mensagens internas seguem imediatas."""
    if _is_internal_number_local(message.get("from", "")):
        return False
    return message.get("type") == "text" and bool(message.get("text", {}).get("body"))


def _merge_debounced_messages(items: list[dict]) -> tuple[dict, dict]:
    """Combina mensagens de texto próximas em uma única mensagem lógica."""
    messages = [item["message"] for item in items]
    metadata = items[-1].get("metadata") or {}
    ids = [str(msg.get("id") or "") for msg in messages]
    text = "\n".join(
        str(msg.get("text", {}).get("body") or "").strip()
        for msg in messages
        if str(msg.get("text", {}).get("body") or "").strip()
    )
    first = dict(messages[0])
    first["id"] = "batch:" + _hashlib.sha256("|".join(ids).encode()).hexdigest()[:24]
    first["type"] = "text"
    first["text"] = {"body": text}
    return first, metadata


async def process_message_debounced(message: dict, metadata: dict):
    """
    Aguarda uma pequena janela antes de rotear textos.

    Isso evita respostas duplicadas quando o paciente manda "oi" e logo em seguida
    explica a intenção ("quero remarcar", "quero marcar", etc.).
    """
    if not _should_debounce_message(message):
        await process_message(message, metadata)
        return

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    phone = message.get("from", "")
    token = str(message.get("id") or _hashlib.sha256(repr(message).encode()).hexdigest())
    queue_key = f"debounce:queue:{phone}"
    token_key = f"debounce:token:{phone}"
    delay = float(os.environ.get("MESSAGE_DEBOUNCE_SECONDS", "4.0"))

    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        await r.rpush(queue_key, _json.dumps({"message": message, "metadata": metadata}, ensure_ascii=False))
        await r.expire(queue_key, _DEBOUNCE_TTL)
        await r.set(token_key, token, ex=_DEBOUNCE_TTL)
        await r.aclose()
    except Exception as e:
        logger.warning("Redis debounce indisponivel: %s — processando sem debounce", e)
        await process_message(message, metadata)
        return

    await asyncio.sleep(delay)

    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        latest = await r.get(token_key)
        if latest != token:
            await r.aclose()
            return
        raw_items = await r.lrange(queue_key, 0, -1)
        await r.delete(queue_key, token_key)
        await r.aclose()
    except Exception as e:
        logger.warning("Redis debounce flush falhou: %s — processando mensagem atual", e)
        await process_message(message, metadata)
        return

    items = [_json.loads(raw) for raw in raw_items]
    if not items:
        return
    merged_message, merged_metadata = _merge_debounced_messages(items)
    await process_message(merged_message, merged_metadata)


async def process_message(message: dict, metadata: dict):
    """Processa uma mensagem em background. Deduplicação + roteamento."""
    from app.database import SessionLocal
    from app.media_handler import analisar_comprovante_pagamento, processar_midia
    from app.models import Message, Contact, Conversation
    from app.router import route_message
    import hashlib
    from datetime import datetime, UTC

    meta_id = message.get("id", "")
    phone = message.get("from", "")
    msg_type = message.get("type", "")
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        itype = interactive.get("type", "")
        if itype == "button_reply":
            text = interactive.get("button_reply", {}).get("id", "") or "[mídia]"
        elif itype == "list_reply":
            text = interactive.get("list_reply", {}).get("id", "") or "[mídia]"
        else:
            text = "[mídia]"
    elif msg_type == "audio":
        media_id = message.get("audio", {}).get("id", "")
        text = "[mídia]"
        if media_id:
            media = await processar_midia(media_id)
            if media.get("transcricao"):
                text = media["transcricao"]
    elif msg_type in ("image", "document"):
        media_payload = message.get(msg_type, {})
        media_id = media_payload.get("id", "")
        chatwoot_url = media_payload.get("chatwoot_url", "")
        text = "[mídia]"
        if media_id:
            media = await processar_midia(media_id)
            analise = analisar_comprovante_pagamento(media.get("bytes", b""), media.get("mime_type", ""))
            if analise.get("eh_comprovante"):
                valor = analise.get("valor")
                valor_txt = f"{valor:.2f}" if isinstance(valor, (float, int)) else "null"
                favorecido = (analise.get("favorecido") or "").replace("|", " ")[:120]
                text = f"[comprovante valor={valor_txt} favorecido={favorecido}]"
        elif chatwoot_url:
            try:
                content = await _download_chatwoot_attachment(chatwoot_url)
                mime_type = media_payload.get("mime_type", "")
                analise = analisar_comprovante_pagamento(content, mime_type)
                if analise.get("eh_comprovante"):
                    valor = analise.get("valor")
                    valor_txt = f"{valor:.2f}" if isinstance(valor, (float, int)) else "null"
                    favorecido = (analise.get("favorecido") or "").replace("|", " ")[:120]
                    text = f"[comprovante valor={valor_txt} favorecido={favorecido}]"
            except Exception as e:
                logger.error("Falha ao processar anexo Chatwoot %s: %s", meta_id, e)
    else:
        text = message.get("text", {}).get("body", "") or "[mídia]"

    # Deduplicacao atomica via Redis SET NX (camada primaria)
    if await _is_duplicate_message(meta_id):
        logger.debug("Dedup Redis: mensagem %s ja processada, ignorando", meta_id)
        return

    with SessionLocal() as db:
        # Deduplicação: se já existe, ignora
        existing = db.query(Message).filter_by(meta_message_id=meta_id).first()
        if existing:
            logger.debug(f"Mensagem duplicada ignorada: {meta_id}")
            return

        # Buscar ou criar contato (usando hash do phone; phone_e164 salvo para uso no remarketing)
        phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            contact = Contact(
                phone_hash=phone_hash,
                phone_e164=phone,  # número real, necessário para Meta API
                push_name=message.get("profile", {}).get("name"),
                stage="new",
            )
            db.add(contact)
            db.flush()

        # Buscar ou criar conversa ativa
        conversation = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id, outcome="em_aberto")
            .order_by(Conversation.opened_at.desc())
            .first()
        )
        if not conversation:
            conversation = Conversation(contact_id=contact.id, stage=contact.stage)
            db.add(conversation)
            db.flush()

        # Registrar mensagem
        msg = Message(
            meta_message_id=meta_id,
            conversation_id=conversation.id,
            direction="inbound",
            content=text,
            processing_status="pending",
        )
        db.add(msg)
        db.commit()

    # Detectar mensagem do Breno (número interno) antes de rotear como paciente
    from app.escalation import is_numero_interno, processar_resposta_breno
    from app.meta_api import MetaAPIClient
    import os as _os

    _meta = MetaAPIClient(
        phone_number_id=_os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=_os.environ.get("WHATSAPP_TOKEN", ""),
    )

    if is_numero_interno(phone):
        # Mensagem do Breno — processar como resposta de escalação
        logger.info("Mensagem do número interno detectada — processando como resposta do Breno")
        await processar_resposta_breno(meta_client=_meta, texto_resposta=text)
        return

    # Rotear e responder (fora do session para evitar lock longo)
    try:
        await route_message(phone=phone, phone_hash=phone_hash, text=text, meta_message_id=meta_id)
    except Exception:
        logger.exception("Falha ao rotear mensagem %s", meta_id)
        with SessionLocal() as db:
            msg = db.query(Message).filter_by(meta_message_id=meta_id).first()
            if msg:
                msg.processing_status = "retrying"
                msg.retry_count = (msg.retry_count or 0) + 1
                msg.processed_at = datetime.now(UTC)
                db.commit()
        return

    with SessionLocal() as db:
        msg = db.query(Message).filter_by(meta_message_id=meta_id).first()
        if msg:
            msg.processing_status = "processed"
            msg.processed_at = datetime.now(UTC)
            db.commit()
