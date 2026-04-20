"""
Gerenciamento de etiquetas (tags) dos contatos.

Etiquetas válidas:
  novo_lead          → primeiro contato, ainda não qualificado
  aguardando_pagamento → consulta agendada, pagamento pendente
  agendado           → pagamento confirmado, consulta marcada
  remarketing        → em sequência de follow-up automático
  lead_perdido       → desistiu ou sem resposta após sequência completa
  OK                 → atendimento concluído com sucesso
"""
from __future__ import annotations

import logging
from enum import Enum

from sqlalchemy.orm import Session

from app.models import Contact

logger = logging.getLogger(__name__)

_LEGACY_STAGE_MAP = {
    "new": "novo_lead",
    "cold_lead": "novo_lead",
    "remarketing_sequence": "remarketing",
}


class Tag(str, Enum):
    NOVO_LEAD = "novo_lead"
    AGUARDANDO_PAGAMENTO = "aguardando_pagamento"
    AGENDADO = "agendado"
    REMARKETING = "remarketing"
    LEAD_PERDIDO = "lead_perdido"
    OK = "ok"


# Transições permitidas (None = qualquer origem é válida)
_TRANSICOES_VALIDAS: dict[Tag, set[Tag] | None] = {
    Tag.NOVO_LEAD: None,                                              # qualquer origem
    Tag.AGUARDANDO_PAGAMENTO: {Tag.NOVO_LEAD, Tag.REMARKETING},
    Tag.AGENDADO: {Tag.AGUARDANDO_PAGAMENTO},
    Tag.REMARKETING: {Tag.NOVO_LEAD, Tag.AGUARDANDO_PAGAMENTO},
    Tag.LEAD_PERDIDO: {Tag.NOVO_LEAD, Tag.REMARKETING, Tag.AGUARDANDO_PAGAMENTO},
    Tag.OK: {Tag.AGENDADO},
}


def get_tag(contact: Contact) -> Tag | None:
    """Retorna a tag atual do contato ou None se não definida."""
    raw = getattr(contact, "stage", None)
    raw = _LEGACY_STAGE_MAP.get(raw, raw)
    try:
        return Tag(raw) if raw else None
    except ValueError:
        return None


def set_tag(db: Session, contact: Contact, nova_tag: Tag, *, force: bool = False) -> bool:
    """
    Aplica nova_tag ao contato se a transição for válida.

    Args:
        force: pula validação de transição (uso interno — migrações, correções)

    Returns:
        True se aplicado, False se transição inválida.
    """
    tag_atual = get_tag(contact)

    if not force:
        origens_validas = _TRANSICOES_VALIDAS.get(nova_tag)
        if origens_validas is not None and tag_atual not in origens_validas:
            logger.warning(
                "Transição inválida %s → %s para contato %s",
                tag_atual, nova_tag, contact.id,
            )
            return False

    contact.stage = nova_tag.value
    db.add(contact)
    db.flush()
    logger.info("Tag %s → %s (contato %s)", tag_atual, nova_tag, contact.id)
    return True


def set_tag_by_phone_hash(
    db: Session, phone_hash: str, nova_tag: Tag, *, force: bool = False
) -> bool:
    """Atalho: aplica tag buscando contato pelo phone_hash."""
    contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
    if not contact:
        logger.warning("Contato com hash %s não encontrado", phone_hash[:12])
        return False
    return set_tag(db, contact, nova_tag, force=force)
