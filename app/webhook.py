from __future__ import annotations

import logging
import os
import redis.asyncio as aioredis
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from app.meta_api import verify_signature

router = APIRouter()
logger = logging.getLogger(__name__)

APP_SECRET = os.environ.get("META_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "")

_DEDUP_TTL = 14400  # 4 horas em segundos


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

    import json as _json
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
                background_tasks.add_task(process_message, message, value.get("metadata", {}))

    return {"status": "ok"}


@router.post("/webhook/chatwoot")
async def receive_chatwoot_webhook(request: Request):
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
        media_id = message.get(msg_type, {}).get("id", "")
        text = "[mídia]"
        if media_id:
            media = await processar_midia(media_id)
            analise = analisar_comprovante_pagamento(media.get("bytes", b""), media.get("mime_type", ""))
            if analise.get("eh_comprovante"):
                valor = analise.get("valor")
                valor_txt = f"{valor:.2f}" if isinstance(valor, (float, int)) else "null"
                favorecido = (analise.get("favorecido") or "").replace("|", " ")[:120]
                text = f"[comprovante valor={valor_txt} favorecido={favorecido}]"
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
    from app.escalation import _NUMERO_INTERNO, processar_resposta_breno
    from app.meta_api import MetaAPIClient
    import os as _os

    _meta = MetaAPIClient(
        phone_number_id=_os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=_os.environ.get("WHATSAPP_TOKEN", ""),
    )

    if phone == _NUMERO_INTERNO:
        # Mensagem do Breno — processar como resposta de escalação
        logger.info("Mensagem do número interno detectada — processando como resposta do Breno")
        await processar_resposta_breno(meta_client=_meta, texto_resposta=text)
        return

    # Rotear e responder (fora do session para evitar lock longo)
    await route_message(phone=phone, phone_hash=phone_hash, text=text, meta_message_id=meta_id)
