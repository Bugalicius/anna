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

    # Extrair mensagens do payload aninhado da Meta
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                background_tasks.add_task(process_message, message, value.get("metadata", {}))

    return {"status": "ok"}


async def process_message(message: dict, metadata: dict):
    """Processa uma mensagem em background. Deduplicação + roteamento."""
    from app.database import SessionLocal
    from app.models import Message, Contact, Conversation
    from app.router import route_message
    import hashlib
    from datetime import datetime, UTC

    meta_id = message.get("id", "")
    phone = message.get("from", "")
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
