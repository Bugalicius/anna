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
_EMAIL_RE = re.compile(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", re.I)
_DESCRICOES_PREF_VALIDAS = {
    "manha",
    "manhã",
    "tarde",
    "noite",
    "qualquer horário",
    "qualquer horario",
    "outras opções",
    "outras opcoes",
}
_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _normalizar_email(texto: str | None) -> str | None:
    if not texto:
        return None
    m = _EMAIL_RE.search(str(texto).strip())
    return m.group(0).lower() if m else None


def _normalizar_telefone_brasil(texto: str | None) -> str:
    digits = re.sub(r"\D", "", str(texto or ""))
    if digits.startswith("55"):
        national = digits[2:]
    else:
        national = digits
    if len(national) == 10:
        national = national[:2] + "9" + national[2:]
    return "55" + national if len(national) == 11 else digits


def _normalizar_data_nascimento(texto: str | None) -> str | None:
    if not texto:
        return None
    raw = str(texto).strip().lower()

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})\b", raw)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if ano < 100:
            ano += 2000 if ano <= datetime.now().year % 100 else 1900
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{2})(\d{2})(\d{4})\b", raw)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})\s+de\s+([a-zçã]+)\s+de\s+(\d{2,4})\b", raw)
    if m:
        dia = int(m.group(1))
        mes = _MESES_PT.get(m.group(2))
        ano = int(m.group(3))
        if ano < 100:
            ano += 2000 if ano <= datetime.now().year % 100 else 1900
        if mes:
            try:
                return date(ano, mes, dia).isoformat()
            except ValueError:
                return None

    return None


def _validar_cadastro(nome: str, telefone: str, data_nascimento: str | None, email: str | None) -> dict:
    pendentes: list[str] = []
    if len([p for p in str(nome or "").strip().split() if len(p) >= 2]) < 2:
        pendentes.append("nome")
    telefone_norm = _normalizar_telefone_brasil(telefone)
    if not telefone_norm or len(telefone_norm) < 12:
        pendentes.append("telefone")

    data_norm = _normalizar_data_nascimento(data_nascimento)
    if not data_norm:
        pendentes.append("data_nascimento")

    email_norm = _normalizar_email(email)
    if not email_norm:
        pendentes.append("email")

    return {
        "ok": not pendentes,
        "pendentes": pendentes,
        "telefone": telefone_norm,
        "data_nascimento": data_norm,
        "email": email_norm,
    }


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
    consulta_atual_inicio: str | None = None,
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
    disponiveis = _priorizar_semana_seguinte_remarcacao(disponiveis, consulta_atual_inicio)

    selecionados, aviso = _selecionar_slots(disponiveis, preferencia)
    return {
        "slots": selecionados,
        "slots_pool": todos,
        "aviso_preferencia": aviso,
        "slots_mesma_semana": _tem_slot_mesma_semana_consulta(selecionados, consulta_atual_inicio),
    }


# ── agendar ───────────────────────────────────────────────────────────────────


async def agendar(
    nome: str,
    telefone: str,
    plano: str,
    modalidade: str,
    slot: dict,
    forma_pagamento: str,
    data_nascimento: str | None = None,
    email: str | None = None,
    instagram: str | None = None,
    profissao: str | None = None,
    cep_endereco: str | None = None,
    indicacao_origem: str | None = None,
    valor_pago_sinal: float | None = None,
    pagamento_confirmado: bool = False,
) -> dict:
    """Cadastra paciente e agenda consulta no Dietbox."""
    from app.integrations.dietbox import processar_agendamento
    from app.knowledge_base import kb

    try:
        validacao = _validar_cadastro(nome, telefone, data_nascimento, email)
        if not validacao["ok"]:
            return {
                "sucesso": False,
                "erro": "cadastro_incompleto",
                "campos_pendentes": validacao["pendentes"],
            }

        dt_str = slot["datetime"]
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=BRT)

        valor_sinal = round(float(valor_pago_sinal), 2) if valor_pago_sinal else round(kb.get_valor(plano, modalidade) * 0.5, 2)
        resultado = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: processar_agendamento(
                dados_paciente={
                    "nome": nome,
                    "telefone": validacao["telefone"],
                    "email": validacao["email"] or "",
                    "data_nascimento": validacao["data_nascimento"],
                    "instagram": instagram,
                    "profissao": profissao,
                    "cep_endereco": cep_endereco,
                    "indicacao_origem": indicacao_origem,
                },
                dt_consulta=dt,
                modalidade=modalidade,
                plano=plano,
                valor_sinal=valor_sinal,
                forma_pagamento=forma_pagamento,
                pago=pagamento_confirmado,
            ),
        )

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
    descricao = str(preferencia.get("descricao") or "").strip().lower()

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
    alvo = descricao if descricao in _DESCRICOES_PREF_VALIDAS else "com essa preferência"
    aviso = (
        f"Não encontrei opções {alvo} nos próximos dias úteis.\n\n"
        "Para não te deixar sem opção, separei os 3 horários mais próximos disponíveis:"
    )
    return _diversificar(slots)[:3], aviso


def _slot_date(slot: dict) -> date | None:
    try:
        return datetime.fromisoformat(str(slot.get("datetime", ""))).date()
    except Exception:
        return None


def _consulta_date(consulta_atual_inicio: str | None) -> date | None:
    if not consulta_atual_inicio:
        return None
    try:
        return datetime.fromisoformat(str(consulta_atual_inicio)).date()
    except Exception:
        return None


def _semana_inicio(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _priorizar_semana_seguinte_remarcacao(slots: list[dict], consulta_atual_inicio: str | None) -> list[dict]:
    consulta_d = _consulta_date(consulta_atual_inicio)
    if not consulta_d:
        return slots

    inicio_semana_consulta = _semana_inicio(consulta_d)
    inicio_semana_seguinte = inicio_semana_consulta + timedelta(days=7)
    fim_semana_seguinte = inicio_semana_seguinte + timedelta(days=6)

    def bucket(slot: dict) -> tuple[int, str]:
        slot_d = _slot_date(slot)
        if not slot_d:
            return (3, str(slot.get("datetime", "")))
        if inicio_semana_seguinte <= slot_d <= fim_semana_seguinte:
            return (0, str(slot.get("datetime", "")))
        if inicio_semana_consulta <= slot_d < inicio_semana_seguinte:
            return (1, str(slot.get("datetime", "")))
        return (2, str(slot.get("datetime", "")))

    return sorted(slots, key=bucket)


def _tem_slot_mesma_semana_consulta(slots: list[dict], consulta_atual_inicio: str | None) -> bool:
    consulta_d = _consulta_date(consulta_atual_inicio)
    if not consulta_d:
        return False
    inicio_semana_consulta = _semana_inicio(consulta_d)
    inicio_semana_seguinte = inicio_semana_consulta + timedelta(days=7)
    for slot in slots:
        slot_d = _slot_date(slot)
        if slot_d and inicio_semana_consulta <= slot_d < inicio_semana_seguinte:
            return True
    return False


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
