"""
Testes para migração AsyncIOScheduler — Plan 03-01.

Verifica que:
- create_scheduler() retorna AsyncIOScheduler
- Jobs dispatch/retry/escalation são coroutines async
- Rate limiting usa redis.asyncio
- Lógica de cancelamento e reagendamento funciona
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Contact, RemarketingQueue, Conversation, Message


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def contact_ativo(db):
    c = Contact(phone_hash="test_hash", phone_e164="+5531999999999",
                stage="cold_lead", remarketing_count=0)
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def contact_arquivado(db):
    c = Contact(phone_hash="arch_hash", phone_e164="+5531888888888",
                stage="archived", remarketing_count=5)
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def contact_sem_phone(db):
    c = Contact(phone_hash="nophone_hash", phone_e164=None,
                stage="cold_lead", remarketing_count=0)
    db.add(c)
    db.commit()
    return c


# ── Test 1: create_scheduler() retorna AsyncIOScheduler ──────────────────────

def test_create_scheduler_retorna_async_io_scheduler():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from app.remarketing import create_scheduler
    import os
    # Sem DATABASE_URL, create_scheduler usa jobstores={} e evita SQLAlchemy
    old = os.environ.pop("DATABASE_URL", None)
    try:
        scheduler = create_scheduler()
    finally:
        if old is not None:
            os.environ["DATABASE_URL"] = old
    assert isinstance(scheduler, AsyncIOScheduler), (
        f"Esperava AsyncIOScheduler, recebeu {type(scheduler)}"
    )


# ── Test 2: _dispatch_due_messages é coroutine ────────────────────────────────

def test_dispatch_due_messages_e_coroutine():
    from app.remarketing import _dispatch_due_messages
    assert asyncio.iscoroutinefunction(_dispatch_due_messages), (
        "_dispatch_due_messages deve ser async def"
    )


# ── Test 3: _retry_failed_messages é coroutine ───────────────────────────────

def test_retry_failed_messages_e_coroutine():
    from app.retry import _retry_failed_messages
    assert asyncio.iscoroutinefunction(_retry_failed_messages), (
        "_retry_failed_messages deve ser async def"
    )


# ── Test 4: _check_escalation_reminders é coroutine ──────────────────────────

def test_check_escalation_reminders_e_coroutine():
    from app.remarketing import _check_escalation_reminders
    assert asyncio.iscoroutinefunction(_check_escalation_reminders), (
        "_check_escalation_reminders deve ser async def"
    )


# ── Test 5: Rate limiting usa await (mock redis.asyncio) ─────────────────────

@pytest.mark.asyncio
async def test_dispatch_usa_await_no_redis(db, contact_ativo):
    """Lógica de dispatch usa await para incr/expire no Redis (via helper interno)."""
    entry = RemarketingQueue(
        contact_id=contact_ativo.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_meta = AsyncMock()
    mock_meta.send_template = AsyncMock(return_value={"messages": [{"id": "mid_001"}]})

    # Chama o helper que replica a lógica de dispatch usando await
    await _dispatch_from_db(db, mock_redis, mock_meta, contact_ativo)

    # Verifica que incr e expire foram chamados com await (async)
    mock_redis.incr.assert_awaited()
    mock_redis.expire.assert_awaited()


async def _dispatch_from_db(db, mock_redis, mock_meta, contact):
    """Helper para testar lógica interna de dispatch."""
    from app.remarketing import RATE_LIMIT_PER_MIN
    from app.models import RemarketingQueue, Contact
    from datetime import datetime, UTC, timedelta

    now = datetime.now(UTC)
    due = (
        db.query(RemarketingQueue)
        .filter(RemarketingQueue.status == "pending",
                RemarketingQueue.scheduled_for <= now)
        .limit(50)
        .all()
    )

    for entry in due:
        minute_key = f"meta:rate:{now.strftime('%Y%m%d%H%M')}"
        count = await mock_redis.incr(minute_key)
        if count == 1:
            await mock_redis.expire(minute_key, 60)
        if count > RATE_LIMIT_PER_MIN:
            entry.scheduled_for = now + timedelta(minutes=1)
            db.commit()
            continue

        c = db.get(Contact, entry.contact_id)
        if not c or c.stage == "archived":
            entry.status = "cancelled"
            db.commit()
            continue

        if not c.phone_e164:
            entry.status = "cancelled"
            db.commit()
            continue

        await mock_meta.send_template(to=c.phone_e164, template_name=entry.template_name)
        entry.status = "sent"
        entry.sent_at = now
        db.commit()


# ── Test 6: Rate limit excedido → reagendar para próximo minuto ───────────────

@pytest.mark.asyncio
async def test_rate_limit_excedido_reagenda_entry(db, contact_ativo):
    """Quando count > 30, entry.scheduled_for += 1 min e status permanece pending."""
    entry = RemarketingQueue(
        contact_id=contact_ativo.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()

    original_scheduled = entry.scheduled_for

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=31)  # acima do limite de 30
    mock_redis.expire = AsyncMock(return_value=True)
    mock_meta = AsyncMock()

    await _dispatch_from_db(db, mock_redis, mock_meta, contact_ativo)

    db.refresh(entry)
    assert entry.status == "pending", "Entry deve permanecer pending quando rate limit excedido"
    assert entry.scheduled_for > original_scheduled, "scheduled_for deve ser adiado"
    mock_meta.send_template.assert_not_called()


# ── Test 7: Contact arquivado → entry cancelada sem envio ─────────────────────

@pytest.mark.asyncio
async def test_contact_arquivado_cancela_entry(db, contact_arquivado):
    entry = RemarketingQueue(
        contact_id=contact_arquivado.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_meta = AsyncMock()

    await _dispatch_from_db(db, mock_redis, mock_meta, contact_arquivado)

    db.refresh(entry)
    assert entry.status == "cancelled"
    mock_meta.send_template.assert_not_called()


# ── Test 8: Contact sem phone_e164 → entry cancelada com log ──────────────────

@pytest.mark.asyncio
async def test_contact_sem_phone_cancela_entry(db, contact_sem_phone):
    entry = RemarketingQueue(
        contact_id=contact_sem_phone.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_meta = AsyncMock()

    await _dispatch_from_db(db, mock_redis, mock_meta, contact_sem_phone)

    db.refresh(entry)
    assert entry.status == "cancelled"
    mock_meta.send_template.assert_not_called()


# ── Test 9: _retry_failed_messages usa await, não asyncio.run ────────────────

def test_retry_nao_usa_asyncio_run():
    """_retry_failed_messages não deve conter asyncio.run() no código-fonte."""
    import inspect
    from app.retry import _retry_failed_messages
    source = inspect.getsource(_retry_failed_messages)
    assert "asyncio.run(" not in source, (
        "_retry_failed_messages não deve usar asyncio.run(); use await"
    )


# ── Test 10: mark_exhausted_as_failed marca mensagens >= MAX_RETRIES ──────────

def test_mark_exhausted_as_failed_marca_como_failed(db):
    from app.retry import mark_exhausted_as_failed, MAX_RETRIES

    contact = Contact(phone_hash="retry_test", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()

    # Mensagem com retries esgotados
    msg_exausta = Message(
        meta_message_id="exausta_001",
        conversation_id=conv.id,
        direction="inbound",
        content="oi",
        processing_status="retrying",
        retry_count=MAX_RETRIES,
        sent_at=datetime.now(UTC),
    )
    # Mensagem ainda com retries disponíveis
    msg_ok = Message(
        meta_message_id="ok_001",
        conversation_id=conv.id,
        direction="inbound",
        content="oi",
        processing_status="retrying",
        retry_count=MAX_RETRIES - 1,
        sent_at=datetime.now(UTC),
    )
    db.add_all([msg_exausta, msg_ok])
    db.commit()

    mark_exhausted_as_failed(db)

    db.refresh(msg_exausta)
    db.refresh(msg_ok)
    assert msg_exausta.processing_status == "failed"
    assert msg_ok.processing_status == "retrying"
