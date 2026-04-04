import pytest
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, Conversation, Message
from app.retry import get_messages_to_retry, compute_backoff_seconds, MAX_RETRIES


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_gets_retrying_messages_older_than_30s(db):
    contact = Contact(phone_hash="h1", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()

    old_msg = Message(
        meta_message_id="old_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=1,
        sent_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    recent_msg = Message(
        meta_message_id="recent_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=1,
        sent_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db.add_all([old_msg, recent_msg])
    db.commit()

    result = get_messages_to_retry(db)
    assert len(result) == 1
    assert result[0].meta_message_id == "old_001"


def test_backoff_exponential():
    assert compute_backoff_seconds(1) == 1    # 4^0
    assert compute_backoff_seconds(2) == 4    # 4^1
    assert compute_backoff_seconds(3) == 16   # 4^2


def test_message_marked_failed_after_max_retries(db):
    contact = Contact(phone_hash="h2", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()
    msg = Message(
        meta_message_id="fail_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=MAX_RETRIES,
        sent_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    db.add(msg)
    db.commit()

    from app.retry import mark_exhausted_as_failed
    mark_exhausted_as_failed(db)
    db.refresh(msg)
    assert msg.processing_status == "failed"
