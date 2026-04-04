import logging
import os
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from app.meta_api import verify_signature

router = APIRouter()
logger = logging.getLogger(__name__)

APP_SECRET = os.environ.get("META_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")


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

    # Rotear e responder (fora do session para evitar lock longo)
    await route_message(phone=phone, phone_hash=phone_hash, text=text, meta_message_id=meta_id)
