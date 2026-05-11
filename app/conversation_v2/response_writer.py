"""
Response Writer — transforma AcaoAutorizada em mensagem(ns) final(is).

Função principal:
    escrever(acao: AcaoAutorizada, contexto: dict) -> list[Mensagem]
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Callable

from app.conversation_v2.models import AcaoAutorizada, BotaoInterativo, Mensagem, RuleResult, TipoAcao
from app.conversation_v2.output_validator import validar_com_regeneracao

logger = logging.getLogger(__name__)

_FALLBACK_PADRAO = "Pode me dar mais detalhes para eu te ajudar certinho? 💚"


def _get_nested(ctx: dict[str, Any], key: str) -> Any:
    val: Any = ctx
    for part in key.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    return val


def renderizar_template(template: str, contexto: dict[str, Any]) -> str:
    def _resolver(match: re.Match[str]) -> str:
        chave = match.group(1).strip()
        valor = _get_nested(contexto, chave)
        if valor is None:
            return f"{{{chave}}}"
        return str(valor)

    return re.sub(r"\{([\w.]+)\}", _resolver, template or "")


def _normalizar_botoes(raw: list[Any]) -> list[BotaoInterativo]:
    botoes: list[BotaoInterativo] = []
    for botao in raw:
        if isinstance(botao, BotaoInterativo):
            botoes.append(botao)
        elif isinstance(botao, dict):
            botoes.append(BotaoInterativo(**botao))
    return botoes


def _renderizar_mensagem(msg: Mensagem, contexto: dict[str, Any]) -> Mensagem:
    return msg.model_copy(
        update={
            "conteudo": renderizar_template(msg.conteudo, contexto),
            "arquivo": renderizar_template(msg.arquivo, contexto) if msg.arquivo else None,
            "numero_contato": renderizar_template(msg.numero_contato, contexto) if msg.numero_contato else None,
        }
    )


def _processar_acao_sequencial(acao: dict[str, Any], contexto: dict[str, Any]) -> Mensagem | None:
    tipo = str(acao.get("tipo", "")).strip().lower()
    if not tipo and any(k in acao for k in ("texto", "mensagem", "mensagem_template", "resposta_template")):
        tipo = "enviar_texto"
    if not tipo:
        return None
    if tipo == "enviar_texto":
        texto_raw = (
            acao.get("texto")
            or acao.get("mensagem")
            or acao.get("mensagem_template")
            or acao.get("resposta_template")
            or ""
        )
        texto = renderizar_template(str(texto_raw), contexto)
        botoes = _normalizar_botoes(acao.get("botoes_interativos") or acao.get("botoes") or [])
        return Mensagem(tipo="botoes" if botoes else "texto", conteudo=texto, botoes=botoes)
    if tipo == "enviar_imagem":
        return Mensagem(
            tipo="imagem",
            conteudo=renderizar_template(str(acao.get("legenda", "")), contexto),
            arquivo=renderizar_template(str(acao.get("arquivo", "")), contexto),
        )
    if tipo == "enviar_pdf":
        arquivo = acao.get("arquivo_dinamico") or acao.get("arquivo") or ""
        return Mensagem(tipo="pdf", arquivo=renderizar_template(str(arquivo), contexto))
    if tipo == "enviar_contato":
        return Mensagem(
            tipo="contato",
            conteudo=renderizar_template(str(acao.get("nome", "")), contexto),
            numero_contato=renderizar_template(str(acao.get("numero", "")), contexto),
        )
    if tipo == "delay":
        return Mensagem(tipo="delay", delay_segundos=int(acao.get("segundos", 1)))
    return None


def _mensagens_base(acao: AcaoAutorizada, contexto: dict[str, Any]) -> list[Mensagem]:
    mensagens: list[Mensagem] = []
    for msg in acao.mensagens_a_enviar or acao.mensagens:
        mensagens.append(_renderizar_mensagem(msg, contexto))

    sequencia = acao.dados.get("acoes_em_sequencia")
    if isinstance(sequencia, dict):
        sequencia = list(sequencia.values())
    if isinstance(sequencia, list):
        for item in sequencia:
            if isinstance(item, dict):
                built = _processar_acao_sequencial(item, contexto)
                if built is not None:
                    mensagens.append(built)
    return mensagens


async def _gerar_texto_improviso(instrucao: str, contexto: dict[str, Any]) -> str:
    try:
        from app.llm_client import complete_text_async

        system = (
            "Você é Ana, assistente de agendamentos da nutricionista Thaynara. "
            "Seja objetiva, curta e factual. Nunca invente valores, horários ou políticas."
        )
        user = (
            f"INSTRUCAO:\n{instrucao}\n\n"
            "CONTEXTO:\n"
            + "\n".join(f"{k}: {v}" for k, v in contexto.items() if not str(k).startswith("_"))
            + "\n\nResponda em até 3 frases."
        )
        texto = await complete_text_async(system=system, user=user, max_tokens=220, temperature=0.2)
        texto = (texto or "").strip()
        return texto or _FALLBACK_PADRAO
    except Exception as exc:
        logger.exception("Falha ao gerar improviso: %s", exc)
        return _FALLBACK_PADRAO


def _regenerador_sync(
    contexto: dict[str, Any],
) -> Callable[[list[RuleResult], int, list[Mensagem]], list[Mensagem]]:
    def _regenerar(violacoes: list[RuleResult], tentativa: int, atuais: list[Mensagem]) -> list[Mensagem]:
        aviso = "; ".join(v.regra for v in violacoes)
        logger.warning("Tentativa de regeneração %d bloqueada por: %s", tentativa, aviso)
        return [Mensagem(tipo="texto", conteudo=_FALLBACK_PADRAO)]

    return _regenerar


def escrever(acao: AcaoAutorizada, contexto: dict[str, Any]) -> list[Mensagem]:
    if acao.permite_improviso or acao.tipo == TipoAcao.improviso_llm:
        mensagens = [Mensagem(tipo="texto", conteudo=_FALLBACK_PADRAO)]
    else:
        mensagens = _mensagens_base(acao, contexto)
    resultado = validar_com_regeneracao(
        mensagens=mensagens,
        contexto=contexto,
        regenerador=_regenerador_sync(contexto),
    )
    return resultado.mensagens


async def escrever_async(acao: AcaoAutorizada, contexto: dict[str, Any]) -> list[Mensagem]:
    if acao.permite_improviso or acao.tipo == TipoAcao.improviso_llm:
        instrucao = acao.instrucao_improviso or "Responda com segurança e peça contexto adicional."
        texto = await _gerar_texto_improviso(instrucao, contexto)
        mensagens = [Mensagem(tipo="texto", conteudo=texto)]
    else:
        mensagens = _mensagens_base(acao, contexto)

    resultado = validar_com_regeneracao(
        mensagens=mensagens,
        contexto=contexto,
        regenerador=_regenerador_sync(contexto),
    )
    return resultado.mensagens


def escrever_improviso_sync(acao: AcaoAutorizada, contexto: dict[str, Any]) -> list[Mensagem]:
    """Atalho para ambientes síncronos que aceitam rodar o async internamente."""
    return asyncio.run(escrever_async(acao, contexto))
