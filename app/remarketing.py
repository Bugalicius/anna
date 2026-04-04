import logging
import os
from datetime import datetime, UTC, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy.orm import Session
from app.models import Contact, RemarketingQueue

logger = logging.getLogger(__name__)

REMARKETING_SEQUENCE = [
    {"position": 1, "template": "follow_up_geral", "delay_hours": 2},
    {"position": 2, "template": "objecao_preco", "delay_hours": 24},
    {"position": 3, "template": "urgencia_vagas", "delay_hours": 48},
    {"position": 4, "template": "depoimento", "delay_hours": 72},
    {"position": 5, "template": "oferta_especial", "delay_hours": 168},
]

BEHAVIORAL_TEMPLATES = {
    "pediu_preco": ("objecao_preco", True),
    "disse_vou_pensar": ("follow_up_geral", True),
    "pediu_parcelamento": ("opcoes_pagamento", False),
    "mencionou_concorrente": ("diferenciacao", False),
}

MAX_REMARKETING = 5
RATE_LIMIT_PER_MIN = 30


def can_schedule_remarketing(db: Session, contact_id: str) -> bool:
    """Verifica se o contato pode receber mais mensagens de remarketing."""
    contact = db.get(Contact, contact_id)
    if not contact or contact.remarketing_count >= MAX_REMARKETING:
        return False

    # Verifica se já foi enviada alguma mensagem hoje
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(RemarketingQueue)
        .filter(
            RemarketingQueue.contact_id == contact_id,
            RemarketingQueue.sent_at >= today_start,
            RemarketingQueue.counts_toward_limit.is_(True),
        )
        .first()
    )
    return sent_today is None


def schedule_time_remarketing(db: Session, contact_id: str, template: str,
                               delay_hours: float, position: int) -> "RemarketingQueue | None":
    if not can_schedule_remarketing(db, contact_id):
        return None
    scheduled = datetime.now(UTC) + timedelta(hours=delay_hours)
    entry = RemarketingQueue(
        contact_id=contact_id,
        template_name=template,
        scheduled_for=scheduled,
        status="pending",
        sequence_position=position,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()
    return entry


def schedule_behavioral_remarketing(db: Session, contact_id: str, signals: list[str]):
    for signal in signals:
        if signal not in BEHAVIORAL_TEMPLATES:
            continue
        template, counts = BEHAVIORAL_TEMPLATES[signal]
        if counts and not can_schedule_remarketing(db, contact_id):
            continue
        entry = RemarketingQueue(
            contact_id=contact_id,
            template_name=template,
            scheduled_for=datetime.now(UTC) + timedelta(minutes=5),
            status="pending",
            sequence_position=0,
            trigger_type="behavior",
            counts_toward_limit=counts,
        )
        db.add(entry)
    db.commit()


def cancel_pending_remarketing(db: Session, contact_id: str):
    pending = (
        db.query(RemarketingQueue)
        .filter_by(contact_id=contact_id, status="pending")
        .all()
    )
    for entry in pending:
        entry.status = "cancelled"
    db.commit()


def _dispatch_due_messages():
    """Job APScheduler: processa entradas pendentes da fila de remarketing."""
    from app.database import SessionLocal
    from app.meta_api import MetaAPIClient
    import redis

    redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    meta = MetaAPIClient(
        phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("META_ACCESS_TOKEN", ""),
    )

    with SessionLocal() as db:
        now = datetime.now(UTC)
        due = (
            db.query(RemarketingQueue)
            .filter(RemarketingQueue.status == "pending", RemarketingQueue.scheduled_for <= now)
            .order_by(RemarketingQueue.scheduled_for)
            .limit(50)
            .all()
        )

        for entry in due:
            # Rate limit Redis: máx 30/min
            minute_key = f"meta:rate:{now.strftime('%Y%m%d%H%M')}"
            count = redis_client.incr(minute_key)
            if count == 1:
                redis_client.expire(minute_key, 60)
            if count > RATE_LIMIT_PER_MIN:
                # Reagendar para próximo minuto
                entry.scheduled_for = now + timedelta(minutes=1)
                db.commit()
                continue

            contact = db.get(Contact, entry.contact_id)
            if not contact or contact.stage == "archived":
                entry.status = "cancelled"
                db.commit()
                continue

            if not contact.phone_e164:
                logger.error(f"Contato {contact.id} sem phone_e164, pulando")
                entry.status = "cancelled"
                db.commit()
                continue

            try:
                meta.send_template(to=contact.phone_e164, template_name=entry.template_name)
                entry.status = "sent"
                entry.sent_at = now
                if entry.counts_toward_limit:
                    contact.remarketing_count += 1
                if contact.remarketing_count >= MAX_REMARKETING:
                    contact.stage = "archived"
                db.commit()
                import time; time.sleep(2)  # intervalo mínimo de 2s entre disparos
            except Exception as e:
                logger.error(f"Falha ao enviar remarketing {entry.id}: {e}")
                entry.status = "failed"
                db.commit()


def create_scheduler() -> BackgroundScheduler:
    jobstores = {"default": SQLAlchemyJobStore(url=os.environ.get("DATABASE_URL", ""))}
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.add_job(_dispatch_due_messages, "interval", minutes=1, id="remarketing_dispatcher",
                      replace_existing=True)
    return scheduler
