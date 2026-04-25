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
import re
from datetime import datetime

import anthropic

from app.pii_sanitizer import sanitize_historico

logger = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
Você interpreta mensagens de pacientes num sistema de agendamento nutricional \
(nutricionista Thaynara Teixeira).

## Instruções
Retorne SOMENTE JSON válido sem markdown. Não invente dados — use null se não houver evidência.

Planos válidos: premium, ouro, com_retorno, unica, formulario
Modalidades: presencial, online
Formas de pagamento: pix, cartao
Dias da semana (int): 0=segunda … 4=sexta

{{"intent":"agendar|remarcar|cancelar|tirar_duvida|duvida_clinica|confirmar_pagamento|recusou_remarketing|fora_de_contexto","nome":string|null,"status_paciente":"novo"|"retorno"|null,"objetivo":string|null,"plano":string|null,"modalidade":string|null,"forma_pagamento":string|null,"escolha_slot":1|2|3|null,"aceita_upgrade":true|false|null,"confirmou_pagamento":true|false,"valor_comprovante":number|null,"data_nascimento":string|null,"email":string|null,"instagram":string|null,"profissao":string|null,"cep_endereco":string|null,"indicacao_origem":string|null,"correcao":{{"campo":"plano"|"modalidade"|"forma_pagamento"|"preferencia_horario","valor_novo":string}}|null,"tem_pergunta":true|false,"topico_pergunta":"pagamento"|"planos"|"modalidade"|"politica"|"clinica"|null,"preferencia_horario":{{"tipo":"turno"|"hora_especifica"|"dia_semana"|"proximidade"|"qualquer","turno":"manha"|"tarde"|"noite"|null,"hora":string|null,"dia_semana":int|null,"descricao":string}}|null}}

Regras críticas:
- "correcao" APENAS quando paciente contradiz algo já dito (ex: "na verdade prefiro tarde")
- "confirmou_pagamento": true se disse "paguei", "enviei comprovante", ou enviou imagem
- "escolha_slot": 1/2/3 somente quando há slots listados e paciente escolhe por número/posição
- "aceita_upgrade": true/false SOMENTE quando houve oferta de upgrade explícita no histórico recente
- Se houve oferta de upgrade (Ana perguntou "Quer manter X ou prefere Y?") e paciente rejeita (ex: "quero X mesmo", "pode deixar", "não quero"), use intent="agendar" e aceita_upgrade=false. NUNCA use recusou_remarketing nesse caso.
- "recusou_remarketing" APENAS quando a Ana enviou mensagem de recontato automático após dias de silêncio e o paciente não quer mais ser contactado. Durante fluxo ativo de agendamento, NUNCA use recusou_remarketing.
- "duvida_clinica" APENAS para perguntas médicas explícitas sobre sintomas, diagnóstico, medicamentos ou condições de saúde (ex: "posso comer X tendo diabetes", "tenho refluxo, pode?"). Paciente falando sobre objetivos, razões para escolher um plano, ou o que espera da consulta → intent="agendar", tem_pergunta=false.
- Quando o paciente está no meio do agendamento (goal=agendar_consulta) e diz algo que explica sua motivação ou objetivo, mantenha intent="agendar" e siga o fluxo.
- Quando o paciente no meio do agendamento (goal=agendar_consulta) diz "trocar o plano", "mudar o plano", "quero outro plano", "quero trocar", NÃO use intent=remarcar nem intent=cancelar. Use intent="agendar" e correcao={{"campo":"plano","valor_novo":null}} para limpar a escolha e re-perguntar.
- Quando o paciente diz "desistir", "não quero mais", "deixa pra lá" durante o agendamento (goal=agendar_consulta) sem ter consulta agendada, use intent="cancelar".
"""

_CONTEXT_TEMPLATE = """\
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


def _normalize_slot_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _match_slot_choice_from_text(message: str, slots: list[dict]) -> int | None:
    """Resolve escolha de slot a partir do texto visível do botão/lista."""
    msg_norm = _normalize_slot_text(message)
    if not msg_norm:
        return None

    for i, s in enumerate(slots):
        data_fmt = _normalize_slot_text(s.get("data_fmt", ""))
        hora = _normalize_slot_text(s.get("hora", ""))
        full_label = _normalize_slot_text(f"{s.get('data_fmt', '')} {s.get('hora', '')}")
        dia = data_fmt.split(",")[0].strip() if data_fmt else ""
        data_curta = data_fmt.split(",", 1)[1].strip() if "," in data_fmt else data_fmt

        candidatos = {c for c in (data_fmt, hora, full_label, dia, data_curta, f"{data_curta} {hora}".strip()) if c}

        if msg_norm in candidatos:
            return i + 1
        if full_label and msg_norm.startswith(full_label):
            return i + 1
        if dia and hora and dia in msg_norm and hora in msg_norm:
            return i + 1
        if data_curta and hora and data_curta in msg_norm and hora in msg_norm:
            return i + 1

    return None


def _extract_receipt_amount(message: str) -> float | None:
    m = re.search(r"\[comprovante valor=([0-9]+(?:\.[0-9]+)?)", message.lower())
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_email(message: str) -> str | None:
    m = re.search(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", message, re.I)
    return m.group(0) if m else None


def _extract_birthdate(message: str) -> str | None:
    m = re.search(r"\b(\d{2})/(\d{2})/(\d{4})\b", message)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2})\b", message)
    if m:
        ano = int(m.group(3))
        ano += 2000 if ano <= datetime.now().year % 100 else 1900
        return f"{ano:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", message)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", message)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{2})(\d{2})(\d{4})\b", message)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


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

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg_lower = message.lower().strip()

    try:
        context = _CONTEXT_TEMPLATE.format(
            goal=state.get("goal", "desconhecido"),
            status=state.get("status", "coletando"),
            collected_summary=collected_summary,
            slots_summary=slots_summary,
            last_assistant=last_assistant[:400],
            history=history_txt,
            message=message,
        )
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=450,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=[{"role": "user", "content": context}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        turno = _parse_turno(data)

        # Heurística pós-LLM: "trocar plano" no fluxo de agendamento → correção
        _TROCAR_PLANO = re.compile(
            r"(trocar|mudar|alterar|outro)\s*(o\s+|a\s+|de\s+)?(plano|opção|opcao|opçao)",
            re.IGNORECASE,
        )
        if (
            state.get("goal") == "agendar_consulta"
            and cd.get("plano")
            and _TROCAR_PLANO.search(message)
            and turno["intent"] in ("remarcar", "cancelar", "fora_de_contexto")
        ):
            turno["intent"] = "agendar"
            turno["correcao"] = {"campo": "plano", "valor_novo": None}

        # Heurística pós-LLM: mensagem é só um número 1-3 com slots disponíveis
        # O LLM às vezes não extrai escolha_slot de mensagens muito curtas.
        import re as _re
        if turno["escolha_slot"] is None and state.get("last_slots_offered"):
            if _re.match(r"^\s*[1-3]\s*$", message):
                turno["escolha_slot"] = int(message.strip())

        # Heurística: botão interativo de slot (slot_1, slot_2, slot_3)
        if turno["escolha_slot"] is None and state.get("last_slots_offered"):
            m = _re.match(r"^slot_([1-3])$", msg_lower)
            if m:
                turno["escolha_slot"] = int(m.group(1))

        # Heurística: paciente responde com o texto visível do slot
        # Ex: "quarta, 29/04 10h", "29/04 10h", "quarta"
        if turno["escolha_slot"] is None and state.get("last_slots_offered"):
            turno["escolha_slot"] = _match_slot_choice_from_text(message, state["last_slots_offered"])

        # Heurística pós-LLM: resposta de botão interativo (ID normalizado)
        if turno["forma_pagamento"] is None and msg_lower in ("pix", "cartao"):
            turno["forma_pagamento"] = msg_lower
            if turno["intent"] == "fora_de_contexto":
                turno["intent"] = "agendar"
        if turno["modalidade"] is None and msg_lower in ("presencial", "online"):
            turno["modalidade"] = msg_lower
            if turno["intent"] == "fora_de_contexto":
                turno["intent"] = "agendar"
        if turno["plano"] is None and msg_lower in _PLANOS:
            turno["plano"] = msg_lower
            if turno["intent"] == "fora_de_contexto":
                turno["intent"] = "agendar"

        # Heurística: botão interativo de objetivo
        _OBJETIVO_BUTTONS = {"emagrecer", "ganhar_massa", "lipedema", "outro"}
        if turno["objetivo"] is None and msg_lower in _OBJETIVO_BUTTONS:
            turno["objetivo"] = msg_lower.replace("_", " ")
            if turno["intent"] == "fora_de_contexto":
                turno["intent"] = "agendar"

        # Heurística: comprovante de pagamento por mídia ou confirmação textual
        contexto_pagamento = (
            state.get("status") == "aguardando_pagamento"
            or state.get("last_action") in ("await_payment", "ask_forma_pagamento", "gerar_link_cartao")
            or state.get("collected_data", {}).get("forma_pagamento") in ("pix", "cartao")
        )
        if contexto_pagamento and (
            msg_lower == "[mídia]"
            or any(w in msg_lower for w in ("comprovante", "paguei", "pago", "pagamento", "enviei"))
        ):
            turno["confirmou_pagamento"] = True
            turno["intent"] = "confirmar_pagamento"
        if turno.get("valor_comprovante") is None:
            turno["valor_comprovante"] = _extract_receipt_amount(message)
        if turno.get("email") is None:
            turno["email"] = _extract_email(message)
        if turno.get("data_nascimento") is None:
            turno["data_nascimento"] = _extract_birthdate(message)

        return turno

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
        "valor_comprovante": float(data["valor_comprovante"]) if data.get("valor_comprovante") is not None else None,
        "data_nascimento": _str_or_none(data.get("data_nascimento")),
        "email": _str_or_none(data.get("email")),
        "instagram": _str_or_none(data.get("instagram")),
        "profissao": _str_or_none(data.get("profissao")),
        "cep_endereco": _str_or_none(data.get("cep_endereco")),
        "indicacao_origem": _str_or_none(data.get("indicacao_origem")),
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
        "valor_comprovante": _extract_receipt_amount(text),
        "data_nascimento": _extract_birthdate(text),
        "email": _extract_email(text),
        "instagram": None,
        "profissao": None,
        "cep_endereco": None,
        "indicacao_origem": None,
        "correcao": None,
        "tem_pergunta": "?" in text,
        "topico_pergunta": None,
        "preferencia_horario": None,
    }
