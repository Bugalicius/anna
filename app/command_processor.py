"""
CommandProcessor — interpreta e executa comandos internos da Thaynara e do Breno.

Remetentes autorizados (env vars):
  THAYNARA_PHONE  — padrão 5531991394759
  BRENO_PHONE     — padrão 5531992059211 (alias de NUMERO_INTERNO)

Comandos reconhecidos:
  "Pergunta [nome] se pode vir às [hora] ao invés das [hora]"
  "Cancela a consulta de [nome]"
  "Qual o status de [nome]"
  "Reagenda [nome] para [data] às [hora]"

Fluxo de troca de horário:
  1. Thaynara/Breno envia o comando
  2. Ana busca o paciente e pergunta no WhatsApp do paciente
  3. Resposta do paciente é interceptada (flag Redis cmd_pending:{phone_hash})
  4. Ana notifica Thaynara/Breno e (se aceitar) remarca no Dietbox
"""
from __future__ import annotations

import json
import logging
import os
import asyncio
from datetime import timedelta, timezone

import redis.asyncio as aioredis

BRT = timezone(timedelta(hours=-3))
logger = logging.getLogger(__name__)

_CMD_TTL = 86400  # 24 h


# ── Números autorizados ───────────────────────────────────────────────────────


def _digits_only(numero: str) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isdigit())


def _sem_nono(numero: str) -> str:
    d = _digits_only(numero)
    if d.startswith("55") and len(d) == 13 and d[4] == "9":
        return d[:4] + d[5:]
    return d


def _authorized_phones() -> set[str]:
    thaynara = _digits_only(os.environ.get("THAYNARA_PHONE", "5531991394759"))
    breno = _digits_only(os.environ.get("BRENO_PHONE", os.environ.get("NUMERO_INTERNO", "5531992059211")))
    phones = set()
    for p in (thaynara, breno):
        phones.add(p)
        phones.add(_sem_nono(p))
    return phones


def is_authorized_sender(phone: str) -> bool:
    return _digits_only(phone) in _authorized_phones()


def _breno_phones() -> set[str]:
    breno = _digits_only(os.environ.get("BRENO_PHONE", os.environ.get("NUMERO_INTERNO", "5531992059211")))
    return {breno, _sem_nono(breno)}


def _is_breno_sender(phone: str) -> bool:
    return _digits_only(phone) in _breno_phones()


def _thaynara_phone() -> str:
    return _digits_only(os.environ.get("THAYNARA_PHONE", "5531991394759"))


# ── Parse do comando via LLM ──────────────────────────────────────────────────


_PARSE_SYSTEM = """Você recebe uma mensagem de texto e deve identificar o comando e extrair as informações.
Responda SOMENTE JSON válido com os campos:
{
  "tipo": "pergunta_troca_horario" | "cancela_consulta" | "status_paciente" | "reagenda" | "desconhecido",
  "nome": string | null,
  "hora_atual": string | null,
  "nova_hora": string | null,
  "data": string | null,
  "hora": string | null
}
Exemplos:
- "Pergunta Maria se pode vir às 10h ao invés das 15h" → {"tipo":"pergunta_troca_horario","nome":"Maria","hora_atual":"15h","nova_hora":"10h","data":null,"hora":null}
- "Cancela a consulta de João" → {"tipo":"cancela_consulta","nome":"João","hora_atual":null,"nova_hora":null,"data":null,"hora":null}
- "Qual o status de Ana Souza" → {"tipo":"status_paciente","nome":"Ana Souza","hora_atual":null,"nova_hora":null,"data":null,"hora":null}
- "Reagenda Carlos para terça às 14h" → {"tipo":"reagenda","nome":"Carlos","hora_atual":null,"nova_hora":null,"data":"terça","hora":"14h"}"""


async def _parse_command(text: str) -> dict:
    from app import llm_client
    try:
        raw = await llm_client.complete_text_async(system=_PARSE_SYSTEM, user=text, max_tokens=200)
        raw = llm_client.strip_json_fences(raw)
        return json.loads(raw)
    except Exception as e:
        logger.warning("Falha ao parsear comando '%s': %s", text[:80], e)
        return {"tipo": "desconhecido"}


# ── Busca de paciente no banco ────────────────────────────────────────────────


def _find_patient_by_name(nome: str) -> dict | None:
    """Retorna {phone_e164, phone_hash, nome} do primeiro contato cujo nome contenha `nome`."""
    from app.database import SessionLocal
    from app.models import Contact
    from sqlalchemy import or_

    if not nome:
        return None
    try:
        with SessionLocal() as db:
            contact = (
                db.query(Contact)
                .filter(
                    or_(
                        Contact.collected_name.ilike(f"%{nome}%"),
                        Contact.first_name.ilike(f"%{nome}%"),
                        Contact.push_name.ilike(f"%{nome}%"),
                    )
                )
                .first()
            )
            if not contact:
                return None
            return {
                "phone_e164": contact.phone_e164 or "",
                "phone_hash": contact.phone_hash or "",
                "nome": contact.collected_name or contact.first_name or contact.push_name or nome,
                "stage": contact.stage or "",
            }
    except Exception as e:
        logger.error("Erro ao buscar paciente '%s': %s", nome, e)
        return None


# ── Redis — flag de resposta pendente ────────────────────────────────────────


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def _set_cmd_pending(phone_hash: str, ctx: dict) -> None:
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        await r.set(f"cmd_pending:{phone_hash}", json.dumps(ctx, ensure_ascii=False), ex=_CMD_TTL)
        await r.aclose()
    except Exception as e:
        logger.warning("cmd_pending set falhou: %s", e)


async def _get_cmd_pending(phone_hash: str) -> dict | None:
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        raw = await r.get(f"cmd_pending:{phone_hash}")
        await r.aclose()
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning("cmd_pending get falhou: %s", e)
        return None


async def _del_cmd_pending(phone_hash: str) -> None:
    try:
        r = aioredis.Redis.from_url(_redis_url(), decode_responses=True)
        await r.delete(f"cmd_pending:{phone_hash}")
        await r.aclose()
    except Exception:
        pass


async def is_command_response_pending(phone_hash: str) -> bool:
    return bool(await _get_cmd_pending(phone_hash))


# ── Resposta afirmativa/negativa do paciente ──────────────────────────────────


_AFIRMATIVAS = {"sim", "pode", "consigo", "consegue", "ok", "tudo bem", "claro", "combinado", "perfeito", "ótimo", "otimo", "tá", "ta", "yes", "confirmo", "confirmado"}


def _is_affirmative(text: str) -> bool:
    t = text.strip().lower()
    return any(a in t for a in _AFIRMATIVAS)


# ── Handlers dos comandos ─────────────────────────────────────────────────────


async def _cmd_pergunta_troca(parsed: dict, phone_solicitante: str, meta_client) -> str:
    nome = parsed.get("nome") or ""
    hora_atual = parsed.get("hora_atual") or "?"
    nova_hora = parsed.get("nova_hora") or "?"

    paciente = _find_patient_by_name(nome)
    if not paciente or not paciente["phone_e164"]:
        return f"Não encontrei '{nome}' no banco. Pode confirmar o nome completo?"

    primeiro_nome = (paciente["nome"] or nome).split()[0]
    msg_paciente = (
        f"Oi {primeiro_nome}! 💚 A Thaynara perguntou se você conseguiria trocar "
        f"sua consulta de {hora_atual} para às {nova_hora}. Consegue?"
    )
    await meta_client.send_text(paciente["phone_e164"], msg_paciente)

    ctx = {
        "tipo": "pergunta_troca_horario",
        "nome": paciente["nome"],
        "phone_paciente": paciente["phone_e164"],
        "phone_solicitante": phone_solicitante,
        "hora_atual": hora_atual,
        "nova_hora": nova_hora,
    }
    await _set_cmd_pending(paciente["phone_hash"], ctx)
    return f"Perguntei pra {primeiro_nome} sobre a troca. Vou te avisar quando responder 💚"


async def _cmd_cancela(parsed: dict, phone_solicitante: str, meta_client) -> str:
    nome = parsed.get("nome") or ""
    paciente = _find_patient_by_name(nome)
    if not paciente or not paciente["phone_e164"]:
        return f"Não encontrei '{nome}' no banco. Pode confirmar o nome completo?"

    loop = asyncio.get_event_loop()
    try:
        from app.integrations.dietbox import cancelar_agendamento
        resultado = await loop.run_in_executor(
            None, lambda: cancelar_agendamento(telefone=paciente["phone_e164"])
        )
        if resultado and resultado.get("sucesso"):
            return f"Consulta de {paciente['nome']} cancelada com sucesso ✅"
        return f"Não consegui cancelar no Dietbox: {resultado}"
    except Exception as e:
        logger.error("Erro ao cancelar consulta de %s: %s", nome, e)
        return f"Erro ao cancelar: {e}"


async def _cmd_status(parsed: dict, phone_solicitante: str, meta_client) -> str:
    from app.database import SessionLocal
    from app.models import Contact

    nome = parsed.get("nome") or ""
    paciente = _find_patient_by_name(nome)
    if not paciente:
        return f"Não encontrei '{nome}' no banco."

    stage = paciente.get("stage", "desconhecido")

    try:
        from app.conversation.state import load_state
        state = await load_state(paciente["phone_hash"])
        status_engine = state.get("status", "sem conversa ativa")
        goal = state.get("goal", "")
        appt = state.get("appointment", {})
        resumo = (
            f"*{paciente['nome']}*\n"
            f"Stage: {stage}\n"
            f"Status engine: {status_engine}\n"
            f"Goal: {goal or '—'}\n"
            f"Agendamento: {appt.get('data_hora') or '—'}"
        )
    except Exception:
        resumo = f"*{paciente['nome']}*\nStage: {stage}"

    return resumo


async def _cmd_reagenda(parsed: dict, phone_solicitante: str, meta_client) -> str:
    nome = parsed.get("nome") or ""
    data = parsed.get("data") or ""
    hora = parsed.get("hora") or ""

    paciente = _find_patient_by_name(nome)
    if not paciente or not paciente["phone_e164"]:
        return f"Não encontrei '{nome}' no banco. Pode confirmar o nome completo?"

    loop = asyncio.get_event_loop()
    try:
        from app.integrations.dietbox import alterar_agendamento, consultar_agendamento_ativo, buscar_paciente_por_telefone
        p_dietbox = await loop.run_in_executor(
            None, lambda: buscar_paciente_por_telefone(paciente["phone_e164"])
        )
        if not p_dietbox:
            return f"Paciente {nome} não encontrado no Dietbox."

        agenda_atual = await loop.run_in_executor(
            None, lambda: consultar_agendamento_ativo(id_paciente=int(p_dietbox["id"]))
        )
        if not agenda_atual:
            return f"{nome} não tem agendamento ativo no Dietbox."

        resultado = await loop.run_in_executor(
            None,
            lambda: alterar_agendamento(
                id_agenda=agenda_atual["id"],
                nova_data=data,
                novo_horario=hora,
            ),
        )
        if resultado and resultado.get("sucesso"):
            return f"Consulta de {nome} reagendada para {data} às {hora} ✅"
        return f"Não consegui reagendar no Dietbox: {resultado}"
    except Exception as e:
        logger.error("Erro ao reagendar %s: %s", nome, e)
        return f"Erro ao reagendar: {e}"


# ── Entrada principal ─────────────────────────────────────────────────────────


async def process_command(phone: str, text: str, meta_client) -> bool:
    """
    Tenta parsear e executar um comando.
    Retorna True se o comando foi reconhecido e tratado.
    Retorna False se não reconhecido (caller pode fazer fallback).
    """
    parsed = await _parse_command(text)
    tipo = parsed.get("tipo", "desconhecido")

    if tipo == "desconhecido":
        if _is_breno_sender(phone):
            return False
        await meta_client.send_text(phone, "Não entendi o comando 😅 Pode reformular?")
        return True  # tratado — resposta de erro

    handler_map = {
        "pergunta_troca_horario": _cmd_pergunta_troca,
        "cancela_consulta": _cmd_cancela,
        "status_paciente": _cmd_status,
        "reagenda": _cmd_reagenda,
    }
    handler = handler_map.get(tipo)
    if not handler:
        return False

    try:
        resposta = await handler(parsed, phone, meta_client)
        if resposta:
            await meta_client.send_text(phone, resposta)
    except Exception as e:
        logger.error("Erro no handler de comando '%s': %s", tipo, e)
        await meta_client.send_text(phone, f"Erro ao executar comando: {e}")

    return True


async def handle_patient_command_response(phone_hash: str, phone: str, text: str, meta_client) -> None:
    """
    Chamado quando um paciente responde a uma pergunta de comando pendente.
    Notifica Thaynara/Breno e, se aceitar, tenta reagendar no Dietbox.
    """
    ctx = await _get_cmd_pending(phone_hash)
    if not ctx:
        return

    await _del_cmd_pending(phone_hash)

    tipo = ctx.get("tipo")
    nome = ctx.get("nome", "Paciente")
    phone_solicitante = ctx.get("phone_solicitante", "")
    primeiro_nome = nome.split()[0]

    if tipo == "pergunta_troca_horario":
        hora_atual = ctx.get("hora_atual", "?")
        nova_hora = ctx.get("nova_hora", "?")

        if _is_affirmative(text):
            msg_solicitante = f"✅ {nome} confirmou — consulta alterada para às {nova_hora}."
            msg_paciente = f"Ótimo {primeiro_nome}! 💚 A Thaynara vai confirmar as novas informações da consulta."
            # Tenta remarcar no Dietbox com best-effort
            try:
                loop = asyncio.get_event_loop()
                from app.integrations.dietbox import (
                    buscar_paciente_por_telefone,
                    consultar_agendamento_ativo,
                    alterar_agendamento,
                )
                p_dietbox = await loop.run_in_executor(
                    None, lambda: buscar_paciente_por_telefone(phone)
                )
                if p_dietbox:
                    agenda = await loop.run_in_executor(
                        None, lambda: consultar_agendamento_ativo(id_paciente=int(p_dietbox["id"]))
                    )
                    if agenda:
                        await loop.run_in_executor(
                            None,
                            lambda: alterar_agendamento(
                                id_agenda=agenda["id"],
                                nova_data=None,
                                novo_horario=nova_hora,
                            ),
                        )
            except Exception as e:
                logger.warning("Remarcar automático falhou (troca horário): %s", e)
        else:
            msg_solicitante = f"❌ {nome} não consegue trocar para às {nova_hora}."
            msg_paciente = f"Tudo bem {primeiro_nome}! 💚 Sua consulta permanece no horário atual."

        await meta_client.send_text(phone, msg_paciente)
        if phone_solicitante:
            await meta_client.send_text(phone_solicitante, msg_solicitante)
