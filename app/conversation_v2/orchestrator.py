"""
Orchestrator — coordena o pipeline completo de um turno conversacional.

Pipeline (implementado a partir da Fase 3):
    1. Carregar contexto (estado Redis + histórico + config YAML)
    2. Interpreter (Gemini) → Interpretacao
    3. Normalizar entidades
    4. State Machine → AcaoAutorizada
    5. Rule Engine valida ação
    6. Tools (se necessário)
    7. Response Writer → list[Mensagem]
    8. Output Validator
    9. Persistir estado + métricas

Referência de logging estruturado (logs/metrics.jsonl):
    {
        "timestamp": "...",
        "phone_hash": "...",
        "fluxo": "agendamento_paciente_novo",
        "estado_antes": "aguardando_nome",
        "estado_depois": "aguardando_status_paciente",
        "intent": "informar_nome",
        "regra_aplicada": "R12_validar_nome_nao_generico",
        "tools_chamadas": [],
        "duracao_ms": 123,
        "erro": null
    }
"""
from __future__ import annotations

import logging
from typing import Any

from app.conversation_v2.models import ResultadoTurno

logger = logging.getLogger(__name__)


async def processar_turno(
    phone: str,
    mensagem: dict[str, Any],
) -> ResultadoTurno:
    """
    Pipeline completo de processamento de um turno.

    Args:
        phone: número do remetente (formato: '5531999999999')
        mensagem: payload da mensagem (text, type, media, etc.)

    Returns:
        ResultadoTurno com status, mensagens enviadas e novo estado.

    Raises:
        NotImplementedError: até Fase 3 ser implementada.
    """
    raise NotImplementedError(
        "processar_turno() será implementado a partir da Fase 3. "
        "O sistema atual usa app/conversation/engine.py."
    )
