import uuid
from datetime import datetime, UTC
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(20))  # número real para envio Meta API
    push_name: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(50), default="new")
    collected_name: Mapped[str | None] = mapped_column(String(255))
    patient_type: Mapped[str | None] = mapped_column(String(50))
    interest_score: Mapped[int | None] = mapped_column(Integer)
    remarketing_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Perfil permanente do paciente (D-13) — nunca expira, salvo no PostgreSQL
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    dietbox_patient_id: Mapped[int | None] = mapped_column(Integer)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="contact")
    remarketing_queue: Mapped[list["RemarketingQueue"]] = relationship(back_populates="contact")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), default="new")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(50), default="em_aberto")
    # outcome valores: converteu | abandonou | agendou | arquivou | em_aberto

    contact: Mapped["Contact"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation",
                                                      order_by="Message.sent_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("meta_message_id", name="uq_meta_message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meta_message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"))
    direction: Mapped[str] = mapped_column(String(10))  # inbound | outbound
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending → retrying (1ª falha) → retrying (2ª) → failed (3ª) | processed (sucesso)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class RemarketingQueue(Base):
    __tablename__ = "remarketing_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(100))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | sent | cancelled | failed
    sequence_position: Mapped[int] = mapped_column(Integer, default=1)
    trigger_type: Mapped[str] = mapped_column(String(20))  # time | behavior
    counts_toward_limit: Mapped[bool] = mapped_column(Boolean, default=True)

    contact: Mapped["Contact"] = relationship(back_populates="remarketing_queue")


class PendingEscalation(Base):
    """
    Registra perguntas pendentes de resposta do Breno (escalações internas).

    Ciclo de vida: aguardando → respondido | timeout
    Número 31 99205-9211 NUNCA exposto ao paciente — armazenado apenas para roteamento interno.
    """

    __tablename__ = "pending_escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)
    pergunta_original: Mapped[str] = mapped_column(Text)
    contexto: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aguardando")
    # status: aguardando | respondido | timeout
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resposta_breno: Mapped[str | None] = mapped_column(Text)
    next_reminder_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
