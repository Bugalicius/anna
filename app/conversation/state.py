"""Compatibilidade para o estado usado pelo orchestrator v2.

O cutover manteve a implementação persistente em ``app.conversation_legacy.state``.
Este módulo preserva o import público ``app.conversation.state`` usado pelos
testes v2 e por integrações internas sem duplicar lógica de persistência.
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.conversation_legacy.state import (  # noqa: F401
    _mem_store,
    add_message,
    apply_correction,
    apply_tool_result,
    apply_turno_updates,
    create_state,
    delete_state,
    init_state_manager,
    load_state,
    save_state,
)

logger = logging.getLogger(__name__)

INACTIVITY_RESET_HOURS = float(os.environ.get("INACTIVITY_RESET_HOURS", "1"))


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


async def maybe_reset_stale_state(phone: str, state: dict[str, Any]) -> dict[str, Any]:
    """
    Reseta o contexto quando o paciente volta depois da janela de inatividade.

    Mantém apenas dados pouco arriscados (nome) e uma fatia curta do histórico para
    observabilidade. O turno atual ainda será processado como uma conversa nova.
    """
    last_dt = _parse_datetime(state.get("last_message_at"))
    if last_dt is None:
        return state

    now = datetime.now(UTC)
    if now - last_dt <= timedelta(hours=INACTIVITY_RESET_HOURS):
        return state

    nome_preservado = (state.get("collected_data") or {}).get("nome")
    reset_state: dict[str, Any] = {
        "_tipo": "conversation",
        "phone_hash": state.get("phone_hash"),
        "phone": phone or state.get("phone", ""),
        "goal": "desconhecido",
        "status": "coletando",
        "estado": "inicio",
        "fluxo_id": "agendamento_paciente_novo",
        "collected_data": {"nome": nome_preservado} if nome_preservado else {},
        "appointment": {},
        "flags": {},
        "history": list(state.get("history") or [])[-3:],
        "last_message_at": now.isoformat(),
        "reset_reason": "inatividade",
    }
    logger.info("State expirado para %s, resetando para inicio", phone[-4:])
    return reset_state
