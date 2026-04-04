import pytest
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, RemarketingQueue
from app.remarketing import (
    can_schedule_remarketing,
    schedule_time_remarketing,
    schedule_behavioral_remarketing,
    cancel_pending_remarketing,
    REMARKETING_SEQUENCE,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def contact(db):
    c = Contact(phone_hash="test_hash", stage="cold_lead", remarketing_count=0)
    db.add(c)
    db.commit()
    return c


def test_can_schedule_when_no_history(db, contact):
    assert can_schedule_remarketing(db, contact.id) is True


def test_cannot_schedule_when_count_is_5(db, contact):
    contact.remarketing_count = 5
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is False


def test_cannot_schedule_when_sent_today(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC),
        sent_at=datetime.now(UTC),
        status="sent",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(rq)
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is False


def test_schedule_time_remarketing_creates_queue_entry(db, contact):
    schedule_time_remarketing(db, contact.id, template="follow_up_geral",
                              delay_hours=2, position=1)
    queue = db.query(RemarketingQueue).filter_by(contact_id=contact.id).all()
    assert len(queue) == 1
    assert queue[0].template_name == "follow_up_geral"
    assert queue[0].trigger_type == "time"


def test_cancel_pending_removes_pending_entries(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) + timedelta(hours=2),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(rq)
    db.commit()

    cancel_pending_remarketing(db, contact.id)
    cancelled = db.query(RemarketingQueue).filter_by(contact_id=contact.id, status="cancelled").first()
    assert cancelled is not None


def test_informational_templates_dont_count(db, contact):
    # Templates informativos (counts_toward_limit=False) não incrementam o contador
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="opcoes_pagamento",
        scheduled_for=datetime.now(UTC),
        sent_at=datetime.now(UTC),
        status="sent",
        sequence_position=0,
        trigger_type="behavior",
        counts_toward_limit=False,
    )
    db.add(rq)
    db.commit()
    # Ainda deve poder agendar
    assert can_schedule_remarketing(db, contact.id) is True
