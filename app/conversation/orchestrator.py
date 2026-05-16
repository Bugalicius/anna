"""
Orchestrator - coordena o pipeline de um turno conversacional v2.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.conversation import response_writer, rules, state_machine
from app.conversation.config_loader import config
from app.conversation.interpreter import _extrair_nome, _extrair_preferencia, interpretar
from app.conversation.locks import acquire_processing_lock, release_processing_lock
from app.conversation.models import AcaoAutorizada, Mensagem, ResultadoTurno, TipoAcao
from app.conversation.state import add_message, create_state, get_state_redis, load_state, maybe_reset_stale_state, save_state
from app.conversation.tools.registry import call_tool

logger = logging.getLogger(__name__)

AGENDAMENTO_ID = "agendamento_paciente_novo"
REMARCACAO_ID = "remarcacao"
CANCELAMENTO_ID = "cancelamento"
FLUXO_ID = AGENDAMENTO_ID
LOG_PATH = Path("logs/metrics.jsonl")
AGGRESSION_LOG_PATH = Path("logs/agressoes.jsonl")

ACTION_NEXT_STATE = {
    "ir_apresentacao_planos": "apresentando_planos",
    "oferecer_upsell": "oferecendo_upsell",
    "ir_modalidade": "aguardando_modalidade",
    "ir_aguardando_preferencia_horario": "aguardando_preferencia_horario",
    "ir_aguardando_forma_pagamento": "aguardando_forma_pagamento",
    "ir_aguardando_pagamento_pix": "aguardando_pagamento_pix",
    "ir_aguardando_pagamento_cartao": "aguardando_pagamento_cartao",
    "criar_agendamento": "criando_agendamento",
}


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


def _ensure_v2_state(state: dict[str, Any], phone: str) -> dict[str, Any]:
    state.setdefault("phone", phone)
    state.setdefault("fluxo_id", FLUXO_ID)
    state.setdefault("estado", "inicio")
    state.setdefault("history", [])
    state.setdefault("collected_data", {})
    state.setdefault("appointment", {})
    state.setdefault("flags", {})
    state.setdefault("last_slots_offered", [])
    state.setdefault("slots_pool", [])
    state.setdefault("slots_rejeitados", [])
    state.setdefault("rodada_negociacao", 0)
    state.setdefault("status", "coletando")
    cd = state["collected_data"]
    for key in (
        "nome",
        "nome_completo",
        "status_paciente",
        "objetivo",
        "plano",
        "modalidade",
        "preferencia_horario",
        "preferencia_horario_nova",
        "forma_pagamento",
        "data_nascimento",
        "email",
        "whatsapp_contato",
        "instagram",
        "profissao",
        "cep_endereco",
        "indicacao_origem",
        "motivo_cancelamento",
    ):
        cd.setdefault(key, None)
    state["appointment"].setdefault("slot_escolhido", None)
    state["appointment"].setdefault("slot_escolhido_novo", None)
    state["appointment"].setdefault("consulta_atual", None)
    state["flags"].setdefault("pagamento_confirmado", False)
    state.setdefault("fora_contexto_count", 0)
    state.setdefault("fallback_streak", 0)
    state.setdefault("last_response_hash", None)
    state.setdefault("last_message_at", None)
    return state


def _get_path(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    if parts[0] == "state":
        parts = parts[1:]
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _primeiro_nome(state: dict[str, Any]) -> str:
    nome = (state.get("collected_data") or {}).get("nome") or ""
    return str(nome).split()[0].capitalize() if str(nome).strip() else ""


def _slot_label(slot: dict[str, Any]) -> str:
    return f"{slot.get('data_fmt') or slot.get('datetime', '')} {slot.get('hora') or ''}".strip()


def _slot_descricao(slot: dict[str, Any]) -> str:
    return _slot_label(slot)


def _texto_mensagem(mensagem: dict[str, Any]) -> str:
    if isinstance(mensagem.get("text"), str):
        return str(mensagem.get("text") or "")
    if isinstance(mensagem.get("text"), dict):
        return str((mensagem.get("text") or {}).get("body") or "")
    return str(mensagem.get("body") or mensagem.get("content") or mensagem.get("caption") or "")


def _norm_text(texto: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


def _is_aggressive_text(texto: str) -> bool:
    n = _norm_text(texto)
    termos = (
        "vai tomar no cu",
        "tomar no cu",
        "filha da puta",
        "filho da puta",
        "porra",
        "caralho",
        "merda",
        "buceta",
        "lixo",
        "burra",
        "burro",
        "incompetente",
        "porcaria",
        "vagabundo",
        "vagabunda",
        "enrolado",
        "enrolando",
        "procon",
        "processar",
        "denunciar",
    )
    return any(t in n for t in termos)


def _mentions_pregnancy(texto: str) -> bool:
    n = _norm_text(texto)
    # Usa \b para evitar falso positivo em palavras que contêm o termo como
    # prefixo (ex: "gravidade" contém "gravida" como substring).
    return bool(re.search(r"\b(gravida|gestante|gestacao|gravidez)\b", n))


def _mentions_clinical_need(texto: str) -> bool:
    n = _norm_text(texto)
    termos = (
        "diabetes",
        "emagrecer",
        "dieta",
        "compulsao",
        "compulsiva",
        "comer",
        "suplement",
        "ozempic",
        "remedio",
        "ansiedade",
        "depressao",
        "panico",
    )
    return any(t in n for t in termos)


def _is_bioimpedancia_question(texto: str) -> bool:
    n = _norm_text(texto)
    return any(t in n for t in ("bioimpedancia", "bio impedancia", "biopendencia", "impedancia"))


def _status_paciente_from_text(texto: str) -> str | None:
    n = _norm_text(texto)
    if any(t in n for t in ("primeira", "primeira vez", "nunca", "novo", "nova")):
        return "novo"
    if any(t in n for t in ("ja sou", "paciente", "retorno", "voltar")):
        return "retorno"
    return None


def _objetivo_from_text(texto: str) -> str | None:
    n = _norm_text(texto)
    if any(t in n for t in ("emagrecer", "perder peso", "perder gordura", "secar")):
        return "emagrecer"
    if any(t in n for t in ("ganhar massa", "hipertrofia", "ganhar peso", "massa muscular")):
        return "ganhar_massa"
    if "lipedema" in n:
        return "lipedema"
    return None


def _extrair_nome_primeira_mensagem(texto: str) -> str | None:
    match = re.search(
        r"\b(?:sou|eu sou|me chamo|chamo|meu nome (?:e|é))\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s'-]{1,80})",
        texto,
        flags=re.I,
    )
    if not match:
        return None
    trecho = re.split(
        r"[,;]|\b(?:primeira|primeira vez|primeira consulta|novo|nova|já sou|ja sou|paciente|retorno|quero|gostaria|preciso)\b",
        match.group(1),
        maxsplit=1,
        flags=re.I,
    )[0].strip()
    nome = _extrair_nome(trecho)
    if not nome or not rules.R12_validar_nome_nao_generico(nome).passou:
        return None
    return nome


def _looks_like_cadastro(texto: str) -> bool:
    return bool(
        re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", texto)
        or re.search(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", texto, re.I)
    )


def _looks_like_cadastro_attempt(texto: str) -> bool:
    n = _norm_text(texto)
    return _looks_like_cadastro(texto) or any(t in n for t in ("arroba", "gmail", "hotmail", "email", "e-mail"))


def _bioimpedancia_answer() -> str:
    try:
        from app.knowledge_base import kb

        for item in kb.faq_combinado():
            pergunta = _norm_text(item.get("pergunta") or item.get("question") or "")
            if "bioimpedancia" in pergunta:
                resposta = item.get("resposta") or item.get("answer") or ""
                if resposta:
                    return str(resposta)
    except Exception:
        pass
    return (
        "A Thaynara não usa bioimpedância porque ela pode apresentar muitas variações e precisa de preparo específico. "
        "No lugar, ela usa adipômetro, circunferências corporais e fotos para acompanhar sua evolução 💚"
    )


def _mensagens_retomada_duvida_operacional(state: dict[str, Any], estado: str, resposta: str) -> list[Mensagem]:
    nome = _primeiro_nome(state)
    if estado == "aguardando_status_paciente":
        return [
            Mensagem(tipo="texto", conteudo=resposta),
            Mensagem(
                tipo="botoes",
                conteudo="E sobre a consulta: é sua primeira consulta com a Thaynara ou você já é paciente?",
                botoes=[  # type: ignore[list-item]
                    {"id": "primeira_consulta", "label": "Primeira consulta"},
                    {"id": "ja_paciente", "label": "Já sou paciente"},
                ],
            ),
        ]
    if estado == "aguardando_objetivo":
        return [
            Mensagem(tipo="texto", conteudo=resposta),
            Mensagem(
                tipo="botoes",
                conteudo=f"{nome + ', ' if nome else ''}me conta: qual seu principal objetivo agora?",
                botoes=[  # type: ignore[list-item]
                    {"id": "obj_emagrecer", "label": "Emagrecer"},
                    {"id": "obj_ganhar_massa", "label": "Ganhar massa"},
                    {"id": "obj_lipedema", "label": "Lipedema"},
                    {"id": "obj_outro", "label": "Outro objetivo"},
                ],
            ),
        ]
    if estado in {"inicio", "aguardando_nome"}:
        return [
            Mensagem(tipo="texto", conteudo=resposta),
            Mensagem(tipo="texto", conteudo="Pra começar, qual é o seu nome e sobrenome?"),
        ]
    return [Mensagem(tipo="texto", conteudo=resposta)]


def _mensagens_bioimpedancia_com_status(
    state: dict[str, Any],
    texto: str,
    resposta: str,
) -> tuple[list[Mensagem], str] | None:
    status = _status_paciente_from_text(texto)
    if not status:
        return None
    state.setdefault("collected_data", {})["status_paciente"] = status
    if status == "novo":
        return _mensagens_retomada_duvida_operacional(state, "aguardando_objetivo", resposta), "aguardando_objetivo"
    return [
        Mensagem(tipo="texto", conteudo=resposta),
        Mensagem(
            tipo="texto",
            conteudo="Que bom te ver de novo! 💚 Pra eu localizar seu cadastro, pode me mandar seu nome completo?",
        ),
    ], "aguardando_nome_completo_retorno"


def _mensagens_nome_com_status(state: dict[str, Any], status: str) -> tuple[list[Mensagem], str]:
    if status == "novo":
        primeiro = _primeiro_nome(state)
        return [
            Mensagem(tipo="texto", conteudo=f"Que bom te receber, {primeiro}! 💚"),
            Mensagem(
                tipo="botoes",
                conteudo="Antes de te apresentar nossos planos, me conta: qual seu principal objetivo agora?",
                botoes=[  # type: ignore[list-item]
                    {"id": "obj_emagrecer", "label": "Emagrecer"},
                    {"id": "obj_ganhar_massa", "label": "Ganhar massa"},
                    {"id": "obj_lipedema", "label": "Tratar lipedema"},
                    {"id": "obj_outro", "label": "Outro objetivo"},
                ],
            ),
        ], "aguardando_objetivo"
    return [
        Mensagem(
            tipo="texto",
            conteudo="Que bom te ver de novo! 💚 Pra eu localizar seu cadastro, pode me mandar seu nome completo?",
        )
    ], "aguardando_nome_completo_retorno"


def _underage_from_text(texto: str) -> int | None:
    n = _norm_text(texto)
    patterns = (
        # "tenho 15 anos" / "minha idade é 15 anos"
        r"\b(?:tenho|idade)\s+(\d{1,2})\s+anos\b",
        # "minha filha de 14 anos" / "a paciente tem 13 anos" / "meu filho tem 13 anos"
        r"\b(?:filha|filho|sobrinha|sobrinho|menina|menino|adolescente|paciente|crianca|criança)\s+(?:de|tem)\s+(\d{1,2})\s+anos\b",
        # Padrão genérico "X anos" removido: capturava qualquer contexto
        # (ex: "minha empresa tem 10 anos", "estou há 5 anos tentando emagrecer")
        # causando bloqueio falso de pacientes adultos.
    )
    for pattern in patterns:
        match = re.search(pattern, n)
        if not match:
            continue
        idade = int(match.group(1))
        if idade < 16:
            return idade
    return None


async def _handle_restriction(
    state: dict[str, Any],
    phone: str,
    texto: str,
    estado_antes: str,
) -> tuple[list[Mensagem], str, list[str]] | None:
    tools_chamadas: list[str] = []
    gestante = _mentions_pregnancy(texto)
    menor_idade = _underage_from_text(texto)
    if not gestante and menor_idade is None:
        return None

    motivo = "gestante" if gestante else "menor_16"
    state.setdefault("flags", {})["restricao_atendimento"] = motivo
    state["estado"] = "concluido_escalado"

    deve_escalar = bool(state.get("flags", {}).get("pagamento_confirmado")) or (
        gestante and _mentions_clinical_need(texto)
    )
    if deve_escalar:
        tools_chamadas.append("escalar_breno_silencioso")
        await call_tool(
            "escalar_breno_silencioso",
            {
                "contexto": {
                    "motivo": motivo,
                    "telefone": phone,
                    "estado": estado_antes,
                    "mensagem": texto,
                    "pagamento_confirmado": bool(state.get("flags", {}).get("pagamento_confirmado")),
                }
            },
        )
        return [
            Mensagem(
                tipo="texto",
                conteudo="Vou pedir pra equipe te orientar por aqui certinho, tá? Um momento 💚",
            )
        ], "concluido_escalado", tools_chamadas

    if gestante:
        texto_resposta = "Infelizmente a Thaynara não realiza atendimento para gestantes no momento 😔"
    else:
        texto_resposta = "Infelizmente a Thaynara não realiza atendimento para menores de 16 anos no momento 😔"
    return [Mensagem(tipo="texto", conteudo=texto_resposta)], "concluido_escalado", tools_chamadas


async def _log_aggression(payload: dict[str, Any]) -> None:
    try:
        AGGRESSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with AGGRESSION_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        logger.warning("Falha ao registrar agressão: %s", exc)


async def _handle_aggression(
    state: dict[str, Any],
    phone: str,
    texto: str,
    estado_antes: str,
) -> tuple[list[Mensagem], list[str]]:
    count = int(state.get("agressao_count") or 0) + 1
    state["agressao_count"] = count
    tools_chamadas: list[str] = []
    await _log_aggression(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": state.get("phone_hash") or _phone_hash(phone),
            "estado": estado_antes,
            "count": count,
            "mensagem": texto[:500],
        }
    )
    if count >= 2:
        tools_chamadas.append("escalar_breno_silencioso")
        await call_tool(
            "escalar_breno_silencioso",
            {
                "contexto": {
                    "motivo": "agressao_reincidente",
                    "count": count,
                    "telefone": phone,
                    "estado": estado_antes,
                    "ultima_mensagem": texto,
                }
            },
        )
        return [
            Mensagem(
                tipo="texto",
                conteudo="Vou pedir pra alguém da equipe te dar atenção especial, tá? Um momento 💚",
            )
        ], tools_chamadas
    return [
        Mensagem(
            tipo="texto",
            conteudo="Sinto muito se algo te deixou frustrado(a). 💚 Posso te ajudar com agendamento ou alguma dúvida?",
        )
    ], tools_chamadas


def _consulta_atual(state: dict[str, Any]) -> dict[str, Any]:
    consulta = (state.get("appointment") or {}).get("consulta_atual") or {}
    return consulta if isinstance(consulta, dict) else {}


def _dt_consulta(consulta: dict[str, Any]) -> datetime | None:
    raw = consulta.get("inicio") or consulta.get("datetime") or consulta.get("data_hora") or consulta.get("start")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sexta_semana_seguinte(dt: datetime | None) -> date:
    base = (dt or datetime.now()).date()
    dias_ate_proxima_sexta = (4 - base.weekday()) % 7
    if dias_ate_proxima_sexta == 0:
        dias_ate_proxima_sexta = 7
    return base + timedelta(days=dias_ate_proxima_sexta)


def _formatar_data_slot(slot: dict[str, Any]) -> tuple[str, str]:
    data_fmt = str(slot.get("data_fmt") or "")
    hora = str(slot.get("hora") or "")
    if data_fmt and hora:
        return data_fmt, hora
    dt = _dt_consulta(slot)
    if not dt:
        return data_fmt or str(slot.get("datetime") or ""), hora
    return dt.strftime("%d/%m/%Y"), hora or dt.strftime("%H:%M")


def _slot_por_id(state: dict[str, Any], slot_id: str | None) -> dict[str, Any] | None:
    if not slot_id or not slot_id.startswith("slot_"):
        return None
    try:
        idx = int(slot_id.split("_", 1)[1]) - 1
    except ValueError:
        return None
    slots = state.get("last_slots_offered") or []
    return slots[idx] if 0 <= idx < len(slots) else None


def _valor_total(state: dict[str, Any]) -> float:
    cd = state.get("collected_data") or {}
    plano = cd.get("plano") or "ouro"
    modalidade = cd.get("modalidade") or "presencial"
    plano_cfg = config.get_plano(str(plano))
    return float(plano_cfg.valores.pix_online if modalidade == "online" else plano_cfg.valores.pix_presencial)


def _contexto_template(state: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = dict(state)
    ctx["primeiro_nome"] = _primeiro_nome(state)
    total = _valor_total(state) if (state.get("collected_data") or {}).get("plano") else 0
    ctx["valor_total"] = f"{total:.2f}".replace(".", ",") if total else ""
    ctx["valor_sinal"] = f"{(total * 0.5):.2f}".replace(".", ",") if total else ""
    slot = (state.get("appointment") or {}).get("slot_escolhido") or {}
    if isinstance(slot, dict):
        ctx["data_completa"] = slot.get("data_fmt") or slot.get("datetime", "")[:10]
        ctx["hora"] = slot.get("hora") or slot.get("datetime", "")[11:16]
        ctx["dia_semana"] = ctx["data_completa"]
    consulta = _consulta_atual(state)
    if consulta:
        dt = _dt_consulta(consulta)
        data_original, hora_original = _formatar_data_slot(consulta)
        ctx.update(
            {
                "data": data_original,
                "hora": ctx.get("hora") or hora_original,
                "data_original": data_original,
                "hora_original": hora_original,
                "dia_semana": ctx.get("dia_semana") or data_original,
                "dia_semana_original": data_original,
                "data_limite": _sexta_semana_seguinte(dt).strftime("%d/%m/%Y"),
                "modalidade": consulta.get("modalidade") or (state.get("collected_data") or {}).get("modalidade") or "",
                "plano": consulta.get("plano") or (state.get("collected_data") or {}).get("plano") or "",
                "nome": (state.get("collected_data") or {}).get("nome") or consulta.get("nome") or "",
            }
        )
    for i, s in enumerate(state.get("last_slots_offered") or [], start=1):
        ctx[f"slot_{i}_descricao"] = _slot_descricao(s)
        ctx[f"slot_{i}_label_curto"] = _slot_label(s)[:20]
    if extra:
        ctx.update(extra)
    return ctx


def _normalizar_entidades(
    state: dict[str, Any],
    entities: dict[str, Any],
    botao_id: str | None,
    texto_original: str,
) -> dict[str, Any]:
    entidades = dict(entities or {})
    texto = texto_original or str(entidades.get("texto_original") or "")
    cd = state.get("collected_data") or {}

    texto_norm = texto.lower()
    if "online" in texto_norm:
        entidades["modalidade_mencionada"] = "online"
        cd["modalidade"] = "online"
    elif "presencial" in texto_norm:
        entidades["modalidade_mencionada"] = "presencial"
        cd["modalidade"] = "presencial"

    plano_atual = cd.get("plano")
    upsell_dest = {"unica": "com_retorno", "com_retorno": "ouro", "ouro": "premium"}.get(str(plano_atual))
    if upsell_dest:
        entidades["plano_destino_calculado"] = upsell_dest

    slot = _slot_por_id(state, botao_id) or _slot_por_id(state, entidades.get("slot_correspondente"))
    if slot:
        entidades["slot_correspondente"] = slot
        entidades["slot_match"] = slot
    elif isinstance(entidades.get("slot_match"), str):
        slot = _slot_por_id(state, entidades["slot_match"])
        if slot:
            entidades["slot_match"] = slot
    entidades["rodada_atual"] = state.get("rodada_negociacao", 0)
    return entidades


def _aplicar_salvar_no_estado(state: dict[str, Any], salvar: dict[str, Any]) -> None:
    for path, value in (salvar or {}).items():
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            continue
        _set_path(state, path, value)


def _aplicar_efeitos_especiais(state: dict[str, Any], acao: AcaoAutorizada) -> None:
    if acao.situacao_nome == "rejeitou_todos":
        rejeitados = list(state.get("slots_rejeitados") or [])
        for slot in state.get("last_slots_offered") or []:
            if slot not in rejeitados:
                rejeitados.append(slot)
        state["slots_rejeitados"] = rejeitados
        state["last_slots_offered"] = []
        state["rodada_negociacao"] = int(state.get("rodada_negociacao") or 0) + 1


async def _escalar_agendamento_inviavel(
    *,
    state: dict[str, Any],
    phone: str,
    motivo: str,
    estado_antes: str,
    ultima_mensagem: str,
) -> None:
    await call_tool(
        "escalar_breno_silencioso",
        {
            "contexto": {
                "motivo": motivo,
                "telefone": phone,
                "estado": estado_antes,
                "rodada_negociacao": state.get("rodada_negociacao"),
                "invalid_preferencia_count": state.get("invalid_preferencia_count"),
                "ultima_mensagem": ultima_mensagem,
            }
        },
    )


def _acao_navegacao(acao: AcaoAutorizada) -> str | None:
    action = (acao.dados or {}).get("action")
    return ACTION_NEXT_STATE.get(str(action or ""))


def _get_botao_id(mensagem: dict[str, Any]) -> str | None:
    """Extrai button_id da mensagem interativa sem precisar do interpreter."""
    if mensagem.get("botao_id"):
        return str(mensagem["botao_id"])
    interactive = mensagem.get("interactive") or {}
    if isinstance(interactive, dict):
        bid = (
            (interactive.get("button_reply") or {}).get("id")
            or (interactive.get("list_reply") or {}).get("id")
        )
        if bid:
            return str(bid)
    # Fallback: para mensagens interativas o text field contém o button_id
    if mensagem.get("type") == "interactive":
        text = str(mensagem.get("text") or "")
        if text in ("confirmar_presenca", "remarcar_consulta"):
            return text
    return None


async def _handle_confirmar_presenca(state: dict[str, Any], phone: str) -> tuple[list[Mensagem], str]:
    """Processa clique em 'Confirmar presenca': marca no Dietbox e limpa Redis."""
    result = await call_tool("marcar_confirmacao_dietbox", {"telefone": phone})
    if not result.sucesso:
        logger.warning("Falha ao marcar confirmacao no Dietbox para %s: %s", phone, result.erro)
    # Limpa pendencia de follow-up no Redis
    try:
        from app.conversation.scheduler import limpar_confirmacao_pendente
        await limpar_confirmacao_pendente(phone)
    except Exception as exc:
        logger.warning("Falha ao limpar Redis de confirmacao: %s", exc)
    state.setdefault("confirmacao", {})["status"] = "confirmada"
    return [Mensagem(tipo="texto", conteudo="Confirmado então! Obrigadaaa 💚😉")], "confirmacao_concluida"


def _intencao_remarcacao(texto: str) -> bool:
    n = _norm_text(texto)
    termos = ("remarcar", "mudar horario", "alterar horario", "trocar horario", "preciso remarcar", "preciso mudar", "preciso remarcar 📅")
    return any(t in n for t in termos)


def _intencao_cancelamento(texto: str) -> bool:
    n = _norm_text(texto)
    return any(t in n for t in ("cancelar", "cancelamento", "desmarcar", "quero cancelar"))


def _ativar_fluxo_por_intencao(state: dict[str, Any], mensagem: dict[str, Any]) -> None:
    texto = _texto_mensagem(mensagem)
    estado = state.get("estado")
    if estado == "inicio":
        if _intencao_cancelamento(texto):
            state["fluxo_id"] = CANCELAMENTO_ID
            state["estado"] = "cancelamento_identificacao"
        elif _intencao_remarcacao(texto):
            state["fluxo_id"] = REMARCACAO_ID
            state["estado"] = "remarcacao_identificacao"
    elif estado in ("cancelamento_tentativa_retencao", "cancelamento_aguardando_decisao_final"):
        n = _norm_text(texto)
        if any(t in n for t in ("topo", "vamos", "pode ser", "sim", "ok", "remarcar", "segunda", "terca", "terça", "quarta", "quinta", "sexta", "manha", "tarde", "noite")):
            state["fluxo_id"] = REMARCACAO_ID
            state["estado"] = "remarcacao_oferecendo_seguranca"


def _deve_disparar_on_enter(acao: AcaoAutorizada, target: str | None) -> bool:
    if not target:
        return False
    return not (acao.mensagens or acao.mensagens_a_enviar)


def _acao_on_enter_custom(state: dict[str, Any], estado: str) -> AcaoAutorizada | None:
    cd = state.get("collected_data") or {}
    if estado == "oferecendo_upsell":
        plano = cd.get("plano")
        destino = {"unica": "com_retorno", "com_retorno": "ouro", "ouro": "premium"}.get(str(plano))
        if not destino:
            return AcaoAutorizada(tipo=TipoAcao.enviar_mensagem, proximo_estado="aguardando_modalidade")
        origem_cfg = config.get_plano(str(plano))
        destino_cfg = config.get_plano(destino)
        modalidade = cd.get("modalidade") or "presencial"
        origem_val = origem_cfg.valores.pix_online if modalidade == "online" else origem_cfg.valores.pix_presencial
        dest_val = destino_cfg.valores.pix_online if modalidade == "online" else destino_cfg.valores.pix_presencial
        diff = dest_val - origem_val
        if plano == "unica":
            texto = (
                "Ótima escolha! Posso te dar uma dica rápida antes de confirmar? 💚\n\n"
                f"Por +R${diff:.0f}, você sobe para o {destino_cfg.nome_publico}: "
                "1 consulta + 1 retorno em 30 dias. Isso dá mais segurança para ajustar o plano depois da primeira fase.\n\n"
                "Quer manter a Consulta Única ou prefere o Com Retorno?"
            )
        elif plano == "com_retorno":
            texto = (
                "Ótima escolha! Posso te mostrar uma opção com mais acompanhamento? 💚\n\n"
                f"Por +R${diff:.0f}, você sobe para o {destino_cfg.nome_publico}: "
                "3 consultas em 130 dias, com a Lilly inclusa para dar mais suporte entre as consultas.\n\n"
                "Quer manter o Com Retorno ou prefere o Ouro?"
            )
        else:
            origem_por_consulta = origem_val / max(int(origem_cfg.consultas or 1), 1)
            dest_por_consulta = dest_val / max(int(destino_cfg.consultas or 1), 1)
            texto = (
                "Ótima escolha! Antes de confirmar, vale comparar com o Premium 💚\n\n"
                f"Por +R${diff:.0f}, você sobe para o {destino_cfg.nome_publico}: "
                "6 consultas em 270 dias, com Lilly e encontros coletivos.\n\n"
                f"Além de ser um acompanhamento bem mais longo, o valor por consulta fica menor: "
                f"aprox. R${origem_por_consulta:.0f} no Ouro vs. R${dest_por_consulta:.0f} no Premium.\n\n"
                "Quer manter o Ouro ou prefere o Premium?"
            )
        return AcaoAutorizada(
            tipo=TipoAcao.enviar_mensagem,
            mensagens=[Mensagem(tipo="botoes", conteudo=texto, botoes=[
                {"id": "upsell_aceitar", "label": f"Quero {destino_cfg.nome_publico}"},  # type: ignore[list-item]
                {"id": "upsell_recusar", "label": "Manter escolha"},  # type: ignore[list-item]
            ])],
            proximo_estado="oferecendo_upsell",
        )
    if estado == "confirmacao_final":
        return _confirmacao_final_acao(state)
    return None


def _confirmacao_final_acao(state: dict[str, Any]) -> AcaoAutorizada:
    cd = state.get("collected_data") or {}
    modalidade = cd.get("modalidade") or "presencial"
    ctx = _contexto_template(state)
    base = (
        f"{ctx.get('primeiro_nome') or 'Seu agendamento'}, sua consulta foi confirmada com sucesso!\n\n"
        f"Data e hora: {ctx.get('data_completa') or ''} às {ctx.get('hora') or ''}\n"
    )
    mensagens = [Mensagem(tipo="texto", conteudo=base)]
    if modalidade == "online":
        mensagens.extend([
            Mensagem(tipo="imagem", arquivo="COMO-SE-PREPARAR---ONLINE.jpg"),
            Mensagem(tipo="pdf", arquivo="Guia - Circunferências Corporais - Mulheres.pdf"),
            Mensagem(tipo="texto", conteudo="A consulta online será por videochamada no WhatsApp. Envie as fotos e medidas antes da consulta, por favor."),
        ])
    else:
        mensagens.extend([
            Mensagem(tipo="texto", conteudo="Local: Aura Clinic & Beauty - Rua Melo Franco, 204/Sala 103, Jardim da Glória, Vespasiano."),
            Mensagem(tipo="imagem", arquivo="COMO-SE-PREPARAR---presencial.jpg"),
        ])
    return AcaoAutorizada(tipo=TipoAcao.enviar_mensagem, mensagens=mensagens, proximo_estado="concluido")


async def _mensagens_on_enter(state: dict[str, Any], estado: str) -> tuple[list[Mensagem], str | None]:
    fluxo_id = state.get("fluxo_id") or AGENDAMENTO_ID
    custom = _acao_on_enter_custom(state, estado)
    if custom:
        msgs = await response_writer.escrever_async(custom, _contexto_template(state))
        return msgs, custom.proximo_estado
    if estado == "aguardando_pagamento_cartao":
        cd = state.get("collected_data") or {}
        result = await call_tool(
            "gerar_link_pagamento",
            {
                "plano": cd.get("plano") or "ouro",
                "modalidade": cd.get("modalidade") or "presencial",
                "phone_hash": state.get("phone_hash") or "",
            },
        )
        url = result.dados.get("url") if result.sucesso else None
        if url:
            state["link_pagamento"] = result.dados
            return [
                Mensagem(
                    tipo="texto",
                    conteudo=f"Segue o link: {url}\n\nParcelamento disponível. Após o pagamento, te confirmo aqui.",
                )
            ], None
        return [
            Mensagem(
                tipo="texto",
                conteudo="Não consegui gerar o link agora. Quer seguir por PIX para garantir o horário?",
            )
        ], "aguardando_forma_pagamento"
    on_enter = state_machine.on_enter_estado(fluxo_id, estado)
    if not on_enter:
        return [], None
    msgs = await response_writer.escrever_async(on_enter, _contexto_template(state))
    return msgs, on_enter.proximo_estado


async def _executar_consultar_slots(state: dict[str, Any]) -> tuple[list[Mensagem], str]:
    cd = state["collected_data"]
    result = await call_tool(
        "consultar_slots",
        {
            "modalidade": cd.get("modalidade") or "presencial",
            "preferencia": cd.get("preferencia_horario") or {},
            "excluir_slots": state.get("slots_rejeitados") or [],
            "max_resultados": 3,
        },
    )
    dados = result.dados if result.sucesso else {"slots": [], "slots_count": 0, "match_exato": False}
    slots = dados.get("slots") or []
    state["last_slots_offered"] = slots[:3]
    state["slots_pool"] = slots
    if not slots:
        return [Mensagem(tipo="texto", conteudo="No momento não tenho horários disponíveis nesse período. Quer que eu olhe outro horário?")], "aguardando_preferencia_horario"
    intro = "Encontrei essas opções:" if dados.get("match_exato") else "Não tenho exatamente esse horário, mas tenho:"
    botoes = [{"id": f"slot_{i}", "label": _slot_label(s)[:20]} for i, s in enumerate(slots[:3], start=1)]
    return [Mensagem(tipo="botoes", conteudo=f"{intro}\n\nQual prefere?", botoes=botoes)], "aguardando_escolha_slot"  # type: ignore[arg-type]


async def _executar_pagamento_pix(state: dict[str, Any], mensagem: dict[str, Any], entities: dict[str, Any]) -> tuple[list[Mensagem], str]:
    cd = state["collected_data"]
    valor_total = _valor_total(state)
    valor_sinal = round(valor_total * 0.5, 2)
    valor_pago = entities.get("valor_pago")
    image_bytes = mensagem.get("image_bytes") or mensagem.get("bytes") or b""
    mime_type = mensagem.get("mime_type") or "image/jpeg"

    if valor_pago is None and image_bytes:
        result = await call_tool("analisar_comprovante", {
            "imagem_bytes": image_bytes,
            "mime_type": mime_type,
            "plano": cd.get("plano") or "ouro",
            "modalidade": cd.get("modalidade") or "presencial",
        })
        if result.sucesso:
            valor_pago = result.dados.get("valor")
    if valor_pago is None:
        return [Mensagem(tipo="texto", conteudo="Não consegui ler o comprovante. Pode me mandar a tela do PIX confirmado?")], "aguardando_pagamento_pix"

    valor_pago = float(valor_pago)
    state["collected_data"]["valor_pago_sinal"] = valor_pago
    if valor_pago < valor_sinal:
        falta = valor_sinal - valor_pago
        return [Mensagem(tipo="texto", conteudo=f"Recebi R$ {valor_pago:.2f}, mas o sinal mínimo é R$ {valor_sinal:.2f}. Pode mandar mais R$ {falta:.2f}?")], "aguardando_pagamento_pix"
    state["flags"]["pagamento_confirmado"] = True
    if valor_pago >= valor_total:
        state["flags"]["pago_integral"] = True
        return [Mensagem(tipo="texto", conteudo=f"Recebi pagamento integral de R$ {valor_pago:.2f}. Tudo quitado.")], "aguardando_cadastro"
    restante = valor_total - valor_pago
    return [Mensagem(tipo="texto", conteudo=f"Recebi seu sinal de R$ {valor_pago:.2f}. Falta R$ {restante:.2f} para acertar no dia da consulta.")], "aguardando_cadastro"


def _parse_data_nascimento(texto: str) -> tuple[str | None, bool]:
    match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", texto)
    if not match:
        return None, False
    dia, mes, ano_raw = int(match.group(1)), int(match.group(2)), int(match.group(3))
    ano = ano_raw + 2000 if ano_raw < 100 and ano_raw <= date.today().year % 100 else ano_raw
    if ano < 100:
        ano += 1900
    try:
        datetime.strptime(f"{dia:02d}/{mes:02d}/{ano}", "%d/%m/%Y")
    except ValueError:
        return None, True
    return f"{dia:02d}/{mes:02d}/{ano}", True


def _cadastro_missing(cd: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if len(str(cd.get("nome") or cd.get("nome_completo") or "").split()) < 2:
        missing.append("nome completo")
    if not cd.get("data_nascimento"):
        missing.append("data de nascimento")
    if not cd.get("email"):
        missing.append("e-mail")
    if not cd.get("whatsapp_contato"):
        missing.append("WhatsApp")
    return missing


async def _processar_cadastro_incremental(
    state: dict[str, Any],
    phone: str,
    texto: str,
    entidades: dict[str, Any],
) -> tuple[list[Mensagem], str] | None:
    cd = state.setdefault("collected_data", {})
    if not cd.get("whatsapp_contato"):
        cd["whatsapp_contato"] = phone

    data_nasc, viu_data = _parse_data_nascimento(texto)
    if viu_data and not data_nasc:
        return [
            Mensagem(
                tipo="texto",
                conteudo="A data de nascimento parece inválida. Pode mandar no formato DD/MM/AAAA?",
            )
        ], "aguardando_cadastro"
    if data_nasc:
        nasc = datetime.strptime(data_nasc, "%d/%m/%Y").date()
        idade = (date.today() - nasc).days // 365
        if idade < 16:
            state.setdefault("flags", {})["restricao_atendimento"] = "menor_16"
            return [
                Mensagem(
                    tipo="texto",
                    conteudo=(
                        "Infelizmente a Thaynara não realiza atendimento para menores de 16 anos no momento. "
                        "Vou avisar a equipe para te orientar por aqui."
                    ),
                )
            ], "concluido_escalado"
        cd["data_nascimento"] = data_nasc

    email = entidades.get("email")
    if email:
        cd["email"] = email
    elif any(t in _norm_text(texto) for t in ("arroba", "gmail", "hotmail", "email", "e-mail")):
        return [
            Mensagem(
                tipo="texto",
                conteudo="O e-mail parece inválido. Pode mandar no formato nome@dominio.com?",
            )
        ], "aguardando_cadastro"

    nome = entidades.get("nome_completo")
    if nome and len(str(nome).split()) >= 2:
        cd["nome"] = nome
        cd["nome_completo"] = nome

    whatsapp = entidades.get("whatsapp_extraido")
    if whatsapp:
        cd["whatsapp_contato"] = whatsapp

    missing = _cadastro_missing(cd)
    if not missing:
        if not (state.get("appointment") or {}).get("slot_escolhido"):
            return [
                Mensagem(
                    tipo="texto",
                    conteudo=(
                        "Cadastro anotado 💚 Agora falta escolher o horário da consulta. "
                        "Me fala qual período funciona melhor pra você?"
                    ),
                )
            ], "aguardando_preferencia_horario"
        return await _criar_agendamento_e_confirmar(state)

    if data_nasc or email or nome or whatsapp:
        faltantes = ", ".join(missing)
        return [Mensagem(tipo="texto", conteudo=f"Anotei 💚 Falta só: {faltantes}. Pode mandar?")], "aguardando_cadastro"

    return None


def _acao_bloqueio_cadastro_se_necessario(
    estado: str,
    interpretacao_texto: str,
    entidades: dict[str, Any],
) -> AcaoAutorizada | None:
    texto = interpretacao_texto.lower()
    idade = entidades.get("tem_idade")
    try:
        idade_num = int(idade) if idade is not None else None
    except (TypeError, ValueError):
        idade_num = None

    if estado != "aguardando_cadastro":
        return None
    # Usa re.search com \b para evitar falso positivo: "gravida" é substring
    # de "gravidade", então match simples bloquearia "qual a gravidade do caso?"
    _texto_norm = _norm_text(interpretacao_texto)
    _e_gestante = bool(re.search(r"\b(gravida|gestante|gestacao|gravidez)\b", _texto_norm))
    if idade_num is not None and idade_num < 16 or _e_gestante:
        return AcaoAutorizada(
            tipo=TipoAcao.escalar,
            mensagens=[
                Mensagem(
                    tipo="texto",
                    conteudo=(
                        "Infelizmente a Thaynara não realiza atendimento para gestantes "
                        "ou menores de 16 anos no momento. Vou avisar a equipe para te orientar por aqui."
                    ),
                )
            ],
            proximo_estado="concluido_escalado",
            dados={"action": "escalar_breno_silencioso"},
        )
    return None


async def _criar_agendamento_e_confirmar(state: dict[str, Any]) -> tuple[list[Mensagem], str]:
    # A execução real de criação no Dietbox fica para a tool de agendamento completa.
    # Nesta fase, o fluxo confirma após cadastro completo e pagamento confirmado.
    state["status"] = "concluido"
    state["appointment"].setdefault("id_agenda", "v2-pendente-dietbox")
    acao = _confirmacao_final_acao(state)
    msgs = await response_writer.escrever_async(acao, _contexto_template(state))
    return msgs, "concluido"


def _mensagem_consulta_atual(state: dict[str, Any]) -> str:
    ctx = _contexto_template(state)
    data = ctx.get("data_original") or ctx.get("data") or "a data combinada"
    hora = ctx.get("hora_original") or ctx.get("hora") or "o horário combinado"
    return f"{data} às {hora}"


def _aplicar_consulta_detectada(state: dict[str, Any], dados: dict[str, Any]) -> None:
    consulta = dict(dados.get("consulta_atual") or {})
    paciente = dados.get("paciente") or {}
    if "ja_remarcada" not in consulta:
        consulta["ja_remarcada"] = bool(dados.get("ja_remarcada"))
    state["appointment"]["consulta_atual"] = consulta
    state["tipo_remarcacao"] = dados.get("tipo_remarcacao")
    if paciente and not (state.get("collected_data") or {}).get("nome"):
        state["collected_data"]["nome"] = paciente.get("nome") or paciente.get("name")
    if consulta:
        state["collected_data"]["modalidade"] = consulta.get("modalidade") or state["collected_data"].get("modalidade")
        state["collected_data"]["plano"] = consulta.get("plano") or state["collected_data"].get("plano")


async def _identificar_consulta(state: dict[str, Any], fluxo_id: str, identificador: str | None = None) -> tuple[list[Mensagem], str]:
    result = await call_tool(
        "detectar_tipo_remarcacao",
        {"telefone": state.get("phone") or "", "identificador": identificador},
    )
    dados = result.dados if result.sucesso else {"tipo_remarcacao": "nao_localizado"}
    tipo = dados.get("tipo_remarcacao")

    if fluxo_id == REMARCACAO_ID:
        if tipo == "retorno":
            _aplicar_consulta_detectada(state, dados)
            consulta = _consulta_atual(state)
            if consulta.get("ja_remarcada") or int(state.get("remarcacoes_count") or 0) >= 1:
                texto = (
                    "Entendo, mas essa consulta já foi remarcada uma vez. "
                    f"Sua consulta segue marcada para {_mensagem_consulta_atual(state)}."
                )
                return [Mensagem(tipo="texto", conteudo=texto)], "remarcacao_concluida"
            return [Mensagem(tipo="texto", conteudo=_texto_seguranca_remarcacao(state))], "remarcacao_oferecendo_seguranca"
        if tipo == "sem_agendamento_confirmado":
            return [
                Mensagem(
                    tipo="botoes",
                    conteudo="Não encontrei uma consulta ativa pra você. Quer agendar uma nova consulta com a Thaynara?",
                    botoes=[
                        {"id": "sim_nova_consulta", "label": "Sim, agendar nova"},  # type: ignore[list-item]
                        {"id": "nao_obrigado", "label": "Não, obrigado"},  # type: ignore[list-item]
                    ],
                )
            ], "remarcacao_aguardando_decisao_nova_consulta"
        return [Mensagem(tipo="texto", conteudo="Oi! Pra eu localizar seu cadastro certinho, pode me mandar seu nome completo?")], "remarcacao_pedindo_nome_completo"

    if tipo == "retorno":
        _aplicar_consulta_detectada(state, dados)
        return [Mensagem(tipo="texto", conteudo=_texto_pedir_motivo_cancelamento(state))], "cancelamento_aguardando_motivo"
    if tipo == "sem_agendamento_confirmado":
        return [Mensagem(tipo="texto", conteudo="Não encontrei uma consulta ativa pra cancelar. Posso te ajudar com mais alguma coisa?")], "cancelamento_concluido"
    return [Mensagem(tipo="texto", conteudo="Não encontrei seu cadastro. Pode me mandar seu nome completo?")], "cancelamento_pedindo_nome"


def _texto_seguranca_remarcacao(state: dict[str, Any]) -> str:
    ctx = _contexto_template(state)
    return (
        f"Tudo bem, {ctx.get('primeiro_nome') or ''}! Podemos remarcar sim.\n\n"
        "Só queria te orientar que a agenda está bem cheia. Se você conseguir manter o horário atual, melhor para não prejudicar seu acompanhamento.\n\n"
        f"Sua consulta atual é {_mensagem_consulta_atual(state)}.\n\n"
        f"Caso realmente não consiga, consigo buscar opções até {ctx.get('data_limite')}. Quais dias e horários funcionam melhor?"
    )


def _texto_pedir_motivo_cancelamento(state: dict[str, Any]) -> str:
    ctx = _contexto_template(state)
    return (
        f"Entendi, {ctx.get('primeiro_nome') or ''}. Sua consulta atual é {_mensagem_consulta_atual(state)}.\n\n"
        "Antes de cancelar, pode me contar rapidinho o motivo? Assim consigo entender melhor pra ver se há algo que posso fazer."
    )


def _texto_retencao_cancelamento(state: dict[str, Any]) -> str:
    ctx = _contexto_template(state)
    return (
        f"Entendi, {ctx.get('primeiro_nome') or ''}.\n\n"
        f"Que tal remarcar em vez de cancelar? Consigo realocar dentro do prazo, até {ctx.get('data_limite')}.\n\n"
        "Topa? Me fala qual dia e horário funciona melhor pra você."
    )


def _slot_fora_janela(state: dict[str, Any], preferencia: dict[str, Any]) -> bool:
    texto = _norm_text(str(preferencia.get("descricao") or ""))
    if "semana que vem" in texto or "mes que vem" in texto or "mês que vem" in texto:
        return True
    return False


def _preferencia_from_texto(texto: str) -> dict[str, Any]:
    pref = _extrair_preferencia(texto)
    pref.setdefault("descricao", texto)
    return pref


async def _buscar_slots_remarcacao(state: dict[str, Any], preferencia: dict[str, Any]) -> tuple[list[Mensagem], str]:
    state["collected_data"]["preferencia_horario_nova"] = preferencia
    if _slot_fora_janela(state, preferencia):
        limite = _contexto_template(state).get("data_limite")
        return [Mensagem(tipo="texto", conteudo=f"Pra remarcação tenho disponibilidade até {limite}. Tem algum horário antes disso?")], "remarcacao_oferecendo_seguranca"

    result = await call_tool(
        "consultar_slots",
        {
            "modalidade": state["collected_data"].get("modalidade") or "presencial",
            "preferencia": preferencia,
            "janela_max_dias": 14,
            "excluir_slots": state.get("slots_rejeitados") or [],
            "max_resultados": 3,
        },
    )
    dados = result.dados if result.sucesso else {"slots": [], "slots_count": 0, "match_exato": False}
    slots = dados.get("slots") or []
    state["last_slots_offered"] = slots[:3]
    if not slots:
        await call_tool("escalar_breno_silencioso", {"contexto": {"fluxo": REMARCACAO_ID, "state": state}})
        return [Mensagem(tipo="texto", conteudo="No momento não tenho horários disponíveis dentro do prazo. Vou verificar com a equipe e já te respondo.")], "remarcacao_aguardando_breno"

    intro = "Encontrei essas opções dentro do prazo de remarcação:"
    botoes = [{"id": f"slot_{i}", "label": _slot_label(s)[:20]} for i, s in enumerate(slots[:3], start=1)]
    return [Mensagem(tipo="botoes", conteudo=f"{intro}\n\nQual prefere?", botoes=botoes)], "remarcacao_aguardando_escolha_slot"  # type: ignore[arg-type]


async def _executar_remarcacao(state: dict[str, Any], slot: dict[str, Any]) -> tuple[list[Mensagem], str]:
    consulta = _consulta_atual(state)
    if consulta.get("ja_remarcada") or int(state.get("remarcacoes_count") or 0) >= 1:
        return [Mensagem(tipo="texto", conteudo="Essa consulta já foi remarcada uma vez, então não consigo remarcar novamente.")], "remarcacao_concluida"

    state["appointment"]["slot_escolhido_novo"] = slot
    result = await call_tool(
        "remarcar_dietbox",
        {"id_agenda": consulta.get("id") or consulta.get("id_agenda"), "novo_slot": slot},
    )
    if not result.sucesso:
        await call_tool("escalar_breno_silencioso", {"contexto": {"fluxo": REMARCACAO_ID, "state": state, "erro": result.erro}})
        return [Mensagem(tipo="texto", conteudo="Estou finalizando sua remarcação, só um instante.")], "remarcacao_aguardando_breno"

    consulta["ja_remarcada"] = True
    state["appointment"]["consulta_atual"] = consulta
    state["remarcacoes_count"] = int(state.get("remarcacoes_count") or 0) + 1
    data, hora = _formatar_data_slot(slot)
    return [Mensagem(tipo="texto", conteudo=f"Fiz a alteração da consulta. Nova data: {data} às {hora}. Qualquer coisa estou à disposição!")], "remarcacao_concluida"


def _notificacao_cancelamento(state: dict[str, Any], silencioso: bool = False) -> str:
    cd = state.get("collected_data") or {}
    prefixo = "Cancelamento por silêncio" if silencioso else "Cancelamento"
    return (
        f"{prefixo} - {cd.get('nome') or 'paciente'}\n"
        f"Consulta cancelada: {_mensagem_consulta_atual(state)}\n"
        f"Modalidade: {cd.get('modalidade') or ''}\n"
        f"Plano: {cd.get('plano') or ''}\n"
        f"Motivo informado: {cd.get('motivo_cancelamento') or 'não informado'}"
    )


async def _executar_cancelamento(state: dict[str, Any], *, silencioso: bool = False) -> tuple[list[Mensagem], str]:
    consulta = _consulta_atual(state)
    result = await call_tool("cancelar_dietbox", {"id_agenda": consulta.get("id") or consulta.get("id_agenda")})
    if not result.sucesso:
        await call_tool("escalar_breno_silencioso", {"contexto": {"fluxo": CANCELAMENTO_ID, "state": state, "erro": result.erro}})
        return [Mensagem(tipo="texto", conteudo="Estou finalizando seu cancelamento, só um instante.")], "cancelamento_aguardando_breno"

    aviso = _notificacao_cancelamento(state, silencioso=silencioso)
    await call_tool("notificar_thaynara", {"mensagem": aviso})
    await call_tool("notificar_breno", {"mensagem": aviso})
    state["status"] = "concluido"
    if silencioso:
        return [], "cancelamento_concluido"
    return [Mensagem(tipo="texto", conteudo="Pronto! Sua consulta foi cancelada. Qualquer coisa, estou à disposição.")], "cancelamento_concluido"


async def _processar_remarcacao(state: dict[str, Any], mensagem: dict[str, Any]) -> tuple[list[Mensagem], str]:
    estado = state.get("estado") or "remarcacao_identificacao"
    texto = _texto_mensagem(mensagem)
    n = _norm_text(texto)

    if estado == "remarcacao_identificacao":
        return await _identificar_consulta(state, REMARCACAO_ID)
    if estado == "remarcacao_pedindo_nome_completo":
        nome = _extrair_nome(texto)
        if nome and len(nome.split()) >= 2:
            state["collected_data"]["nome"] = nome
            return await _identificar_consulta(state, REMARCACAO_ID, identificador=nome)
        return [Mensagem(tipo="texto", conteudo="Pra eu localizar seu cadastro, preciso do nome e sobrenome.")], estado
    if estado == "remarcacao_aguardando_decisao_nova_consulta":
        if any(t in n for t in ("sim", "quero", "agendar", "nova")):
            state["fluxo_id"] = AGENDAMENTO_ID
            state["estado"] = "inicio"
            return [Mensagem(tipo="texto", conteudo="Claro. Vamos começar uma nova consulta.")], "inicio"
        return [Mensagem(tipo="texto", conteudo="Tudo bem! Quando quiser agendar, é só me chamar.")], "remarcacao_concluida"
    if estado == "remarcacao_oferecendo_seguranca":
        if any(t in n for t in ("vou manter", "fico mesmo", "mantenho", "deixa como esta", "deixa como está")):
            return [Mensagem(tipo="texto", conteudo=f"Que ótimo! Sua consulta segue marcada para {_mensagem_consulta_atual(state)}.")], "remarcacao_concluida"
        pref = _preferencia_from_texto(texto)
        if pref.get("tem_dia") == "sexta" and pref.get("turno_extraido") == "noite":
            return [Mensagem(tipo="texto", conteudo="Sexta à noite a Thaynara não atende. Posso te oferecer sexta de tarde ou noite de segunda a quinta.")], estado
        if pref.get("tem_dia") in ("sábado", "sabado", "domingo"):
            return [Mensagem(tipo="texto", conteudo="Sábado e domingo a Thaynara não atende. Tem algum dia de segunda a sexta que funciona?")], estado
        return await _buscar_slots_remarcacao(state, pref)
    if estado == "remarcacao_oferecendo_slots":
        pref = state["collected_data"].get("preferencia_horario_nova") or _preferencia_from_texto(texto)
        return await _buscar_slots_remarcacao(state, pref)
    if estado == "remarcacao_aguardando_escolha_slot":
        if any(t in n for t in ("outra", "outro", "nao serve", "não serve", "mais")):
            state["slots_rejeitados"] = list(state.get("slots_rejeitados") or []) + list(state.get("last_slots_offered") or [])
            state["last_slots_offered"] = []
            state["rodada_negociacao"] = int(state.get("rodada_negociacao") or 0) + 1
            pref = _preferencia_from_texto(texto)
            return await _buscar_slots_remarcacao(state, pref)
        slot = _slot_por_id(state, texto.strip()) or _slot_por_id(state, mensagem.get("botao_id")) or _slot_por_id(state, "slot_1")
        return await _executar_remarcacao(state, slot or {})
    if estado == "remarcacao_executando":
        slot = state["appointment"].get("slot_escolhido_novo") or {}
        return await _executar_remarcacao(state, slot)
    return [Mensagem(tipo="texto", conteudo="Sua remarcação está encerrada. Qualquer coisa estou à disposição.")], "remarcacao_concluida"


async def _processar_cancelamento(state: dict[str, Any], mensagem: dict[str, Any]) -> tuple[list[Mensagem], str]:
    estado = state.get("estado") or "cancelamento_identificacao"
    texto = _texto_mensagem(mensagem)
    n = _norm_text(texto)

    if estado == "cancelamento_identificacao":
        return await _identificar_consulta(state, CANCELAMENTO_ID)
    if estado == "cancelamento_pedindo_nome":
        nome = _extrair_nome(texto)
        if nome and len(nome.split()) >= 2:
            state["collected_data"]["nome"] = nome
            return await _identificar_consulta(state, CANCELAMENTO_ID, identificador=nome)
        return [Mensagem(tipo="texto", conteudo="Pra localizar seu cadastro, preciso do nome e sobrenome.")], estado
    if estado == "cancelamento_aguardando_motivo":
        if len(texto.strip()) < 2:
            return [Mensagem(tipo="texto", conteudo="Pode me contar rapidinho o motivo do cancelamento?")], estado
        state["collected_data"]["motivo_cancelamento"] = texto.strip()
        return [Mensagem(tipo="texto", conteudo=_texto_retencao_cancelamento(state))], "cancelamento_tentativa_retencao"
    if estado in ("cancelamento_tentativa_retencao", "cancelamento_aguardando_decisao_final"):
        if "24h" in n or "sem resposta" in n:
            return await _executar_cancelamento(state, silencioso=True)
        if any(t in n for t in ("cancelar mesmo", "prefiro cancelar", "nao quero remarcar", "não quero remarcar", "cancela")):
            return await _executar_cancelamento(state)
        if any(t in n for t in ("vou manter", "fico mesmo", "vou tentar")):
            return [Mensagem(tipo="texto", conteudo=f"Que ótimo! Sua consulta segue marcada para {_mensagem_consulta_atual(state)}.")], "cancelamento_concluido"
        if any(t in n for t in ("vou pensar", "vou ver", "depois", "pensar")):
            return [Mensagem(tipo="texto", conteudo="Claro, sem pressa. Sua consulta segue marcada por enquanto. Quando decidir, me avisa.")], "cancelamento_aguardando_decisao_final"
        state["fluxo_id"] = REMARCACAO_ID
        state["estado"] = "remarcacao_oferecendo_seguranca"
        pref = _preferencia_from_texto(texto)
        return await _buscar_slots_remarcacao(state, pref)
    if estado == "cancelamento_executando":
        return await _executar_cancelamento(state)
    if estado == "cancelamento_executando_silencioso":
        return await _executar_cancelamento(state, silencioso=True)
    return [Mensagem(tipo="texto", conteudo="Cancelamento encerrado. Qualquer coisa estou à disposição.")], "cancelamento_concluido"


async def _log_metric(payload: dict[str, Any]) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        logger.warning("Falha ao registrar métrica v2: %s", exc)


def _response_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def _is_fallback_like(text: str) -> bool:
    n = _norm_text(text)
    termos = (
        "nao entendi",
        "entender certinho",
        "mandar de outro jeito",
        "mais detalhes",
        "pode escrever",
        "pode me mandar",
    )
    return any(t in n for t in termos)


def _is_retomada_after_handoff(text: str) -> bool:
    n = _norm_text(text)
    if not n:
        return False
    saudacoes = {
        "oi",
        "ola",
        "olá",
        "bom dia",
        "boa tarde",
        "boa noite",
        "tudo bem",
    }
    if n in saudacoes:
        return True
    if any(n.startswith(f"{s} ") for s in saudacoes):
        return True
    termos_fluxo = (
        "agendar",
        "marcar",
        "consulta",
        "remarcar",
        "cancelar",
        "valor",
        "valores",
        "preco",
        "preço",
        "plano",
        "planos",
        "presencial",
        "online",
    )
    return any(t in n for t in termos_fluxo)


async def _aplicar_controle_loop_fallback(
    *,
    state: dict[str, Any],
    phone: str,
    mensagens: list[Mensagem],
    is_fallback: bool,
    estado_antes: str,
    ultima_mensagem: str,
    tools_chamadas: list[str],
) -> list[Mensagem]:
    if not is_fallback:
        state["fallback_streak"] = 0
        state["last_response_hash"] = None
        return mensagens

    resp_text = "\n".join(m.conteudo for m in mensagens if m.conteudo).strip()
    resp_hash = _response_hash(resp_text)
    streak = int(state.get("fallback_streak") or 0) + 1
    repeated = state.get("last_response_hash") == resp_hash
    state["fallback_streak"] = streak
    state["last_response_hash"] = resp_hash

    fora_contexto_count = int(state.get("fora_contexto_count") or 0)
    if (streak < 2 and fora_contexto_count < 2) or not (repeated or _is_fallback_like(resp_text)):
        return mensagens

    motivo = "fora_contexto_consecutivo" if fora_contexto_count >= 2 else "loop_fallback_2x"
    tools_chamadas.append("escalar_breno_silencioso")
    await call_tool(
        "escalar_breno_silencioso",
        {
            "contexto": {
                "motivo": motivo,
                "reason": "loop_fallback_2x",
                "count": max(streak, fora_contexto_count),
                "telefone": phone,
                "estado": estado_antes,
                "ultima_mensagem": ultima_mensagem,
                "resposta_repetida": resp_text,
            }
        },
    )
    state["fallback_streak"] = 0
    state["last_response_hash"] = None
    state["estado"] = "aguardando_orientacao_breno"
    await _log_metric(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": state.get("phone_hash"),
            "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
            "estado_antes": estado_antes,
            "estado_depois": state.get("estado"),
            "tools_chamadas": ["escalar_breno_silencioso"],
            "evento": "fallback_loop_escalado",
            "erro": None,
        }
    )
    return [
        Mensagem(
            tipo="texto",
            conteudo="Deixa eu chamar alguém da equipe pra te dar atenção especial 💚",
        )
    ]


async def _acquire_processing_lock(phone: str) -> bool:
    return await acquire_processing_lock(phone)


async def _release_processing_lock(phone: str) -> None:
    await release_processing_lock(phone)


async def processar_turno(phone: str, mensagem: dict[str, Any]) -> ResultadoTurno:
    started = time.perf_counter()
    phone_hash = _phone_hash(phone)
    acquired = await _acquire_processing_lock(phone)
    if not acquired:
        logger.info("Já existe processamento ativo para %s; turno ignorado nesta janela", phone[-4:])
        await _log_metric(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phone_hash": phone_hash,
                "evento": "processing_lock_busy",
                "duracao_ms": int((time.perf_counter() - started) * 1000),
                "erro": None,
            }
        )
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=[],
            novo_estado=None,
            fluxo_id=AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        return await _processar_turno_locked(phone, mensagem)
    finally:
        await _release_processing_lock(phone)


async def _processar_turno_locked(phone: str, mensagem: dict[str, Any]) -> ResultadoTurno:
    started = time.perf_counter()
    phone_hash = _phone_hash(phone)
    loaded_state = await load_state(phone_hash, phone)
    estado_original = loaded_state.get("estado")
    loaded_state = await maybe_reset_stale_state(phone, loaded_state)
    state = _ensure_v2_state(loaded_state, phone)
    state["phone_hash"] = phone_hash
    state["last_message_at"] = datetime.now(timezone.utc).isoformat()

    # ── IDENTIFICAÇÃO DE PACIENTE (base CSV Dietbox) ───────────────────────────
    if not (state.get("flags") or {}).get("paciente_identificado"):
        try:
            from app.conversation.patient_lookup import identificar_paciente as _lookup
            _paciente = await _lookup(phone, get_state_redis())
            if _paciente:
                cd = state.setdefault("collected_data", {})
                if not cd.get("nome"):
                    cd["nome"] = _paciente["nome"]
                fl = state.setdefault("flags", {})
                fl["paciente_identificado"] = True
                fl["paciente_origem"] = "csv_dietbox"
                fl["primeiro_nome_csv"] = _paciente.get("primeiro_nome", "")
        except Exception as _exc:
            logger.warning("Falha na identificacao de paciente: %s", _exc)
    if state.get("reset_reason") == "inatividade" and estado_original != state.get("estado"):
        await _log_metric(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phone_hash": phone_hash,
                "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
                "estado_antes": estado_original,
                "estado_depois": state.get("estado"),
                "evento": "state_reset_inactivity",
                "erro": None,
            }
        )

    # ── COMANDOS INTERNOS (Fluxo 8) ───────────────────────────────────────────
    try:
        from app.conversation.command_processor import processar_comando_interno
        cmd_result = await processar_comando_interno(phone, mensagem, state)
        if cmd_result.processado:
            # Não salvamos estado de conversa para operadores internos
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=cmd_result.mensagens,
                novo_estado=state.get("estado"),
                fluxo_id="comando_interno",
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )
    except Exception as exc:
        logger.exception("Erro no processador de comandos internos: %s", exc)

    # ── MÍDIAS NÃO TEXTUAIS (Fluxo 9) ────────────────────────────────────────
    msg_type = str(mensagem.get("type") or "")

    # ── AGRESSÃO / AMEAÇA (interceptador global) ─────────────────────────────
    texto_entrada = _texto_mensagem(mensagem)

    if state.get("estado") == "aguardando_orientacao_breno":
        estado_antes_handoff = state.get("estado")
        if msg_type in ("", "text", "conversation") and _is_retomada_after_handoff(texto_entrada):
            nome_preservado = (state.get("collected_data") or {}).get("nome")
            state = create_state(phone_hash, phone)
            if nome_preservado:
                state["collected_data"]["nome"] = nome_preservado
            state["last_message_at"] = datetime.now(timezone.utc).isoformat()
            state["reset_reason"] = "retomada_apos_handoff"
            enter_msgs, prox = await _mensagens_on_enter(state, "inicio")
            state["estado"] = prox or "aguardando_nome"
            add_message(state, "user", texto_entrada)
            add_message(state, "assistant", "\n".join(m.conteudo for m in enter_msgs if m.conteudo))
            await save_state(phone_hash, state)
            await _log_metric({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phone_hash": phone_hash,
                "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
                "estado_antes": estado_antes_handoff,
                "estado_depois": state.get("estado"),
                "tools_chamadas": [],
                "duracao_ms": int((time.perf_counter() - started) * 1000),
                "erro": None,
                "evento": "handoff_retomado_pelo_paciente",
            })
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=enter_msgs,
                novo_estado=state.get("estado"),
                fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

        msgs_handoff = [
            Mensagem(
                tipo="texto",
                conteudo="A equipe já foi chamada e vai te responder por aqui, tá? 💚",
            )
        ]
        add_message(state, "user", texto_entrada or "[mensagem]")
        add_message(state, "assistant", msgs_handoff[0].conteudo)
        state["fallback_streak"] = 0
        state["last_response_hash"] = None
        await save_state(phone_hash, state)
        await _log_metric({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": phone_hash,
            "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
            "estado_antes": estado_antes_handoff,
            "estado_depois": state.get("estado"),
            "tools_chamadas": [],
            "duracao_ms": int((time.perf_counter() - started) * 1000),
            "erro": None,
            "evento": "handoff_mensagem_registrada_com_espera",
        })
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=msgs_handoff,
            novo_estado=state.get("estado"),
            fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    if msg_type in ("", "text", "conversation") and _is_aggressive_text(texto_entrada):
        estado_antes_agressao = state.get("estado", "inicio")
        msgs, aggression_tools = await _handle_aggression(state, phone, texto_entrada, estado_antes_agressao)
        add_message(state, "user", texto_entrada)
        add_message(state, "assistant", "\n".join(m.conteudo for m in msgs if m.conteudo))
        await save_state(phone_hash, state)
        await _log_metric({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": phone_hash,
            "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
            "estado_antes": estado_antes_agressao,
            "estado_depois": state.get("estado"),
            "tools_chamadas": aggression_tools,
            "duracao_ms": int((time.perf_counter() - started) * 1000),
            "erro": None,
            "evento": "agressao_interceptada",
        })
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=msgs,
            novo_estado=state.get("estado"),
            fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    if msg_type in ("", "text", "conversation"):
        estado_antes_restricao = state.get("estado", "inicio")
        restriction = await _handle_restriction(state, phone, texto_entrada, estado_antes_restricao)
        if restriction is not None:
            msgs, novo_estado, restriction_tools = restriction
            add_message(state, "user", texto_entrada)
            add_message(state, "assistant", "\n".join(m.conteudo for m in msgs if m.conteudo))
            await save_state(phone_hash, state)
            await _log_metric({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "phone_hash": phone_hash,
                "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
                "estado_antes": estado_antes_restricao,
                "estado_depois": novo_estado,
                "tools_chamadas": restriction_tools,
                "duracao_ms": int((time.perf_counter() - started) * 1000),
                "erro": None,
                "evento": "restricao_atendimento",
            })
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=msgs,
                novo_estado=novo_estado,
                fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

    if msg_type in ("", "text", "conversation") and _is_bioimpedancia_question(texto_entrada):
        estado_antes_duvida = state.get("estado", "inicio")
        resposta_bioimpedancia = _bioimpedancia_answer()
        status_batched = (
            _mensagens_bioimpedancia_com_status(state, texto_entrada, resposta_bioimpedancia)
            if estado_antes_duvida == "aguardando_status_paciente"
            else None
        )
        if status_batched is not None:
            msgs, novo_estado_duvida = status_batched
            state["estado"] = novo_estado_duvida
        else:
            msgs = _mensagens_retomada_duvida_operacional(
                state,
                estado_antes_duvida,
                resposta_bioimpedancia,
            )
            if estado_antes_duvida == "inicio":
                state["estado"] = "aguardando_nome"
        add_message(state, "user", texto_entrada)
        add_message(state, "assistant", "\n".join(m.conteudo for m in msgs if m.conteudo))
        await save_state(phone_hash, state)
        await _log_metric({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": phone_hash,
            "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
            "estado_antes": estado_antes_duvida,
            "estado_depois": state.get("estado"),
            "tools_chamadas": [],
            "duracao_ms": int((time.perf_counter() - started) * 1000),
            "erro": None,
            "evento": "duvida_operacional_bioimpedancia",
        })
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=msgs,
            novo_estado=state.get("estado"),
            fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    # Localização → resposta determinística
    if msg_type == "location":
        msgs = [Mensagem(
            tipo="texto",
            conteudo=(
                "Nossa clínica fica em: Aura Clinic & Beauty — Rua Melo Franco, 204/Sala 103, "
                "Jardim da Glória, Vespasiano/MG.\n\nPosso te ajudar com mais alguma coisa?"
            ),
        )]
        add_message(state, "user", "[localização]")
        add_message(state, "assistant", msgs[0].conteudo)
        await save_state(phone_hash, state)
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=msgs,
            novo_estado=state.get("estado"),
            fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    # Vídeo → resposta determinística
    if msg_type == "video":
        msgs = [Mensagem(
            tipo="texto",
            conteudo="Não consigo processar vídeos por aqui 😊 Pode me mandar uma mensagem de texto?",
        )]
        add_message(state, "user", "[vídeo]")
        add_message(state, "assistant", msgs[0].conteudo)
        await save_state(phone_hash, state)
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=msgs,
            novo_estado=state.get("estado"),
            fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )

    # Áudio → transcrever via Gemini e continuar como texto
    if msg_type == "audio":
        audio_bytes: bytes = mensagem.get("audio_bytes") or mensagem.get("bytes") or b""
        mime_type_audio: str = mensagem.get("mime_type") or "audio/ogg"
        media_id_audio: str = str(mensagem.get("media_id") or "")

        if not audio_bytes and media_id_audio:
            try:
                import asyncio
                from app.media_handler import download_media
                loop = asyncio.get_event_loop()
                audio_bytes, mime_type_audio = await loop.run_in_executor(
                    None, lambda: download_media(media_id_audio)
                )
            except Exception as exc:
                logger.warning("Falha ao baixar áudio media_id=%s: %s", media_id_audio, exc)

        if audio_bytes:
            audio_result = await call_tool(
                "transcrever_audio", {"audio_bytes": audio_bytes, "mime_type": mime_type_audio}
            )
            if audio_result.sucesso:
                transcricao = str(audio_result.dados.get("transcricao") or "").strip()
                if transcricao:
                    # Injeta a transcrição e continua o fluxo como mensagem de texto
                    mensagem = dict(mensagem)
                    mensagem["type"] = "text"
                    mensagem["text"] = transcricao
                    mensagem["_transcrito_de_audio"] = True
                    msg_type = "text"
                    logger.info("Áudio transcrito: %r", transcricao[:80])
                else:
                    msgs = [Mensagem(tipo="texto", conteudo="Não consegui entender o áudio. Pode me mandar em texto?")]
                    add_message(state, "user", "[áudio]")
                    add_message(state, "assistant", msgs[0].conteudo)
                    await save_state(phone_hash, state)
                    return ResultadoTurno(
                        sucesso=True,
                        mensagens_enviadas=msgs,
                        novo_estado=state.get("estado"),
                        fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                        duracao_ms=int((time.perf_counter() - started) * 1000),
                    )
            else:
                msgs = [Mensagem(tipo="texto", conteudo="Não consegui processar o áudio. Pode me mandar em texto?")]
                add_message(state, "user", "[áudio]")
                add_message(state, "assistant", msgs[0].conteudo)
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=msgs,
                    novo_estado=state.get("estado"),
                    fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )
        else:
            msgs = [Mensagem(tipo="texto", conteudo="Recebi seu áudio mas não consegui abrir. Pode escrever?")]
            add_message(state, "user", "[áudio]")
            add_message(state, "assistant", msgs[0].conteudo)
            await save_state(phone_hash, state)
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=msgs,
                novo_estado=state.get("estado"),
                fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

    # ── INTERCEPTADOR DE IMAGENS / STICKERS ───────────────────────────────────
    if msg_type in ("image", "sticker", "document"):
        try:
            from app.conversation.interceptors.image_interceptor import interceptar_imagem
            intercept = await interceptar_imagem(mensagem, state)
            if intercept.interceptado:
                for path, value in (intercept.salvar_no_estado or {}).items():
                    _set_path(state, path, value)
                if intercept.proximo_estado:
                    state["estado"] = intercept.proximo_estado
                mensagens = [
                    Mensagem(tipo=m.get("tipo", "texto"), conteudo=m.get("conteudo", ""))
                    for m in intercept.mensagens
                ]
                add_message(state, "user", _texto_mensagem(mensagem))
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=mensagens,
                    novo_estado=state.get("estado"),
                    fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )
        except Exception as exc:
            logger.exception("Erro no interceptador de imagem: %s", exc)

    # ── BOTÕES GLOBAIS DE CONFIRMAÇÃO DE PRESENÇA ────────────────────────────
    botao_id_rapido = _get_botao_id(mensagem)
    if botao_id_rapido == "confirmar_presenca":
        try:
            msgs, novo_estado = await _handle_confirmar_presenca(state, phone)
            state["estado"] = novo_estado
            add_message(state, "user", _texto_mensagem(mensagem))
            add_message(state, "assistant", "\n".join(m.conteudo for m in msgs if m.conteudo))
            await save_state(phone_hash, state)
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=msgs,
                novo_estado=novo_estado,
                fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID,
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:
            logger.exception("Erro ao processar confirmar_presenca: %s", exc)

    if botao_id_rapido == "remarcar_consulta":
        state["fluxo_id"] = REMARCACAO_ID
        state["estado"] = "remarcacao_identificacao"
        try:
            from app.conversation.scheduler import limpar_confirmacao_pendente
            await limpar_confirmacao_pendente(phone)
        except Exception:
            pass

    _ativar_fluxo_por_intencao(state, mensagem)
    estado_antes = state.get("estado", "inicio")
    fluxo_ativo = state.get("fluxo_id") or AGENDAMENTO_ID
    mensagens: list[Mensagem] = []
    tools_chamadas: list[str] = []
    erro: str | None = None

    try:
        if fluxo_ativo in (REMARCACAO_ID, CANCELAMENTO_ID):
            if fluxo_ativo == REMARCACAO_ID:
                mensagens, target = await _processar_remarcacao(state, mensagem)
            else:
                mensagens, target = await _processar_cancelamento(state, mensagem)
            state["estado"] = target
            add_message(state, "user", _texto_mensagem(mensagem))
            add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
            await save_state(phone_hash, state)
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=mensagens,
                novo_estado=state["estado"],
                fluxo_id=state.get("fluxo_id"),
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )

        if estado_antes == "inicio":
            if state.get("flags", {}).get("paciente_identificado"):
                # Paciente da base CSV — saudacao personalizada, sem perguntar nome
                _primeiro = state["flags"].get("primeiro_nome_csv") or _primeiro_nome(state)
                _hora = datetime.now(timezone(timedelta(hours=-3))).hour
                _saudacao = "Bom dia" if _hora < 12 else ("Boa tarde" if _hora < 18 else "Boa noite")
                msg_bv = Mensagem(tipo="texto", conteudo=f"{_saudacao}, {_primeiro}! 💚\n\nComo posso te ajudar hoje?")
                mensagens.append(msg_bv)
                state["collected_data"]["status_paciente"] = "retorno"
                state["estado"] = "aguardando_status_paciente"
                add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
                add_message(state, "assistant", msg_bv.conteudo)
                await save_state(phone_hash, state)
                return ResultadoTurno(sucesso=True, mensagens_enviadas=mensagens, novo_estado=state["estado"], fluxo_id=AGENDAMENTO_ID, duracao_ms=int((time.perf_counter() - started) * 1000))

            texto_inicio = _texto_mensagem(mensagem)
            nome_inicio = _extrair_nome_primeira_mensagem(texto_inicio)
            status_inicio = _status_paciente_from_text(texto_inicio)
            objetivo_inicio = _objetivo_from_text(texto_inicio)
            if nome_inicio and status_inicio:
                state["collected_data"]["nome"] = nome_inicio
                state["collected_data"]["status_paciente"] = status_inicio
                if status_inicio == "novo" and objetivo_inicio:
                    state["collected_data"]["objetivo"] = objetivo_inicio
                    mensagens.append(Mensagem(tipo="texto", conteudo=f"Prazer, {_primeiro_nome(state)}! 💚"))
                    enter_msgs, prox = await _mensagens_on_enter(state, "apresentando_planos")
                    mensagens.extend(enter_msgs)
                    state["estado"] = prox or "aguardando_escolha_plano"
                else:
                    mensagens, target = _mensagens_nome_com_status(state, status_inicio)
                    state["estado"] = target
                add_message(state, "user", texto_inicio)
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=mensagens,
                    novo_estado=state["estado"],
                    fluxo_id=AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )

            enter_msgs, prox = await _mensagens_on_enter(state, "inicio")
            mensagens.extend(enter_msgs)
            state["estado"] = prox or "aguardando_nome"
            add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
            add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
            await save_state(phone_hash, state)
            return ResultadoTurno(sucesso=True, mensagens_enviadas=mensagens, novo_estado=state["estado"], fluxo_id=AGENDAMENTO_ID)

        interpretacao = await interpretar(mensagem, estado_antes, state.get("history", [])[-6:], state=state)
        entidades = _normalizar_entidades(
            state,
            interpretacao.entities,
            interpretacao.botao_id,
            interpretacao.texto_original,
        )

        if (
            estado_antes == "aguardando_nome"
            and interpretacao.intent == "informar_nome"
            and interpretacao.validacoes.get("validacao_nome_passou")
        ):
            status_informado = _status_paciente_from_text(interpretacao.texto_original)
            nome_informado = entidades.get("nome_extraido") or _extrair_nome(interpretacao.texto_original)
            if status_informado and nome_informado:
                state["collected_data"]["nome"] = nome_informado
                state["collected_data"]["status_paciente"] = status_informado
                mensagens, target = _mensagens_nome_com_status(state, status_informado)
                state["estado"] = target
                add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=mensagens,
                    novo_estado=state["estado"],
                    fluxo_id=AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )

        if estado_antes == "aguardando_cadastro":
            cadastro = await _processar_cadastro_incremental(
                state,
                phone,
                interpretacao.texto_original,
                entidades,
            )
            if cadastro:
                mensagens, target = cadastro
                state["estado"] = target
                add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=mensagens,
                    novo_estado=state["estado"],
                    fluxo_id=AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )

        acao = _acao_bloqueio_cadastro_se_necessario(estado_antes, interpretacao.texto_original, entidades)
        if acao is None and estado_antes == "aguardando_pagamento_pix" and entidades.get("valor_pago") is not None:
            acao = AcaoAutorizada(
                tipo=TipoAcao.executar_tool,
                tool_a_executar="analisar_comprovante",
                proximo_estado="validando_comprovante",
            )
        if acao is None and estado_antes == "aguardando_pagamento_pix" and _looks_like_cadastro_attempt(interpretacao.texto_original):
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[
                    Mensagem(
                        tipo="texto",
                        conteudo="Antes do cadastro, preciso confirmar o pagamento. Pode me mandar o comprovante do PIX confirmado? 💚",
                    )
                ],
                proximo_estado="aguardando_pagamento_pix",
            )
        if acao is None and estado_antes == "aguardando_pagamento_cartao":
            texto_cartao = _norm_text(interpretacao.texto_original)
            if "pix" in texto_cartao:
                state["collected_data"]["forma_pagamento"] = "pix"
                mensagens, target = await _mensagens_on_enter(state, "aguardando_pagamento_pix")
                state["estado"] = target or "aguardando_pagamento_pix"
                add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(
                    sucesso=True,
                    mensagens_enviadas=mensagens,
                    novo_estado=state["estado"],
                    fluxo_id=AGENDAMENTO_ID,
                    duracao_ms=int((time.perf_counter() - started) * 1000),
                )
            if _looks_like_cadastro_attempt(interpretacao.texto_original):
                acao = AcaoAutorizada(
                    tipo=TipoAcao.enviar_mensagem,
                    mensagens=[
                        Mensagem(
                            tipo="texto",
                            conteudo=(
                                "Ainda preciso aguardar a confirmação do cartão antes do cadastro. "
                                "Assim que confirmar, eu sigo com seus dados por aqui 💚"
                            ),
                        )
                    ],
                    proximo_estado="aguardando_pagamento_cartao",
                )
        if acao is None and estado_antes == "aguardando_escolha_slot" and interpretacao.intent == "informar_preferencia_horario":
            pref = _extrair_preferencia(interpretacao.texto_original)
            pref["descricao"] = interpretacao.texto_original
            state["collected_data"]["preferencia_horario"] = pref
            state["last_slots_offered"] = []
            state["slots_rejeitados"] = []
            mensagens, target = await _executar_consultar_slots(state)
            state["estado"] = target
            add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
            add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
            await save_state(phone_hash, state)
            return ResultadoTurno(
                sucesso=True,
                mensagens_enviadas=mensagens,
                novo_estado=state["estado"],
                fluxo_id=AGENDAMENTO_ID,
                duracao_ms=int((time.perf_counter() - started) * 1000),
            )
        if acao is None and estado_antes == "oferecendo_upsell":
            texto_norm = _norm_text(interpretacao.texto_original)
            if any(t in texto_norm for t in ("presencial", "online", "fica", "manter", "esse mesmo")):
                destino = "aguardando_preferencia_horario" if state["collected_data"].get("modalidade") else "aguardando_modalidade"
                acao = AcaoAutorizada(
                    tipo=TipoAcao.enviar_mensagem,
                    proximo_estado=destino,
                    salvar_no_estado={
                        "flags.upsell_oferecido": True,
                        "flags.upsell_aceito": False,
                    },
                )
        if acao is None and estado_antes == "aguardando_status_paciente" and state.get("flags", {}).get("paciente_identificado"):
            # Paciente identificado pelo CSV — rotear pelo intent real (qualquer mensagem)
            _intent_csv = interpretacao.intent or ""
            _texto_norm_csv = _norm_text(interpretacao.texto_original or "")
            _nome_csv = state["collected_data"].get("nome")

            _cancelar = _intent_csv in {"cancelar", "cancelamento"} or any(
                t in _texto_norm_csv for t in ("cancelar", "cancelamento", "desmarcar")
            )
            _remarcar = _intent_csv in {"remarcar", "remarcacao"} or any(
                t in _texto_norm_csv for t in ("remarcar", "remarcacao", "mudar horario", "mudar data")
            )
            _agendar = _intent_csv in {"agendar", "saudacao", "saudacao_sem_info"} or any(
                t in _texto_norm_csv for t in ("marcar", "agendar", "consulta", "quero")
            )
            # duvida_operacional e duvida_sobre_thaynara já têm handler no YAML — deixa state_machine tratar
            _deixa_yaml = _intent_csv in {"duvida_operacional", "duvida_sobre_thaynara", "desistir"}

            if not _deixa_yaml and (_cancelar or _remarcar or _agendar):
                state["collected_data"]["status_paciente"] = "retorno"
                _fluxo_destino = CANCELAMENTO_ID if _cancelar else REMARCACAO_ID
                state["fluxo_id"] = _fluxo_destino
                _tool_msgs, _target = await _identificar_consulta(state, _fluxo_destino, _nome_csv)
                mensagens.extend(_tool_msgs)
                state["estado"] = _target
                add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
                add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
                await save_state(phone_hash, state)
                return ResultadoTurno(sucesso=True, mensagens_enviadas=mensagens, novo_estado=state["estado"], fluxo_id=_fluxo_destino, duracao_ms=int((time.perf_counter() - started) * 1000))

        if acao is None:
            acao = state_machine.proxima_acao(
                estado_atual=estado_antes,
                intent=interpretacao.intent,
                entities=entidades,
                fluxo_id=AGENDAMENTO_ID,
                confidence=interpretacao.confidence,
                botao_id=interpretacao.botao_id,
                message_type=interpretacao.message_type,
                texto_original=interpretacao.texto_original,
                validacoes=interpretacao.validacoes,
                contexto_extra=_contexto_template(state, entidades),
            )
        if estado_antes == "aguardando_escolha_plano" and acao and acao.situacao_nome == "pergunta_modalidade":
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[
                    Mensagem(
                        tipo="texto",
                        conteudo=(
                            "Você pode escolher presencial ou online. No presencial, a consulta acontece na Aura Clinic. "
                            "No online, é por videochamada no WhatsApp, com orientações para fotos e medidas antes da consulta. "
                            "Agora me conta: qual plano faz mais sentido pra você?"
                        ),
                    )
                ],
                proximo_estado="aguardando_escolha_plano",
                situacao_nome="pergunta_modalidade",
            )
        if estado_antes == "aguardando_pagamento_cartao" and acao and acao.situacao_nome == "paciente_disse_pagou":
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[
                    Mensagem(
                        tipo="texto",
                        conteudo=(
                            "Perfeito, vou aguardar a confirmação do cartão por aqui. "
                            "Assim que confirmar, sigo com seu cadastro para finalizar o agendamento 💚"
                        ),
                    )
                ],
                proximo_estado="aguardando_pagamento_cartao",
                situacao_nome="paciente_disse_pagou",
            )
        # ── FORA DE CONTEXTO (Fluxo 10) ──────────────────────────────────────
        fora_contexto = acao is None
        if acao is None:
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[Mensagem(tipo="texto", conteudo="Pode me mandar de outro jeito para eu entender certinho?")],
                proximo_estado=estado_antes,
            )

        validation = rules.validar_acao_pre_envio(acao, state)
        blocked = next((v for v in validation if not v.passou and v.severidade == "BLOCKING"), None)
        if blocked:
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[Mensagem(tipo="texto", conteudo="Preciso validar essa informação antes de seguir.")],
                proximo_estado=estado_antes,
            )

        _aplicar_efeitos_especiais(state, acao)
        _aplicar_salvar_no_estado(state, acao.salvar_no_estado)
        if estado_antes == "aguardando_escolha_slot" and acao.situacao_nome in {"escolheu_slot_botao", "escolheu_slot_texto"}:
            slot_escolhido = entidades.get("slot_correspondente") or entidades.get("slot_match")
            if isinstance(slot_escolhido, dict):
                state.setdefault("appointment", {})["slot_escolhido"] = slot_escolhido
        target = acao.proximo_estado or _acao_navegacao(acao)

        if acao.tool_a_executar == "consultar_slots":
            tools_chamadas.append("consultar_slots")
            tool_msgs, target = await _executar_consultar_slots(state)
            mensagens.extend(tool_msgs)
        elif acao.tool_a_executar == "analisar_comprovante":
            tools_chamadas.append("analisar_comprovante")
            tool_msgs, target = await _executar_pagamento_pix(state, mensagem, entidades)
            mensagens.extend(tool_msgs)
        elif (acao.dados or {}).get("action") == "criar_agendamento":
            tool_msgs, target = await _criar_agendamento_e_confirmar(state)
            mensagens.extend(tool_msgs)
        else:
            mensagens.extend(await response_writer.escrever_async(acao, _contexto_template(state, entidades)))

        if estado_antes == "aguardando_preferencia_horario":
            invalidas = {
                "pediu_sexta_noite",
                "pediu_fim_de_semana",
                "pediu_horario_fora_grade",
                "pediu_mesmo_dia",
                "resposta_vaga",
            }
            if acao.situacao_nome in invalidas:
                state["invalid_preferencia_count"] = int(state.get("invalid_preferencia_count") or 0) + 1
            elif acao.tool_a_executar == "consultar_slots":
                state["invalid_preferencia_count"] = 0
            if int(state.get("invalid_preferencia_count") or 0) >= 4:
                tools_chamadas.append("escalar_breno_silencioso")
                await _escalar_agendamento_inviavel(
                    state=state,
                    phone=phone,
                    motivo="preferencia_horario_inviavel_repetida",
                    estado_antes=estado_antes,
                    ultima_mensagem=interpretacao.texto_original,
                )
                mensagens.append(
                    Mensagem(
                        tipo="texto",
                        conteudo="Vou pedir pra alguém da equipe te ajudar a encontrar a melhor opção, tá? Um momento 💚",
                    )
                )
                target = "concluido_escalado"

        if acao.situacao_nome == "rejeitou_todos" and int(state.get("rodada_negociacao") or 0) > 3:
            tools_chamadas.append("escalar_breno_silencioso")
            await _escalar_agendamento_inviavel(
                state=state,
                phone=phone,
                motivo="slots_rejeitados_tres_rodadas",
                estado_antes=estado_antes,
                ultima_mensagem=interpretacao.texto_original,
            )
            mensagens.append(
                Mensagem(
                    tipo="texto",
                    conteudo="Vou pedir pra alguém da equipe te ajudar a encontrar a melhor opção, tá? Um momento 💚",
                )
            )
            target = "concluido_escalado"

        if target == "aguardando_modalidade" and state["collected_data"].get("modalidade"):
            target = "aguardando_preferencia_horario"

        if target:
            state["estado"] = target
            if _deve_disparar_on_enter(acao, target) and not mensagens:
                enter_msgs, prox = await _mensagens_on_enter(state, target)
                mensagens.extend(enter_msgs)
                if prox:
                    state["estado"] = prox
            elif _deve_disparar_on_enter(acao, target) and target in {
                "apresentando_planos",
                "aguardando_modalidade",
                "aguardando_preferencia_horario",
                "aguardando_forma_pagamento",
                "aguardando_pagamento_pix",
                "aguardando_cadastro",
                "oferecendo_upsell",
            }:
                enter_msgs, prox = await _mensagens_on_enter(state, target)
                mensagens.extend(enter_msgs)
                if prox:
                    state["estado"] = prox

        if state.get("estado") == "criando_agendamento":
            final_msgs, final_state = await _criar_agendamento_e_confirmar(state)
            mensagens.extend(final_msgs)
            state["estado"] = final_state

        # ── CONTADOR FORA DE CONTEXTO (Fluxo 10) ─────────────────────────────
        if fora_contexto:
            state["fora_contexto_count"] = int(state.get("fora_contexto_count") or 0) + 1
            mensagens = await _aplicar_controle_loop_fallback(
                state=state,
                phone=phone,
                mensagens=mensagens,
                is_fallback=True,
                estado_antes=estado_antes,
                ultima_mensagem=interpretacao.texto_original,
                tools_chamadas=tools_chamadas,
            )
            if state.get("estado") == "aguardando_orientacao_breno":
                target = state["estado"]
        else:
            state["fora_contexto_count"] = 0
            mensagens = await _aplicar_controle_loop_fallback(
                state=state,
                phone=phone,
                mensagens=mensagens,
                is_fallback=False,
                estado_antes=estado_antes,
                ultima_mensagem=interpretacao.texto_original,
                tools_chamadas=tools_chamadas,
            )

        add_message(state, "user", interpretacao.texto_original)
        add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
        await save_state(phone_hash, state)
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=mensagens,
            novo_estado=state["estado"],
            fluxo_id=AGENDAMENTO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        erro = str(exc)
        logger.exception("Erro no orchestrator v2: %s", exc)
        fallback = Mensagem(tipo="texto", conteudo="Tive uma instabilidade aqui. Pode me mandar de novo, por favor?")
        return ResultadoTurno(sucesso=False, mensagens_enviadas=[fallback], novo_estado=state.get("estado"), fluxo_id=state.get("fluxo_id") or AGENDAMENTO_ID, erro=erro)
    finally:
        await _log_metric({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": phone_hash,
            "fluxo": state.get("fluxo_id") or AGENDAMENTO_ID,
            "estado_antes": estado_antes,
            "estado_depois": state.get("estado"),
            "tools_chamadas": tools_chamadas,
            "duracao_ms": int((time.perf_counter() - started) * 1000),
            "erro": erro,
        })
