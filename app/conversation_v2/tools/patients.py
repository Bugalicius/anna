from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from app.conversation_v2.tools import ToolResult


def _is_ja_remarcada(consulta_atual: dict[str, Any]) -> bool:
    descricao = str(consulta_atual.get("descricao", "") or "").lower()
    return "remarc" in descricao


async def detectar_tipo_remarcacao(
    telefone: str,
    identificador: str | None = None,
) -> ToolResult:
    """
    Identifica retorno, sem agendamento confirmado ou não localizado.
    """
    from app.integrations.dietbox import (
        buscar_paciente_por_identificador,
        buscar_paciente_por_telefone,
        consultar_agendamento_ativo,
    )

    loop = asyncio.get_event_loop()

    paciente = await loop.run_in_executor(None, lambda: buscar_paciente_por_telefone(telefone))
    if not paciente and identificador:
        paciente = await loop.run_in_executor(
            None,
            lambda: buscar_paciente_por_identificador(identificador),
        )

    if not paciente:
        return ToolResult(
            sucesso=True,
            dados={
                "tipo_remarcacao": "nao_localizado",
                "consulta_atual": None,
                "ja_remarcada": None,
            },
        )

    consulta_atual = await loop.run_in_executor(
        None,
        lambda: consultar_agendamento_ativo(id_paciente=int(paciente["id"])),
    )
    if not consulta_atual:
        return ToolResult(
            sucesso=True,
            dados={
                "tipo_remarcacao": "sem_agendamento_confirmado",
                "consulta_atual": None,
                "paciente": paciente,
                "ja_remarcada": None,
            },
        )

    consulta_atual = dict(consulta_atual)
    consulta_atual["ja_remarcada"] = _is_ja_remarcada(consulta_atual)
    try:
        dt_consulta = date.fromisoformat(str(consulta_atual.get("inicio", ""))[:10])
        fim_janela = (dt_consulta + timedelta(days=90)).isoformat()
    except Exception:
        fim_janela = (date.today() + timedelta(days=90)).isoformat()

    return ToolResult(
        sucesso=True,
        dados={
            "tipo_remarcacao": "retorno",
            "consulta_atual": consulta_atual,
            "paciente": paciente,
            "ja_remarcada": consulta_atual["ja_remarcada"],
            "fim_janela": fim_janela,
        },
    )

