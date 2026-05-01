"""Tool de escalação — encaminha para a nutricionista."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def escalar(meta_client, telefone: str, nome: str | None, historico: list[dict]) -> None:
    """Escala dúvida clínica para o número interno da nutricionista."""
    from app.escalation import escalar_para_humano

    resumo = "\n".join(
        f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content'][:120]}"
        for m in historico[-6:]
    )
    await escalar_para_humano(
        meta_client=meta_client,
        telefone_paciente=telefone,
        nome_paciente=nome,
        historico_resumido=resumo,
        motivo="Dúvida clínica — requer nutricionista",
    )
