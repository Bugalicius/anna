"""
Interpreter — interpreta o turno do usuário com Claude Haiku.

Função pública:
  interpretar_turno(message, state) -> dict

Retorna um 'turno' com todos os dados extraídos da mensagem.
Não decide o que fazer — isso é papel do Planner.
"""
from __future__ import annotations

import json
import logging
import os

import anthropic

from app.pii_sanitizer import sanitize_historico

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT = """\
Você interpreta mensagens de pacientes num sistema de agendamento nutricional \
(nutricionista Thaynara Teixeira).

## Contexto da conversa
Goal atual: {goal}
Status: {status}
Dados coletados: {collected_summary}
Slots oferecidos: {slots_summary}
Última mensagem da Ana: {last_assistant}

## Histórico recente
{history}

## Mensagem atual do paciente
{message}

## Instruções
Retorne SOMENTE JSON válido sem markdown. Não invente dados — use null se não houver evidência.

Planos válidos: premium, ouro, com_retorno, unica, formulario
Modalidades: presencial, online
Formas de pagamento: pix, cartao
Dias da semana (int): 0=segunda … 4=sexta

{{"intent":"agendar|remarcar|cancelar|tirar_duvida|duvida_clinica|confirmar_pagamento|recusou_remarketing|fora_de_contexto","nome":string|null,"status_paciente":"novo"|"retorno"|null,"objetivo":string|null,"plano":string|null,"modalidade":string|null,"forma_pagamento":string|null,"escolha_slot":1|2|3|null,"aceita_upgrade":true|false|null,"confirmou_pagamento":true|false,"correcao":{{"campo":"plano"|"modalidade"|"forma_pagamento"|"preferencia_horario","valor_novo":string}}|null,"tem_pergunta":true|false,"topico_pergunta":"pagamento"|"planos"|"modalidade"|"politica"|"clinica"|null,"preferencia_horario":{{"tipo":"turno"|"hora_especifica"|"dia_semana"|"proximidade"|"qualquer","turno":"manha"|"tarde"|"noite"|null,"hora":string|null,"dia_semana":int|null,"descricao":string}}|null}}

Regras críticas:
- "correcao" APENAS quando paciente contradiz algo já dito (ex: "na verdade prefiro tarde")
- "confirmou_pagamento": true se disse "paguei", "enviei comprovante", ou enviou imagem
- "escolha_slot": 1/2/3 somente quando há slots listados e paciente escolhe por número/posição
- "aceita_upgrade": true/false SOMENTE quando houve oferta de upgrade explícita no histórico recente
- Se houve oferta de upgrade (Ana perguntou "Quer manter X ou prefere Y?") e paciente rejeita (ex: "quero X mesmo", "pode deixar", "não quero"), use intent="agendar" e aceita_upgrade=false. NUNCA use recusou_remarketing nesse caso.
- "recusou_remarketing" APENAS quando a Ana enviou mensagem de recontato automático após dias de silêncio e o paciente não quer mais ser contactado. Durante fluxo ativo de agendamento, NUNCA use recusou_remarketing.
- "duvida_clinica" APENAS para perguntas médicas explícitas sobre sintomas, diagnóstico, medicamentos ou condições de saúde (ex: "posso comer X tendo diabetes", "tenho refluxo, pode?"). Paciente falando sobre objetivos, razões para escolher um plano, ou o que espera da consulta → intent="agendar", tem_pergunta=false.
- Quando o paciente está no meio do agendamento (goal=agendar_consulta) e diz algo que explica sua motivação ou objetivo, mantenha intent="agendar" e siga o fluxo.
"""

# ── Valores aceitos ────────────────────────────────────────────────────────────

_INTENTS = {
    "agendar", "remarcar", "cancelar", "tirar_duvida",
    "duvida_clinica", "confirmar_pagamento", "recusou_remarketing", "fora_de_contexto",
}
_PLANOS = {"premium", "ouro", "com_retorno", "unica", "formulario"}
_MODALIDADES = {"presencial", "online"}
_FORMAS_PAG = {"pix", "cartao"}
_TOPICOS = {"pagamento", "planos", "modalidade", "politica", "clinica"}
_TURNOS = {"manha", "tarde", "noite"}
_TIPOS_PREF = {"turno", "hora_especifica", "dia_semana", "proximidade", "qualquer"}


# ── Função pública ─────────────────────────────────────────────────────────────


async def interpretar_turno(message: str, state: dict) -> dict:
    """
    Interpreta a mensagem atual do paciente com Claude Haiku.

    Usa o estado atual como contexto para dar ao LLM informação sobre
    o que já foi coletado, quais slots foram oferecidos, etc.

    Retorna um dict 'turno' com todos os campos extraídos.
    """
    cd = state["collected_data"]
    collected_summary = (
        f"nome={cd['nome'] or '?'}, plano={cd['plano'] or '?'}, "
        f"modalidade={cd['modalidade'] or '?'}, pagamento={cd['forma_pagamento'] or '?'}"
    )
    slots = state.get("last_slots_offered", [])
    slots_summary = (
        ", ".join(
            f"{i+1}. {s.get('data_fmt','?')} às {s.get('hora','?')}"
            for i, s in enumerate(slots)
        )
        or "nenhum"
    )
    last_assistant = next(
        (m["content"] for m in reversed(state.get("history", [])) if m["role"] == "assistant"),
        "(sem resposta anterior)",
    )
    history_clean = sanitize_historico(state.get("history", [])[-8:])
    history_txt = "\n".join(
        f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content'][:250]}"
        for m in history_clean
    ) or "(sem histórico)"

    prompt = _PROMPT.format(
        goal=state.get("goal", "desconhecido"),
        status=state.get("status", "coletando"),
        collected_summary=collected_summary,
        slots_summary=slots_summary,
        last_assistant=last_assistant[:400],
        history=history_txt,
        message=message,
    )

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=450,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return _parse_turno(data)

    except Exception as e:
        logger.error("Erro ao interpretar turno: %s", e)
        return _fallback(message)


# ── Parsing ───────────────────────────────────────────────────────────────────


def _parse_turno(data: dict) -> dict:
    intent = data.get("intent", "fora_de_contexto")
    if intent not in _INTENTS:
        intent = "fora_de_contexto"

    escolha = data.get("escolha_slot")
    escolha_int = int(escolha) if escolha in (1, 2, 3) else None

    aceita = data.get("aceita_upgrade")
    aceita_bool = bool(aceita) if aceita is not None else None

    correcao = None
    raw_c = data.get("correcao")
    if isinstance(raw_c, dict) and raw_c.get("campo") and raw_c.get("valor_novo") is not None:
        correcao = {"campo": str(raw_c["campo"]), "valor_novo": raw_c["valor_novo"]}

    preferencia = None
    raw_p = data.get("preferencia_horario")
    if isinstance(raw_p, dict) and raw_p.get("tipo"):
        tipo = raw_p.get("tipo", "qualquer")
        if tipo not in _TIPOS_PREF:
            tipo = "qualquer"
        dia = raw_p.get("dia_semana")
        preferencia = {
            "tipo": tipo,
            "turno": raw_p.get("turno") if raw_p.get("turno") in _TURNOS else None,
            "hora": str(raw_p["hora"]) if raw_p.get("hora") else None,
            "dia_semana": int(dia) if dia is not None and 0 <= int(dia) <= 4 else None,
            "descricao": str(raw_p.get("descricao", "")),
        }

    return {
        "intent": intent,
        "nome": _str_or_none(data.get("nome")),
        "status_paciente": _one_of(data.get("status_paciente"), ("novo", "retorno")),
        "objetivo": _str_or_none(data.get("objetivo")),
        "plano": _one_of(data.get("plano"), _PLANOS),
        "modalidade": _one_of(data.get("modalidade"), _MODALIDADES),
        "forma_pagamento": _one_of(data.get("forma_pagamento"), _FORMAS_PAG),
        "escolha_slot": escolha_int,
        "aceita_upgrade": aceita_bool,
        "confirmou_pagamento": bool(data.get("confirmou_pagamento", False)),
        "correcao": correcao,
        "tem_pergunta": bool(data.get("tem_pergunta", False)),
        "topico_pergunta": _one_of(data.get("topico_pergunta"), _TOPICOS),
        "preferencia_horario": preferencia,
    }


def _str_or_none(v) -> str | None:
    if v is None or v == "":
        return None
    s = str(v).strip()
    return s or None


def _one_of(v, valid) -> str | None:
    if v is None:
        return None
    s = str(v).lower().strip()
    return s if s in valid else None


def _fallback(text: str) -> dict:
    """Interpretação heurística mínima quando o LLM falha."""
    t = text.lower()
    intent = "fora_de_contexto"
    if any(w in t for w in ["remarcar", "mudar horário", "reagendar"]):
        intent = "remarcar"
    elif any(w in t for w in ["cancelar", "desmarcar"]):
        intent = "cancelar"
    elif any(w in t for w in ["paguei", "pago", "comprovante", "enviei"]):
        intent = "confirmar_pagamento"
    elif any(w in t for w in ["agendar", "consulta", "marcar"]):
        intent = "agendar"

    return {
        "intent": intent,
        "nome": None,
        "status_paciente": None,
        "objetivo": None,
        "plano": None,
        "modalidade": None,
        "forma_pagamento": "pix" if "pix" in t else ("cartao" if "cartão" in t or "cartao" in t else None),
        "escolha_slot": None,
        "aceita_upgrade": None,
        "confirmou_pagamento": intent == "confirmar_pagamento",
        "correcao": None,
        "tem_pergunta": "?" in text,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }
