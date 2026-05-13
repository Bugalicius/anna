"""Compatibilidade para o estado usado pelo orchestrator v2.

O cutover manteve a implementação persistente em ``app.conversation_legacy.state``.
Este módulo preserva o import público ``app.conversation.state`` usado pelos
testes v2 e por integrações internas sem duplicar lógica de persistência.
"""
from __future__ import annotations

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

