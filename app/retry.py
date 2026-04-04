import logging
import time
from datetime import datetime, UTC, timedelta
from sqlalchemy.orm import Session
from app.models import Message

logger = logging.getLogger(__name__)
RETRY_AFTER_SECONDS = 30
MAX_RETRIES = 3
BACKOFF_BASE = 4  # 4^0=1s, 4^1=4s, 4^2=16s


def compute_backoff_seconds(retry_count: int) -> int:
    return BACKOFF_BASE ** (retry_count - 1)


def get_messages_to_retry(db: Session) -> list[Message]:
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
        logger.error(f"Mensagem {msg.meta_message_id} falhou após {MAX_RETRIES} tentativas")
    db.commit()


def _retry_failed_messages():
    """Job APScheduler a cada 5 min: reprocessa mensagens em retry com backoff."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        mark_exhausted_as_failed(db)
        messages = get_messages_to_retry(db)
        logger.info(f"Reprocessando {len(messages)} mensagens em retry")
        for msg in messages:
            backoff = compute_backoff_seconds(msg.retry_count + 1)
            msg.retry_count += 1
            msg.processing_status = "retrying"
            db.commit()
            time.sleep(backoff)
            # Reimportar para evitar circular import
            from app.router import route_message
            import asyncio
            # Extrair phone do conversation → contact
            contact = msg.conversation.contact
            if contact and contact.phone_e164:
                asyncio.run(route_message(
                    phone=contact.phone_e164,
                    phone_hash=contact.phone_hash,
                    text=msg.content,
                    meta_message_id=msg.meta_message_id,
                ))
