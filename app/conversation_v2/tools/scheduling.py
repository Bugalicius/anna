from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Literal

import requests
from pydantic import BaseModel, ConfigDict, Field

from app.conversation_v2.rules import validar_distribuicao_slots
from app.conversation_v2.tools import ToolResult

logger = logging.getLogger(__name__)


class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datetime: str
    data_fmt: str = ""
    hora: str = ""


class ConsultarSlotsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modalidade: Literal["presencial", "online"]
    preferencia: dict[str, Any] = Field(default_factory=dict)
    janela_max_dias: int = 90
    excluir_slots: list[str] = Field(default_factory=list)
    max_resultados: int = 3


class ConsultarSlotsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slots: list[Slot]
    match_exato: bool
    slots_count: int


class RemarcarDietboxInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_agenda: int
    novo_slot: Slot


class CancelarDietboxInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id_agenda: int


def _slot_from_raw(slot: dict[str, Any]) -> Slot | None:
    dt = str(slot.get("datetime", "")).strip()
    if not dt:
        return None
    data_fmt = str(slot.get("data_fmt", "")).strip()
    hora = str(slot.get("hora", "")).strip()
    if not hora:
        try:
            hora = f"{datetime.fromisoformat(dt).hour}h"
        except ValueError:
            hora = ""
    return Slot(datetime=dt, data_fmt=data_fmt, hora=hora)


async def consultar_slots(input: ConsultarSlotsInput) -> ToolResult:
    """
    Busca slots no Dietbox respeitando grade, distribuição e preferência.
    """
    from app.integrations.dietbox import consultar_slots_disponiveis
    from app.tools import scheduling as legacy_scheduling

    loop = asyncio.get_event_loop()
    try:
        pool = await loop.run_in_executor(
            None,
            lambda: consultar_slots_disponiveis(
                modalidade=input.modalidade,
                dias_a_frente=input.janela_max_dias,
            ),
        )
        selecionados, aviso_preferencia = legacy_scheduling._selecionar_slots(
            slots=pool,
            preferencia=input.preferencia,
        )
        excluidos = set(input.excluir_slots)
        selecionados = [s for s in selecionados if str(s.get("datetime", "")) not in excluidos]
        filtrados, avisos_regras = validar_distribuicao_slots(
            selecionados,
            max_resultados=input.max_resultados,
        )

        slots_model = [s for s in (_slot_from_raw(x) for x in filtrados) if s is not None]
        output = ConsultarSlotsOutput(
            slots=slots_model,
            match_exato=aviso_preferencia is None,
            slots_count=len(slots_model),
        )
        dados = output.model_dump()
        if aviso_preferencia:
            dados["aviso_preferencia"] = aviso_preferencia
        if avisos_regras:
            dados["avisos_regras"] = avisos_regras
        return ToolResult(sucesso=True, dados=dados)
    except Exception as exc:
        logger.exception("Erro ao consultar slots: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def remarcar_dietbox(id_agenda: int, novo_slot: Slot) -> ToolResult:
    """PUT no Dietbox e sinaliza ja_remarcada=true em caso de sucesso."""
    from app.integrations.dietbox import alterar_agendamento

    try:
        novo_dt = datetime.fromisoformat(novo_slot.datetime)
        loop = asyncio.get_event_loop()
        sucesso = await loop.run_in_executor(
            None,
            lambda: alterar_agendamento(
                id_agenda=str(id_agenda),
                novo_dt_inicio=novo_dt,
                observacao="Remarcado pelo Agente Ana (conversation_v2)",
            ),
        )
        if not sucesso:
            return ToolResult(sucesso=False, erro="Falha ao remarcar no Dietbox")
        return ToolResult(
            sucesso=True,
            dados={
                "id_agenda": id_agenda,
                "ja_remarcada": True,
                "novo_slot": novo_slot.model_dump(),
            },
        )
    except Exception as exc:
        logger.exception("Erro ao remarcar no Dietbox: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def cancelar_dietbox(id_agenda: int) -> ToolResult:
    """
    Cancela consulta via PUT desmarcada=true.
    Nunca usa DELETE.
    """
    from app.agents import dietbox_worker

    try:
        loop = asyncio.get_event_loop()

        def _cancelar() -> tuple[bool, str | None]:
            get_resp = requests.get(
                f"{dietbox_worker.DIETBOX_API}/agenda/{id_agenda}",
                headers=dietbox_worker._headers(),
                timeout=20,
            )
            get_resp.raise_for_status()
            current = get_resp.json().get("Data") or get_resp.json()

            def _get(*keys: str) -> Any:
                for k in keys:
                    val = current.get(k)
                    if val is not None:
                        return val
                return None

            payload = {
                "inicio": _get("inicio", "Start"),
                "fim": _get("fim", "End"),
                "timezone": _get("timezone", "Timezone") or "America/Sao_Paulo",
                "idPaciente": _get("idPaciente", "IdPaciente"),
                "idLocalAtendimento": _get("idLocalAtendimento", "IdLocalAtendimento"),
                "idServico": _get("idServico", "IdServico"),
                "tipo": _get("tipo", "Type") or 1,
                "isOnline": bool(_get("isOnline", "IsOnline") or False),
                "isVideoConference": bool(_get("isVideoConference", "IsVideoConference") or False),
                "alert": True,
                "allDay": False,
                "desmarcada": True,
                "descricao": "Cancelado pelo Agente Ana (conversation_v2)",
            }
            payload = {k: v for k, v in payload.items() if v is not None}
            put_resp = requests.put(
                f"{dietbox_worker.DIETBOX_API}/agenda/{id_agenda}",
                headers=dietbox_worker._headers(),
                json=payload,
                timeout=20,
            )
            if put_resp.status_code not in (200, 204):
                return False, f"PUT falhou status={put_resp.status_code}"
            return True, None

        sucesso, erro = await loop.run_in_executor(None, _cancelar)
        if not sucesso:
            return ToolResult(sucesso=False, erro=erro or "Falha ao cancelar")
        return ToolResult(sucesso=True, dados={"id_agenda": id_agenda, "desmarcada": True})
    except Exception as exc:
        logger.exception("Erro ao cancelar no Dietbox: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))

