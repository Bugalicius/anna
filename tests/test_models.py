import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, Conversation, Message, RemarketingQueue


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_contact(db):
    contact = Contact(phone_hash="abc123", push_name="Maria", stage="new")
    db.add(contact)
    db.commit()
    assert contact.id is not None
    assert contact.remarketing_count == 0


def test_contact_stage_values(db):
    valid_stages = ["new", "collecting_info", "presenting", "scheduling",
                    "awaiting_payment", "confirmed", "cold_lead",
                    "remarketing_sequence", "archived"]
    for stage in valid_stages:
        c = Contact(phone_hash=f"hash_{stage}", stage=stage)
        db.add(c)
    db.commit()
    assert db.query(Contact).count() == len(valid_stages)


def test_message_dedup_by_meta_id(db):
    contact = Contact(phone_hash="h1", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()
    msg = Message(meta_message_id="META_MSG_001", conversation_id=conv.id,
                  direction="inbound", content="oi", message_type="text",
                  processing_status="pending")
    db.add(msg)
    db.commit()
    # Deve ter constraint UNIQUE em meta_message_id
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        msg2 = Message(meta_message_id="META_MSG_001", conversation_id=conv.id,
                       direction="inbound", content="oi2", message_type="text")
        db.add(msg2)
        db.commit()


def test_remarketing_queue_counts_flag(db):
    contact = Contact(phone_hash="h2", stage="cold_lead")
    db.add(contact)
    db.flush()
    rq = RemarketingQueue(contact_id=contact.id, template_name="follow_up_geral",
                          scheduled_for=__import__('datetime').datetime.now(__import__('datetime').timezone.utc),
                          status="pending", sequence_position=1,
                          trigger_type="time", counts_toward_limit=True)
    db.add(rq)
    db.commit()
    assert rq.counts_toward_limit is True
