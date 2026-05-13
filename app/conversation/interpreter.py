"""
Interpreter - extrai intent + entities da mensagem do paciente.

Função principal:
    async def interpretar(mensagem, estado_atual, historico) -> Interpretacao

Este módulo não decide fluxo. Ele só normaliza entrada em uma estrutura.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime
from typing import Any

from app.conversation.config_loader import config
from app.conversation.models import Interpretacao
from app.conversation.rules import R12_validar_nome_nao_generico

logger = logging.getLogger(__name__)

_DIAS = {
    "segunda": 0,
    "segunda-feira": 0,
    "terca": 1,
    "terça": 1,
    "terça-feira": 1,
    "quarta": 2,
    "quarta-feira": 2,
    "quinta": 3,
    "quinta-feira": 3,
    "sexta": 4,
    "sexta-feira": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def _texto_mensagem(mensagem: dict[str, Any]) -> str:
    if "text" in mensagem and isinstance(mensagem["text"], str):
        return mensagem["text"]
    if isinstance(mensagem.get("text"), dict):
        return str(mensagem["text"].get("body") or "")
    if mensagem.get("body"):
        return str(mensagem["body"])
    if mensagem.get("caption"):
        return str(mensagem["caption"])
    if mensagem.get("interactive"):
        interactive = mensagem.get("interactive") or {}
        return (
            interactive.get("button_reply", {}).get("id")
            or interactive.get("list_reply", {}).get("id")
            or ""
        )
    return str(mensagem.get("content") or "")


def _message_type(mensagem: dict[str, Any]) -> str:
    return str(mensagem.get("type") or mensagem.get("message_type") or "text")


def _botao_id(mensagem: dict[str, Any], texto: str) -> str | None:
    if mensagem.get("botao_id"):
        return str(mensagem["botao_id"])
    interactive = mensagem.get("interactive") or {}
    if isinstance(interactive, dict):
        bid = interactive.get("button_reply", {}).get("id") or interactive.get("list_reply", {}).get("id")
        if bid:
            return str(bid)
    if texto.startswith(("primeira_consulta", "ja_paciente", "obj_", "plano_", "upsell_", "mod_", "slot_", "pag_")):
        return texto.strip()
    return None


def _norm(texto: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


def _primeiro_nome(nome: str | None) -> str:
    return (nome or "").strip().split()[0].capitalize() if (nome or "").strip() else ""


def _normalizar_entities_llm(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, list):
        return {}
    entities: dict[str, Any] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = item.get("type") or item.get("name") or item.get("key")
        if not key:
            continue
        value = item.get("value", item.get("text"))
        entities[str(key)] = value
    return entities


def _extrair_nome(texto: str) -> str | None:
    raw = texto.strip()
    if not raw:
        return None
    raw = re.sub(r"^(meu nome (e|é)|sou|eu sou|chamo|me chamo)\s+", "", raw, flags=re.I).strip()
    raw = re.sub(r"[^A-Za-zÀ-ÿ\s'-]", "", raw).strip()
    if not raw or len(raw) < 2:
        return None
    if len(raw.split()) > 5:
        return None
    return " ".join(p.capitalize() for p in raw.split())


def _extrair_preferencia(texto: str) -> dict[str, Any]:
    n = _norm(texto)
    entities: dict[str, Any] = {
        "tem_dia": False,
        "tem_hora": False,
        "tem_turno": False,
        "tem_hora_fora_grade": False,
        "validar_grade": "passou",
    }

    for label, idx in _DIAS.items():
        if _norm(label) in n:
            entities["tem_dia"] = True
            entities["dia_extraido"] = idx
            entities["dia_semana_texto"] = label
            if idx == 4:
                entities["tem_dia"] = "sexta"
            if idx in (5, 6):
                entities["tem_dia"] = label
            break
    if "hoje" in n:
        entities["tem_dia"] = "hoje"
        entities["data_pedida"] = "data_atual"

    turno = None
    if any(x in n for x in ("manha", "cedo")):
        turno = "manha"
    elif "tarde" in n:
        turno = "tarde"
    elif "noite" in n:
        turno = "noite"
    if turno:
        entities["tem_turno"] = turno if entities.get("tem_dia") == "sexta" else True
        entities["turno_extraido"] = turno
        entities["turno_inferido"] = turno
        entities["turno_inferido_ou_null"] = turno

    m = re.search(r"\b([01]?\d|2[0-3])\s*(?:h|:00)?\b", n)
    if m:
        hora_i = int(m.group(1))
        entities["tem_hora"] = True
        entities["hora_extraida"] = f"{hora_i:02d}:00"
        if hora_i in (8, 9, 10):
            turno = "manha"
        elif hora_i in (15, 16, 17):
            turno = "tarde"
        elif hora_i in (18, 19):
            turno = "noite"
        else:
            entities["tem_hora_fora_grade"] = True
            entities["validar_grade"] = "falhou"
        if turno:
            entities["turno_inferido"] = turno
            entities["turno_inferido_ou_null"] = turno

    return entities


def _extrair_cadastro(texto: str, state: dict[str, Any] | None) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    email = re.search(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", texto, re.I)
    data = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", texto)
    phone = re.search(r"\b(?:\+?55)?\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}\b", texto)
    nome_match = re.search(r"(?:nome completo[:\s-]+|^)([A-Za-zÀ-ÿ]{2,}(?:\s+[A-Za-zÀ-ÿ]{2,})+)", texto, re.I)

    if email:
        entities["email"] = email.group(0).lower()
    if data:
        ano = int(data.group(3))
        if ano < 100:
            ano += 2000 if ano <= date.today().year % 100 else 1900
        data_nasc = f"{int(data.group(1)):02d}/{int(data.group(2)):02d}/{ano}"
        entities["data_nasc"] = data_nasc
        try:
            nasc = datetime.strptime(data_nasc, "%d/%m/%Y").date()
            entities["tem_idade"] = (date.today() - nasc).days // 365
        except ValueError:
            pass
    if phone:
        entities["whatsapp_extraido"] = re.sub(r"\D", "", phone.group(0))
    if nome_match:
        entities["nome_completo"] = nome_match.group(1).strip().title()
    elif state:
        nome_estado = ((state.get("collected_data") or {}).get("nome") or "").strip()
        if len(nome_estado.split()) >= 2:
            entities["nome_completo"] = nome_estado

    entities["tem_nome_completo"] = bool(entities.get("nome_completo"))
    entities["tem_data_nascimento"] = bool(entities.get("data_nasc"))
    entities["tem_email"] = bool(entities.get("email"))
    entities["tem_whatsapp_contato"] = bool(entities.get("whatsapp_extraido"))
    obrig = ["tem_nome_completo", "tem_data_nascimento", "tem_email", "tem_whatsapp_contato"]
    tem_algum = any(entities[k] for k in obrig)
    entities["informou_alguns_obrigatorios"] = tem_algum and not all(entities[k] for k in obrig)
    entities["informou_um_dado_isolado"] = sum(1 for k in obrig if entities[k]) == 1
    return entities


def _heuristica(mensagem: dict[str, Any], estado_atual: str, state: dict[str, Any] | None) -> Interpretacao:
    texto = _texto_mensagem(mensagem)
    n = _norm(texto)
    msg_type = _message_type(mensagem)
    botao = _botao_id(mensagem, texto)
    entities: dict[str, Any] = {"texto_original": texto}
    validacoes: dict[str, Any] = {}
    intent = "ambigua"
    confidence = 0.75

    if msg_type in ("image", "document") or "comprovante valor=" in n:
        intent = "enviou_comprovante"
        if m := re.search(r"comprovante valor=([0-9]+(?:[.,][0-9]+)?)", texto, re.I):
            entities["valor_pago"] = float(m.group(1).replace(",", "."))
        confidence = 0.95
    elif any(x in n for x in ("desist", "nao quero", "deixa pra la")):
        intent = "desistir"
    elif estado_atual == "aguardando_nome":
        if "quanto" in n or "valor" in n or "preco" in n or "custa" in n:
            intent = "duvida_operacional"
        else:
            intent = "informar_nome"
            nome = _extrair_nome(texto)
            entities["nome_extraido"] = nome or texto.strip()
            entities["primeiro_nome"] = _primeiro_nome(nome)
            validacoes["validacao_nome_passou"] = bool(nome and R12_validar_nome_nao_generico(nome).passou)
    elif estado_atual == "aguardando_status_paciente":
        intent = "escolher_status_paciente"
    elif estado_atual == "aguardando_objetivo":
        intent = "pergunta_clinica" if any(x in n for x in ("dieta", "comer", "suplement")) else "informar_objetivo"
    elif estado_atual == "aguardando_escolha_plano":
        intent = "pedir_desconto" if "desconto" in n else "escolher_plano"
    elif estado_atual == "oferecendo_upsell":
        intent = "aceitar_upsell" if any(x in n for x in ("sim", "aceito", "quero", "melhor")) else "recusar_upsell"
    elif estado_atual == "aguardando_modalidade":
        intent = "duvida_modalidade" if "diferenca" in n else "escolher_modalidade"
    elif estado_atual == "aguardando_preferencia_horario":
        intent = "informar_preferencia_horario"
        entities.update(_extrair_preferencia(texto))
    elif estado_atual == "aguardando_escolha_slot":
        if any(x in n for x in ("outra", "mais", "nao serve", "nenhum", "outro turno")):
            intent = "rejeitar_slots"
        else:
            intent = "escolher_slot"
            if botao and botao.startswith("slot_"):
                entities["slot_correspondente"] = botao
            elif "segund" in n or "2" in n:
                entities["slot_match"] = "slot_2"
                entities["match_texto_com_slots"] = True
            elif "terceir" in n or "3" in n:
                entities["slot_match"] = "slot_3"
                entities["match_texto_com_slots"] = True
            else:
                entities["slot_match"] = "slot_1"
                entities["match_texto_com_slots"] = True
    elif estado_atual == "aguardando_forma_pagamento":
        intent = "duvida_pagamento" if any(x in n for x in ("parcel", "juros")) else "escolher_forma_pagamento"
    elif estado_atual == "aguardando_pagamento_pix":
        intent = "enviou_comprovante" if "comprovante" in n else "duvida_pagamento"
    elif estado_atual == "aguardando_pagamento_cartao":
        intent = "confirmou_pagamento" if any(x in n for x in ("paguei", "finalizei", "pronto")) else "problema_pagamento"
    elif estado_atual == "aguardando_cadastro":
        if any(x in n for x in ("gravida", "gestante", "gestacao")):
            intent = "informar_cadastro"
        elif any(x in n for x in ("quanto", "valor", "custa")):
            intent = "duvida_operacional"
        else:
            intent = "informar_cadastro"
        entities.update(_extrair_cadastro(texto, state))
    else:
        intent = "agendar_consulta" if any(x in n for x in ("oi", "ola", "agendar", "consulta")) else "ambigua"

    if botao:
        confidence = 0.98
    return Interpretacao(
        intent=intent,
        confidence=confidence,
        entities={k: v for k, v in entities.items() if k != "texto_original"},
        botao_id=botao,
        message_type=msg_type,
        patient_message_type=msg_type,
        validacoes=validacoes,
        texto_original=texto,
    )


async def _interpretar_gemini(
    mensagem: dict[str, Any],
    estado_atual: str,
    historico: list[dict[str, Any]],
    intents_possiveis: list[str],
) -> Interpretacao | None:
    if not os.environ.get("GEMINI_API_KEY"):
        return None
    try:
        from app import llm_client

        system = (
            "Você é um interpreter estrutural. Não decida fluxo e não escreva resposta ao paciente. "
            "Retorne somente JSON com intent, confidence, entities, validacoes."
        )
        user = json.dumps(
            {
                "estado_atual": estado_atual,
                "intents_possiveis": intents_possiveis,
                "historico_ultimas_6": historico[-6:],
                "mensagem": mensagem,
            },
            ensure_ascii=False,
            default=str,
        )
        raw = await llm_client.complete_text_async(system=system, user=user, max_tokens=500, temperature=0.0)
        data = json.loads(llm_client.strip_json_fences(raw))
        return Interpretacao(
            intent=str(data.get("intent") or "ambigua"),
            confidence=float(data.get("confidence") or 0.5),
            entities=_normalizar_entities_llm(data.get("entities")),
            botao_id=data.get("botao_id"),
            message_type=_message_type(mensagem),
            patient_message_type=_message_type(mensagem),
            validacoes=_normalizar_entities_llm(data.get("validacoes")),
            texto_original=_texto_mensagem(mensagem),
        )
    except Exception as exc:
        logger.warning("Interpreter Gemini falhou; usando heurística: %s", exc)
        return None


async def interpretar(
    mensagem: dict[str, Any],
    estado_atual: str,
    historico: list[dict[str, Any]] | None = None,
    state: dict[str, Any] | None = None,
) -> Interpretacao:
    fluxo = config.get_fluxo("agendamento_paciente_novo")
    estado = fluxo.estados.get(estado_atual)
    intents = estado.intents_aceitas if estado else []
    heuristic = _heuristica(mensagem, estado_atual, state)
    deterministic_states = {
        "aguardando_nome",
        "aguardando_status_paciente",
        "aguardando_objetivo",
        "aguardando_escolha_plano",
        "oferecendo_upsell",
        "aguardando_modalidade",
        "aguardando_preferencia_horario",
        "aguardando_escolha_slot",
        "aguardando_forma_pagamento",
        "aguardando_pagamento_pix",
        "aguardando_pagamento_cartao",
        "aguardando_cadastro",
    }
    if estado_atual in deterministic_states and heuristic.intent != "ambigua":
        return heuristic
    gemini = await _interpretar_gemini(mensagem, estado_atual, historico or [], intents)
    if gemini is not None and (not intents or gemini.intent in intents):
        return gemini
    if gemini is not None:
        logger.info(
            "Interpreter Gemini retornou intent fora do estado; usando heurística. estado=%s intent=%s aceitas=%s",
            estado_atual,
            gemini.intent,
            intents,
        )
    return heuristic
