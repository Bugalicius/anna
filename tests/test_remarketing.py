"""
Testes para logica de negocio do remarketing — Plans 03-01 e 03-02.

Cobre:
- Sequencia corrigida 24h/7d/30d, MAX=3
- Remocao de BEHAVIORAL_TEMPLATES e schedule_behavioral_remarketing
- can_schedule_remarketing: limite e lead_perdido
- Intencao recusou_remarketing no orquestrador
- Handler recusou_remarketing no router (farewell + lead_perdido + cancel queue)
- Verificacao de conversa ativa no Redis antes de disparar
"""
from __future__ import annotations

import pytest
from datetime import datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, RemarketingQueue
from app.remarketing import (
    can_schedule_remarketing,
    schedule_time_remarketing,
    cancel_pending_remarketing,
    REMARKETING_SEQUENCE,
)


# ── Fixtures de banco de dados ────────────────────────────────────────────────

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


# ── Testes originais (mantidos) ────────────────────────────────────────────────

def test_can_schedule_when_no_history(db, contact):
    assert can_schedule_remarketing(db, contact.id) is True


def test_cannot_schedule_when_sent_today(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="ana_followup_24h",
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
    schedule_time_remarketing(db, contact.id, template="ana_followup_24h",
                              delay_hours=24, position=1)
    queue = db.query(RemarketingQueue).filter_by(contact_id=contact.id).all()
    assert len(queue) == 1
    assert queue[0].template_name == "ana_followup_24h"
    assert queue[0].trigger_type == "time"


def test_cancel_pending_removes_pending_entries(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="ana_followup_24h",
        scheduled_for=datetime.now(UTC) + timedelta(hours=24),
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
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="ana_followup_24h",
        scheduled_for=datetime.now(UTC),
        sent_at=datetime.now(UTC),
        status="sent",
        sequence_position=0,
        trigger_type="behavior",
        counts_toward_limit=False,
    )
    db.add(rq)
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is True


# ── Task 1: Sequencia e MAX corrigidos ────────────────────────────────────────

def test_remarketing_sequence_tem_3_entries():
    assert len(REMARKETING_SEQUENCE) == 3


def test_remarketing_sequence_delays_corretos():
    delays = [entry["delay_hours"] for entry in REMARKETING_SEQUENCE]
    assert delays == [24, 168, 720]


def test_max_remarketing_igual_3():
    from app.remarketing import MAX_REMARKETING
    assert MAX_REMARKETING == 3


def test_behavioral_templates_removido():
    import app.remarketing as mod
    assert not hasattr(mod, "BEHAVIORAL_TEMPLATES"), "BEHAVIORAL_TEMPLATES deve ser removido"


def test_schedule_behavioral_remarketing_removido_ou_raises():
    import app.remarketing as mod
    if hasattr(mod, "schedule_behavioral_remarketing"):
        fn = mod.schedule_behavioral_remarketing
        with pytest.raises(NotImplementedError):
            fn(None, "contact_id", [])
    # Se nao existe, teste passa automaticamente


def test_can_schedule_remarketing_false_quando_count_gte_3():
    from app.remarketing import can_schedule_remarketing
    db = MagicMock()
    contact = MagicMock()
    contact.remarketing_count = 3
    contact.stage = "remarketing"
    db.get.return_value = contact
    assert can_schedule_remarketing(db, "contact-id") is False


def test_can_schedule_remarketing_false_quando_lead_perdido():
    from app.remarketing import can_schedule_remarketing
    db = MagicMock()
    contact = MagicMock()
    contact.remarketing_count = 0
    contact.stage = "lead_perdido"
    db.get.return_value = contact
    assert can_schedule_remarketing(db, "contact-id") is False


def test_cannot_schedule_when_count_is_3(db, contact):
    contact.remarketing_count = 3
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is False


# ── Task 1: Orquestrador — recusou_remarketing ────────────────────────────────

def test_orchestrator_intencao_recusou_remarketing_valida():
    """recusou_remarketing deve estar no Literal IntencaoType."""
    import typing
    from app.agents.orchestrator import IntencaoType
    args = typing.get_args(IntencaoType)
    assert "recusou_remarketing" in args


def test_rotear_recusou_remarketing_retorna_agente_correto():
    from app.agents.orchestrator import rotear
    with patch("app.agents.orchestrator._classificar_intencao",
               return_value=("recusou_remarketing", 0.95)):
        resultado = rotear("nao tenho interesse", stage_atual="remarketing")
    assert resultado["agente"] == "remarketing_recusa"
    assert resultado["intencao"] == "recusou_remarketing"


def test_classificar_intencao_recusou_remarketing():
    """_classificar_intencao retorna recusou_remarketing quando LLM retorna essa intencao."""
    from app.agents.orchestrator import _classificar_intencao
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"intencao": "recusou_remarketing", "confianca": 0.9}')]
    with patch("anthropic.Anthropic") as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.messages.create.return_value = mock_response
        intencao, confianca = _classificar_intencao("nao tenho interesse")
    assert intencao == "recusou_remarketing"
    assert confianca == 0.9


# ── Task 2: Handler recusou_remarketing no router ─────────────────────────────

MSG_ENCERRAMENTO_ESPERADA = (
    "Tudo bem! Posso perguntar o que pesou na decisão? "
    "Só pra melhorar nosso atendimento 😊"
)


def _make_remarketing_mocks(contact_id: str = "contact-id-1"):
    contact_mock = MagicMock()
    contact_mock.stage = "remarketing"
    contact_mock.collected_name = None
    contact_mock.push_name = None
    contact_mock.first_name = None
    contact_mock.id = contact_id
    db_mock = MagicMock()
    db_mock.query.return_value.filter_by.return_value.first.return_value = contact_mock
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    meta_mock = AsyncMock()
    return contact_mock, db_mock, meta_mock


def _recusou_state():
    return {
        "goal": "recusou_remarketing",
        "status": "recusou_remarketing",
        "collected_data": {"nome": None},
        "appointment": {"id_agenda": None},
        "history": [],
        "flags": {},
    }


@pytest.mark.asyncio
async def test_router_recusou_remarketing_envia_mensagem_encerramento():
    """Quando engine retorna MSG_ENCERRAMENTO_REMARKETING, Ana envia a mensagem."""
    from app.router import route_message, MSG_ENCERRAMENTO_REMARKETING

    _, db_mock, meta_mock = _make_remarketing_mocks("contact-id-1")
    enviadas = []

    async def capturar(phone, msg):
        enviadas.append(msg)

    meta_mock.send_text.side_effect = capturar

    with (
        patch("app.router.SessionLocal", return_value=db_mock),
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        patch("app.router.cancel_pending_remarketing"),
        patch("app.router.set_tag"),
        patch("app.conversation.engine.engine.handle_message",
              new_callable=AsyncMock, return_value=[MSG_ENCERRAMENTO_REMARKETING]),
        patch("app.conversation.state.load_state",
              new_callable=AsyncMock, return_value=_recusou_state()),
        patch("app.conversation.state.save_state", new_callable=AsyncMock),
        patch("app.conversation.state.delete_state", new_callable=AsyncMock),
    ):
        await route_message(
            phone="+5531999999999",
            phone_hash="abc123hash",
            text="nao tenho interesse",
            meta_message_id="msg-001",
        )

    assert MSG_ENCERRAMENTO_ESPERADA in enviadas


@pytest.mark.asyncio
async def test_router_recusou_remarketing_chama_set_tag_lead_perdido():
    """Apos recusou_remarketing, set_tag(LEAD_PERDIDO) deve ser chamado."""
    from app.router import route_message, MSG_ENCERRAMENTO_REMARKETING
    from app.tags import Tag

    _, db_mock, meta_mock = _make_remarketing_mocks("contact-id-2")

    with (
        patch("app.router.SessionLocal", return_value=db_mock),
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        patch("app.router.cancel_pending_remarketing"),
        patch("app.router.set_tag") as mock_set_tag,
        patch("app.conversation.engine.engine.handle_message",
              new_callable=AsyncMock, return_value=[MSG_ENCERRAMENTO_REMARKETING]),
        patch("app.conversation.state.load_state",
              new_callable=AsyncMock, return_value=_recusou_state()),
        patch("app.conversation.state.save_state", new_callable=AsyncMock),
        patch("app.conversation.state.delete_state", new_callable=AsyncMock),
    ):
        await route_message(
            phone="+5531999999998",
            phone_hash="abc456hash",
            text="pode tirar meu numero",
            meta_message_id="msg-002",
        )

    tags_usadas = [call.args[2] for call in mock_set_tag.call_args_list if len(call.args) >= 3]
    assert Tag.LEAD_PERDIDO in tags_usadas


@pytest.mark.asyncio
async def test_router_recusou_remarketing_chama_cancel_pending():
    """Apos recusou_remarketing, cancel_pending_remarketing deve ser chamado."""
    from app.router import route_message, MSG_ENCERRAMENTO_REMARKETING

    _, db_mock, meta_mock = _make_remarketing_mocks("contact-id-3")

    with (
        patch("app.router.SessionLocal", return_value=db_mock),
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        patch("app.router.cancel_pending_remarketing") as mock_cancel,
        patch("app.router.set_tag"),
        patch("app.conversation.engine.engine.handle_message",
              new_callable=AsyncMock, return_value=[MSG_ENCERRAMENTO_REMARKETING]),
        patch("app.conversation.state.load_state",
              new_callable=AsyncMock, return_value=_recusou_state()),
        patch("app.conversation.state.save_state", new_callable=AsyncMock),
        patch("app.conversation.state.delete_state", new_callable=AsyncMock),
    ):
        await route_message(
            phone="+5531999999997",
            phone_hash="abc789hash",
            text="deixa pra la",
            meta_message_id="msg-003",
        )

    assert mock_cancel.called


@pytest.mark.asyncio
async def test_router_recusou_remarketing_deleta_estado_redis():
    """Apos recusou_remarketing, delete_state deve ser chamado para limpar Redis."""
    from app.router import route_message, MSG_ENCERRAMENTO_REMARKETING

    _, db_mock, meta_mock = _make_remarketing_mocks("contact-id-4")

    with (
        patch("app.router.SessionLocal", return_value=db_mock),
        patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        patch("app.router.cancel_pending_remarketing"),
        patch("app.router.set_tag"),
        patch("app.conversation.engine.engine.handle_message",
              new_callable=AsyncMock, return_value=[MSG_ENCERRAMENTO_REMARKETING]),
        patch("app.conversation.state.load_state",
              new_callable=AsyncMock, return_value=_recusou_state()),
        patch("app.conversation.state.save_state", new_callable=AsyncMock),
        patch("app.conversation.state.delete_state",
              new_callable=AsyncMock) as mock_del,
    ):
        await route_message(
            phone="+5531999999996",
            phone_hash="abc000hash",
            text="nao vou marcar",
            meta_message_id="msg-004",
        )

    mock_del.assert_called_once_with("abc000hash")


def test_msg_encerramento_constante_existe_no_router():
    """Mensagem de encerramento deve ser constante no router com texto exato do D-09."""
    import app.router as router_mod
    assert hasattr(router_mod, "MSG_ENCERRAMENTO_REMARKETING")
    assert router_mod.MSG_ENCERRAMENTO_REMARKETING == MSG_ENCERRAMENTO_ESPERADA


# ── Task 3: Verificacao de conversa ativa no Redis antes de disparar ──────────

@pytest.mark.asyncio
async def test_dispatch_skip_quando_conversa_ativa():
    """Se agent_state:{phone_hash} existe no Redis, entry nao e disparada."""
    from app.remarketing import _dispatch_from_db

    entry = MagicMock()
    entry.contact_id = "contact-id-5"
    entry.template_name = "ana_followup_24h"
    entry.counts_toward_limit = True
    entry.id = "entry-id-1"
    entry.status = "pending"

    contact = MagicMock()
    contact.stage = "remarketing"
    contact.phone_e164 = "+5531999999995"
    contact.phone_hash = "hash12345"
    contact.remarketing_count = 0

    db = MagicMock()
    db.get.return_value = contact

    redis_client = AsyncMock()
    redis_client.incr.return_value = 1
    redis_client.expire.return_value = True
    redis_client.exists.return_value = 1  # conversa ativa

    meta = AsyncMock()

    await _dispatch_from_db([entry], db, redis_client, meta)

    meta.send_template.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_nao_cancela_entry_quando_conversa_ativa():
    """Entry pulada por conversa ativa permanece pending (nao e cancelada)."""
    from app.remarketing import _dispatch_from_db

    entry = MagicMock()
    entry.contact_id = "contact-id-6"
    entry.template_name = "ana_followup_24h"
    entry.counts_toward_limit = True
    entry.id = "entry-id-2"
    entry.status = "pending"

    contact = MagicMock()
    contact.stage = "remarketing"
    contact.phone_e164 = "+5531999999994"
    contact.phone_hash = "hash67890"
    contact.remarketing_count = 0

    db = MagicMock()
    db.get.return_value = contact

    redis_client = AsyncMock()
    redis_client.incr.return_value = 1
    redis_client.expire.return_value = True
    redis_client.exists.return_value = 1  # conversa ativa

    meta = AsyncMock()

    await _dispatch_from_db([entry], db, redis_client, meta)

    assert entry.status == "pending"


@pytest.mark.asyncio
async def test_dispatch_envia_quando_sem_conversa_ativa():
    """Quando nao ha chave agent_state no Redis, entry e disparada normalmente."""
    from app.remarketing import _dispatch_from_db
    from unittest.mock import patch

    entry = MagicMock()
    entry.contact_id = "contact-id-7"
    entry.template_name = "ana_followup_24h"
    entry.sequence_position = 1
    entry.counts_toward_limit = True
    entry.id = "entry-id-3"
    entry.status = "pending"

    contact = MagicMock()
    contact.stage = "remarketing"
    contact.phone_e164 = "+5531999999993"
    contact.phone_hash = "hash11111"
    contact.remarketing_count = 1

    db = MagicMock()
    db.get.return_value = contact

    redis_client = AsyncMock()
    redis_client.incr.return_value = 1
    redis_client.expire.return_value = True
    redis_client.exists.return_value = 0  # sem conversa ativa

    meta = AsyncMock()

    # _dispatch_from_db agora delega para _enviar_remarketing (refatoracao 03-03)
    with patch("app.remarketing._enviar_remarketing", new_callable=AsyncMock, return_value=True) as mock_enviar:
        await _dispatch_from_db([entry], db, redis_client, meta)
        mock_enviar.assert_called_once()

    assert entry.status == "sent"


@pytest.mark.asyncio
async def test_dispatch_entry_permanece_pending_apos_skip():
    """Entry pulada por conversa ativa permanece pending para o proximo ciclo."""
    from app.remarketing import _dispatch_from_db

    entry = MagicMock()
    entry.contact_id = "contact-id-8"
    entry.template_name = "ana_followup_7d"
    entry.counts_toward_limit = True
    entry.id = "entry-id-4"
    entry.status = "pending"

    contact = MagicMock()
    contact.stage = "remarketing"
    contact.phone_e164 = "+5531999999992"
    contact.phone_hash = "hashabc999"
    contact.remarketing_count = 0

    db = MagicMock()
    db.get.return_value = contact

    redis_client = AsyncMock()
    redis_client.incr.return_value = 1
    redis_client.expire.return_value = True
    redis_client.exists.return_value = 1  # conversa ativa

    meta = AsyncMock()

    await _dispatch_from_db([entry], db, redis_client, meta)

    assert entry.status == "pending"
