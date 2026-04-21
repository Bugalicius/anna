"""
Tools de agendamento — wrappers async sobre os workers do Dietbox.

Funções públicas:
  consultar_slots(modalidade, preferencia) -> dict
  consultar_slots_remarcar(modalidade, preferencia, fim_janela, excluir, pool) -> dict
  agendar(nome, telefone, plano, modalidade, slot, forma_pagamento) -> dict
  remarcar(id_agenda_original, novo_slot, consulta_atual) -> dict
  cancelar(telefone, motivo) -> dict
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

_HORAS_MANHA = {"8h", "9h", "10h"}
_HORAS_TARDE = {"15h", "16h", "17h"}
_HORAS_NOITE = {"18h", "19h"}


# ── consultar_slots ───────────────────────────────────────────────────────────


async def consultar_slots(modalidade: str, preferencia: dict | None) -> dict:
    """Consulta slots disponíveis no Dietbox e filtra/ordena por preferência."""
    from app.integrations.dietbox import consultar_slots_disponiveis

    hoje_iso = date.today().isoformat()
    try:
        todos = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: consultar_slots_disponiveis(modalidade=modalidade, dias_a_frente=14),
        )
    except Exception as e:
        logger.error("Erro ao consultar slots: %s", e)
        return {"slots": [], "slots_pool": []}

    # Nunca oferecer slots do dia atual
    todos = [s for s in todos if not s.get("datetime", "").startswith(hoje_iso)]

    if not todos:
        return {"slots": [], "slots_pool": []}

    selecionados, aviso = _selecionar_slots(todos, preferencia)
    return {
        "slots": selecionados,
        "slots_pool": todos,
        "aviso_preferencia": aviso,
    }


async def consultar_slots_remarcar(
    modalidade: str,
    preferencia: dict | None,
    fim_janela: str | None,
    excluir: list[str] | None = None,
    pool: list[dict] | None = None,
) -> dict:
    """Consulta slots para remarcação dentro da janela de prazo."""
    from app.integrations.dietbox import consultar_slots_disponiveis

    hoje = date.today()
    data_inicio = hoje + timedelta(days=1)
    if fim_janela:
        try:
            data_fim = date.fromisoformat(fim_janela)
        except ValueError:
            data_fim = hoje + timedelta(days=7)
    else:
        data_fim = hoje + timedelta(days=7)

    dias_a_frente = max(1, (data_fim - hoje).days)

    if pool is not None:
        todos = pool
    else:
        try:
            todos = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: consultar_slots_disponiveis(
                    modalidade=modalidade,
                    dias_a_frente=dias_a_frente,
                    data_inicio=data_inicio,
                ),
            )
        except Exception as e:
            logger.error("Erro slots remarcar: %s", e)
            return {"slots": [], "slots_pool": []}

    # Remove slots já oferecidos
    excluir_set = set(excluir or [])
    disponiveis = [s for s in todos if s.get("datetime") not in excluir_set]

    selecionados, aviso = _selecionar_slots(disponiveis, preferencia)
    return {
        "slots": selecionados,
        "slots_pool": todos,
        "aviso_preferencia": aviso,
    }


# ── agendar ───────────────────────────────────────────────────────────────────


async def agendar(
    nome: str,
    telefone: str,
    plano: str,
    modalidade: str,
    slot: dict,
    forma_pagamento: str,
) -> dict:
    """Cadastra paciente e agenda consulta no Dietbox."""
    from app.integrations.dietbox import processar_agendamento, confirmar_pagamento
    from app.knowledge_base import kb

    try:
        dt_str = slot["datetime"]
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)

        valor_sinal = round(kb.get_valor(plano, modalidade) * 0.5, 2)
        resultado = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: processar_agendamento(
                dados_paciente={"nome": nome, "telefone": telefone, "email": ""},
                dt_consulta=dt,
                modalidade=modalidade,
                plano=plano,
                valor_sinal=valor_sinal,
                forma_pagamento=forma_pagamento,
            ),
        )

        if resultado.get("sucesso") and resultado.get("id_transacao"):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: confirmar_pagamento(resultado["id_transacao"])
                )
            except Exception as exc:
                logger.warning("Falha ao confirmar pagamento Dietbox: %s", exc)

        return resultado

    except Exception as e:
        logger.error("Erro ao agendar: %s", e)
        return {"sucesso": False, "erro": str(e)}


# ── remarcar ──────────────────────────────────────────────────────────────────


async def remarcar(
    id_agenda_original: str,
    novo_slot: dict,
    consulta_atual: dict | None = None,
) -> dict:
    """Altera agendamento existente no Dietbox."""
    from app.integrations.dietbox import alterar_agendamento

    try:
        novo_dt = datetime.fromisoformat(novo_slot["datetime"])
        data_orig = ""
        if consulta_atual:
            try:
                dt_orig = datetime.fromisoformat(consulta_atual.get("inicio", ""))
                data_orig = dt_orig.strftime("%d/%m/%Y")
            except Exception:
                pass
        data_nova = novo_dt.strftime("%d/%m/%Y")
        obs = (
            f"Remarcado do dia {data_orig} para {data_nova}"
            if data_orig else f"Remarcado para {data_nova}"
        )
        sucesso = await asyncio.get_event_loop().run_in_executor(
            None, lambda: alterar_agendamento(id_agenda_original, novo_dt, obs)
        )
        return {"sucesso": bool(sucesso)}
    except Exception as e:
        logger.error("Erro ao remarcar: %s", e)
        return {"sucesso": False, "erro": str(e)}


# ── cancelar ─────────────────────────────────────────────────────────────────


async def cancelar(telefone: str, motivo: str) -> dict:
    """Cancela agendamento ativo no Dietbox."""
    from app.integrations.dietbox import (
        buscar_paciente_por_telefone,
        consultar_agendamento_ativo,
        cancelar_agendamento,
    )

    try:
        paciente = await asyncio.get_event_loop().run_in_executor(
            None, lambda: buscar_paciente_por_telefone(telefone)
        )
        if not paciente:
            return {"sucesso": False, "erro": "Paciente não encontrado"}

        agenda = await asyncio.get_event_loop().run_in_executor(
            None, lambda: consultar_agendamento_ativo(id_paciente=int(paciente["id"]))
        )
        if not agenda:
            return {"sucesso": False, "erro": "Sem agendamento ativo"}

        obs = f"Cancelado pelo paciente. Motivo: {motivo}"
        sucesso = await asyncio.get_event_loop().run_in_executor(
            None, lambda: cancelar_agendamento(agenda["id"], observacao=obs)
        )
        return {"sucesso": bool(sucesso)}
    except Exception as e:
        logger.error("Erro ao cancelar: %s", e)
        return {"sucesso": False, "erro": str(e)}


# ── Seleção de slots ───────────────────────────────────────────────────────────


def _selecionar_slots(
    slots: list[dict],
    preferencia: dict | None,
) -> tuple[list[dict], str | None]:
    """
    Seleciona até 3 slots com base na preferência do paciente.
    Prioriza diversificação de dias.
    Retorna (slots_selecionados, aviso_preferencia).
    """
    if not slots:
        return [], None

    if not preferencia or preferencia.get("tipo") in ("proximidade", "qualquer", None):
        return _diversificar(slots)[:3], None

    tipo = preferencia.get("tipo")
    turno = preferencia.get("turno")
    hora = preferencia.get("hora")
    dia_pref = preferencia.get("dia_semana")
    descricao = preferencia.get("descricao", "")

    horas_alvo: set[str] | None = None
    if tipo == "turno" and turno:
        horas_alvo = {"manha": _HORAS_MANHA, "tarde": _HORAS_TARDE, "noite": _HORAS_NOITE}.get(turno)
    elif tipo == "hora_especifica" and hora:
        h = re.sub(r"[^0-9]", "", hora)
        horas_alvo = {f"{int(h)}h"} if h else None

    def _match(s: dict) -> bool:
        dia_ok = dia_pref is None or datetime.fromisoformat(s["datetime"]).weekday() == dia_pref
        hora_ok = not horas_alvo or s.get("hora") in horas_alvo
        return dia_ok and hora_ok

    matches = [s for s in slots if _match(s)]
    if matches:
        return _diversificar(matches)[:3], None

    # Preferência não encontrada — aviso e fallback
    aviso = (
        f"Não encontrei opções {descricao} nos próximos dias úteis.\n\n"
        "Para não te deixar sem opção, separei os 3 horários mais próximos disponíveis:"
    )
    return _diversificar(slots)[:3], aviso


def _diversificar(slots: list[dict]) -> list[dict]:
    """Seleciona slots priorizando dias diferentes."""
    vistos: set[str] = set()
    resultado: list[dict] = []
    for s in slots:
        dia = s.get("datetime", "")[:10]
        if dia not in vistos:
            resultado.append(s)
            vistos.add(dia)
        if len(resultado) >= 3:
            break
    # Completa com slots do mesmo dia se necessário
    if len(resultado) < 3:
        for s in slots:
            if s not in resultado:
                resultado.append(s)
            if len(resultado) >= 3:
                break
    return resultado
