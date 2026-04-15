"""
Módulo de retry de mensagens — job async do APScheduler.

Responsabilidades:
- _retry_failed_messages(): reprocessa mensagens em status 'retrying' com backoff exponencial
- get_messages_to_retry(): consulta mensagens elegíveis para retry
- mark_exhausted_as_failed(): marca mensagens que esgotaram tentativas como 'failed'
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, UTC, timedelta
from sqlalchemy.orm import Session
from app.models import Message

logger = logging.getLogger(__name__)
RETRY_AFTER_SECONDS = 30
MAX_RETRIES = 3
BACKOFF_BASE = 4  # 4^0=1s, 4^1=4s, 4^2=16s


def compute_backoff_seconds(retry_count: int) -> int:
    """Calcula o tempo de espera exponencial para o retry."""
    return BACKOFF_BASE ** (retry_count - 1)


def get_messages_to_retry(db: Session) -> list[Message]:
    """Retorna mensagens em 'retrying' com retry_count < MAX_RETRIES e antigas o suficiente."""
    cutoff = datetime.now(UTC) - timedelta(seconds=RETRY_AFTER_SECONDS)
    return (
        db.query(Message)
        .filter(
            Message.processing_status == "retrying",
            Message.retry_count < MAX_RETRIES,
            Message.sent_at <= cutoff,
        )
        .all()
    )


def mark_exhausted_as_failed(db: Session) -> None:
    """Marca como 'failed' mensagens que já atingiram MAX_RETRIES."""
    exhausted = (
        db.query(Message)
        .filter(Message.processing_status == "retrying", Message.retry_count >= MAX_RETRIES)
        .all()
    )
    for msg in exhausted:
        msg.processing_status = "failed"
        logger.error("Mensagem %s falhou após %d tentativas", msg.meta_message_id, MAX_RETRIES)
    db.commit()


async def _retry_failed_messages() -> None:
    """Job APScheduler a cada 5 min: reprocessa mensagens em retry com backoff."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        mark_exhausted_as_failed(db)
        messages = get_messages_to_retry(db)
        logger.info("Reprocessando %d mensagens em retry", len(messages))
        for msg in messages:
            backoff = compute_backoff_seconds(msg.retry_count + 1)
            msg.retry_count += 1
            msg.processing_status = "retrying"
            db.commit()
            await asyncio.sleep(backoff)
            # Reimportar para evitar circular import
            from app.router import route_message
            contact = msg.conversation.contact
            if contact and contact.phone_e164:
                await route_message(
                    phone=contact.phone_e164,
                    phone_hash=contact.phone_hash,
                    text=msg.content,
                    meta_message_id=msg.meta_message_id,
                )
