"""Tools de pacientes — detecta tipo de remarcação e busca dados no Dietbox."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


async def detectar_tipo_remarcacao(telefone: str, identificador: str | None = None) -> dict:
    """
    Determina se o paciente tem agendamento com pagamento confirmado (retorno)
    ou não (nova consulta), e retorna os dados do agendamento encontrado.
    """
    from app.integrations.dietbox import (
        buscar_paciente_por_telefone,
        buscar_paciente_por_identificador,
        consultar_agendamento_ativo,
        verificar_lancamento_financeiro,
    )

    loop = asyncio.get_event_loop()

    paciente = await loop.run_in_executor(
        None, lambda: buscar_paciente_por_telefone(telefone)
    )
    if not paciente and identificador:
        paciente = await loop.run_in_executor(
            None, lambda: buscar_paciente_por_identificador(identificador)
        )
    if not paciente:
        return {
            "tipo_remarcacao": "nao_localizado",
            "consulta_atual": None,
            "precisa_identificacao": True,
            "identificador_usado": identificador,
        }

    agenda = await loop.run_in_executor(
        None, lambda: consultar_agendamento_ativo(id_paciente=int(paciente["id"]))
    )
    if not agenda:
        return {
            "tipo_remarcacao": "sem_agendamento_confirmado",
            "consulta_atual": None,
            "paciente": paciente,
            "precisa_identificacao": True,
            "identificador_usado": identificador,
        }

    tem_lancamento = await loop.run_in_executor(
        None, lambda: verificar_lancamento_financeiro(id_agenda=agenda["id"])
    )
    if not tem_lancamento:
        return {
            "tipo_remarcacao": "sem_agendamento_confirmado",
            "consulta_atual": None,
            "paciente": paciente,
            "precisa_identificacao": True,
            "identificador_usado": identificador,
        }

    # Calcula janela de remarcação como retorno: até 90 dias da consulta original.
    try:
        dt_consulta = date.fromisoformat(agenda["inicio"][:10])
        fim_janela = (dt_consulta + timedelta(days=90)).isoformat()
    except Exception as e:
        logger.error("Erro ao calcular fim_janela: %s", e)
        fim_janela = (date.today() + timedelta(days=90)).isoformat()

    if date.today().isoformat() > fim_janela:
        return {
            "tipo": "perda_retorno",
            "tipo_remarcacao": "perda_retorno",
            "consulta_atual": agenda,
            "fim_janela": fim_janela,
            "paciente": paciente,
        }

    return {
        "tipo_remarcacao": "retorno",
        "consulta_atual": agenda,
        "fim_janela": fim_janela,
    }
