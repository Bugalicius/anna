"""
State Machine — decide próxima ação possível a partir do estado atual + intent.

Função principal:
    proxima_acao(estado_atual, intent, entities, fluxo_id) -> AcaoAutorizada | None
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.conversation.config_loader import config
from app.conversation.models import (
    AcaoAutorizada,
    Interpretacao,
    Mensagem,
    Situacao,
    TipoAcao,
)

logger = logging.getLogger(__name__)


def _get_nested(ctx: dict[str, Any], key: str) -> Any:
    val: Any = ctx
    for part in key.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def _render_template(texto: str, ctx: dict[str, Any]) -> str:
    def _replace(match: re.Match[str]) -> str:
        k = match.group(1).strip()
        v = _get_nested(ctx, k)
        return f"{{{k}}}" if v is None else str(v)

    return re.sub(r"\{([\w.]+)\}", _replace, texto)


def _aplicar_mapeamentos(mapeamento: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    def _render_valor(valor: Any) -> Any:
        if isinstance(valor, str):
            return _render_template(valor, ctx)
        if isinstance(valor, dict):
            return {k: _render_valor(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [_render_valor(v) for v in valor]
        return valor

    saida: dict[str, Any] = {}
    for chave, valor in (mapeamento or {}).items():
        saida[chave] = _render_valor(valor)
    return saida


def _avaliar_condicao(cond: str, ctx: dict[str, Any]) -> bool:
    cond = cond.strip()
    if cond == "nao_match_acima":
        return bool(ctx.get("nao_match_acima", False))

    m = re.match(r"^([\w.]+)\s+IN\s+\[(.+)\]$", cond, flags=re.IGNORECASE)
    if m:
        key, raw = m.group(1), m.group(2)
        lista = [v.strip().strip('"\'').lower() for v in raw.split(",")]
        return str(_get_nested(ctx, key) or "").lower() in lista

    m = re.match(r"^texto_contem=\[(.+)\]$", cond)
    if m:
        termos = [t.strip().strip('"\'').lower() for t in m.group(1).split(",")]
        texto = str(ctx.get("texto_original", "")).lower()
        return any(termo in texto for termo in termos)

    m = re.match(r"^([\w.]+)=\[(.+)\]$", cond)
    if m:
        key, raw = m.group(1), m.group(2)
        lista = [v.strip().strip('"\'').lower() for v in raw.split(",")]
        return str(_get_nested(ctx, key) or "").lower() in lista

    for op in ("!=", "<=", ">=", "=="):
        m = re.match(rf"^([\w.]+)\s*{re.escape(op)}\s*(.+)$", cond)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        atual = _get_nested(ctx, key)
        if op in ("!=", "=="):
            if op == "==":
                try:
                    return float(atual) == float(raw)
                except (TypeError, ValueError):
                    return str(atual).lower() == raw.lower()
            return str(atual).lower() != raw.lower()
        try:
            atual_n = float(atual)
            raw_n = float(raw)
        except (TypeError, ValueError):
            return False
        if op == "<=":
            return atual_n <= raw_n
        return atual_n >= raw_n

    for op in ("<", ">"):
        m = re.match(rf"^([\w.]+)\s*{re.escape(op)}\s*(.+)$", cond)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        try:
            atual_n = float(_get_nested(ctx, key))
            raw_n = float(raw)
        except (TypeError, ValueError):
            return False
        if op == "<":
            return atual_n < raw_n
        return atual_n > raw_n

    m = re.match(r"^([\w.]+)\s*=\s*(.+)$", cond)
    if m:
        key, raw = m.group(1), m.group(2).strip()
        atual = _get_nested(ctx, key)
        if raw.lower() == "true":
            return atual is True or str(atual).lower() == "true"
        if raw.lower() == "false":
            return atual is False or str(atual).lower() == "false"
        return str(atual).lower() == raw.lower()

    if re.match(r"^[\w.]+$", cond):
        return bool(_get_nested(ctx, cond))

    logger.debug("Condição não reconhecida: %s", cond)
    return False


def _avaliar_trigger(trigger: str, ctx: dict[str, Any]) -> bool:
    partes_or = re.split(r"\s+OR\s+", trigger, flags=re.IGNORECASE)
    for parte_or in partes_or:
        partes_and = re.split(r"\s+AND\s+", parte_or, flags=re.IGNORECASE)
        if all(_avaliar_condicao(cond, ctx) for cond in partes_and):
            return True
    return False


def _resolver_tool_name(acao: str | None) -> str | None:
    if not acao:
        return None
    aliases = {
        "consultar_slots_dietbox": "consultar_slots",
        "consultar_slots_proxima_pagina": "consultar_slots",
        "tool_analisar_comprovante": "analisar_comprovante",
        "tool_analisar_imagem": "classificar_imagem",
        "tool_cancelar_dietbox": "cancelar_dietbox",
        "tool_detectar_tipo_remarcacao": "detectar_tipo_remarcacao",
        "tool_detectar_tipo_remarcacao_por_nome": "detectar_tipo_remarcacao",
        "tool_gerar_link_pagamento": "gerar_link_pagamento",
        "tool_gerar_link_pagamento_novo": "gerar_link_pagamento",
        "tool_transcrever_audio_gemini": "transcrever_audio",
        "tool_validar_comprovante_completo": "analisar_comprovante",
        "validar_comprovante": "analisar_comprovante",
        "interpretar_comando_via_gemini": "interpretar_comando",
        "encaminhar_comprovante_thaynara": "encaminhar_comprovante_thaynara",
        "escalar_breno_silencioso": "escalar_breno_silencioso",
        "notificar_breno_paciente_nao_confirmou": "notificar_breno",
        "notificar_breno_tentativa_b2b": "notificar_breno",
        "encaminhar_pagamento_thaynara": "notificar_thaynara",
    }
    candidates = [
        acao,
        aliases.get(acao, ""),
        acao.removeprefix("tool_"),
        acao.removeprefix("tool_").removesuffix("_dietbox"),
    ]
    try:
        from app.conversation.tools.registry import TOOLS
    except Exception:
        TOOLS = {}
    for candidate in candidates:
        if candidate and candidate in TOOLS:
            return candidate
    return None


def _tipo_acao(situacao: Situacao) -> TipoAcao:
    acao = situacao.acao_declarada or ""
    if situacao.permite_improviso:
        return TipoAcao.improviso_llm
    if _resolver_tool_name(acao):
        return TipoAcao.executar_tool
    if "escalar" in acao:
        return TipoAcao.escalar
    if "redirecionar_fluxo" in acao:
        return TipoAcao.redirecionar_fluxo
    return TipoAcao.enviar_mensagem


def _situacao_para_acao(nome: str, situacao: Situacao, ctx: dict[str, Any]) -> AcaoAutorizada:
    mensagens: list[Mensagem] = []
    texto = situacao.texto_resposta()
    if texto:
        mensagens.append(
            Mensagem(
                tipo="botoes" if situacao.botoes_interativos else "texto",
                conteudo=texto,
                botoes=situacao.botoes_interativos,
            )
        )
    acao = situacao.acao_declarada
    tool_name = _resolver_tool_name(acao)
    salvar = _aplicar_mapeamentos(situacao.salva_no_estado, ctx)
    return AcaoAutorizada(
        tipo=_tipo_acao(situacao),
        proximo_estado=situacao.proximo_estado,
        mensagens=mensagens,
        mensagens_a_enviar=mensagens,
        tool_a_executar=tool_name,
        permite_improviso=situacao.permite_improviso,
        instrucao_improviso=situacao.instrucao_para_llm,
        salvar_no_estado=salvar,
        dados={
            "action": acao,
            "usar_kb_objections": situacao.usar_kb_objections,
            "max_tentativas": situacao.max_tentativas,
            "ao_atingir_max": situacao.ao_atingir_max,
            "agendar_remarketing": situacao.agendar_remarketing,
            "regras_escalacao": situacao.regras_escalacao,
        },
        situacao_nome=nome,
    )


def _build_ctx(
    intent: str,
    entities: dict[str, Any] | None,
    confidence: float,
    botao_id: str | None,
    message_type: str,
    texto_original: str,
    validacoes: dict[str, Any] | None,
    contexto_extra: dict[str, Any] | None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "intent": intent,
        "confidence": confidence,
        "botao_id": botao_id or "",
        "message_type": message_type,
        "messageType": message_type,
        "texto_original": texto_original,
        "nao_match_acima": False,
    }
    if entities:
        ctx.update(entities)
    if validacoes:
        ctx.update(validacoes)
    if contexto_extra:
        ctx.update(contexto_extra)
    return ctx


def proxima_acao(
    estado_atual: str,
    intent: str,
    entities: dict[str, Any] | None,
    fluxo_id: str,
    *,
    confidence: float = 1.0,
    botao_id: str | None = None,
    message_type: str = "text",
    texto_original: str = "",
    validacoes: dict[str, Any] | None = None,
    contexto_extra: dict[str, Any] | None = None,
) -> AcaoAutorizada | None:
    """Retorna a próxima ação autorizada para o estado/intent atual."""
    try:
        fluxo = config.get_fluxo(fluxo_id)
    except KeyError:
        logger.warning("Fluxo não encontrado: %s", fluxo_id)
        return None

    estado = fluxo.estados.get(estado_atual)
    if estado is None:
        logger.warning("Estado %s inexistente no fluxo %s", estado_atual, fluxo_id)
        return None

    if not estado.situacoes:
        return None

    ctx = _build_ctx(
        intent=intent,
        entities=entities,
        confidence=confidence,
        botao_id=botao_id,
        message_type=message_type,
        texto_original=texto_original,
        validacoes=validacoes,
        contexto_extra=contexto_extra,
    )

    match_ate_agora = False
    for nome, situacao in estado.situacoes.items():
        ctx["nao_match_acima"] = not match_ate_agora
        try:
            if _avaliar_trigger(situacao.trigger, ctx):
                match_ate_agora = True
                return _situacao_para_acao(nome, situacao, ctx)
        except Exception as exc:
            logger.exception(
                "Erro avaliando trigger '%s' em %s/%s/%s: %s",
                situacao.trigger,
                fluxo_id,
                estado_atual,
                nome,
                exc,
            )
    return None


def proxima_acao_de_interpretacao(
    fluxo_id: str,
    estado_atual: str,
    interpretacao: Interpretacao,
    contexto_extra: dict[str, Any] | None = None,
) -> AcaoAutorizada | None:
    """Compat: usa o contrato antigo baseado em Interpretacao."""
    return proxima_acao(
        estado_atual=estado_atual,
        intent=interpretacao.intent,
        entities=interpretacao.entities,
        fluxo_id=fluxo_id,
        confidence=interpretacao.confidence,
        botao_id=interpretacao.botao_id,
        message_type=interpretacao.message_type,
        texto_original=interpretacao.texto_original,
        validacoes=interpretacao.validacoes,
        contexto_extra=contexto_extra,
    )


def on_enter_estado(fluxo_id: str, estado_nome: str) -> AcaoAutorizada | None:
    """Retorna ação declarada em on_enter do estado, se houver."""
    try:
        fluxo = config.get_fluxo(fluxo_id)
    except KeyError:
        return None
    estado = fluxo.estados.get(estado_nome)
    if not estado or not estado.on_enter:
        return None

    oe = estado.on_enter
    mensagens: list[Mensagem] = []
    texto = oe.texto_mensagem()
    if texto:
        mensagens.append(
            Mensagem(
                tipo="botoes" if oe.botoes_interativos else "texto",
                conteudo=texto,
                botoes=oe.botoes_interativos,
            )
        )
    tool = _resolver_tool_name(oe.acao)
    return AcaoAutorizada(
        tipo=TipoAcao.executar_tool if tool else TipoAcao.enviar_mensagem,
        proximo_estado=oe.proximo_estado,
        mensagens=mensagens,
        mensagens_a_enviar=mensagens,
        tool_a_executar=tool,
        salvar_no_estado=oe.salva_no_estado,
        dados={
            "acoes": oe.acoes,
            "acoes_em_sequencia": oe.acoes_em_sequencia,
            "action": oe.acao,
        },
    )
