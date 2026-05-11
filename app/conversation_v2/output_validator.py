"""
Output Validator — valida toda mensagem antes de enviar ao paciente.

Roda regras invioláveis globais (R1, R3, R5, etc.) na resposta final.
Se reprovar, registra e regenera (max 2 tentativas) ou usa fallback seguro.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.conversation_v2.models import Mensagem, RuleResult
from app.conversation_v2.rules import validar_resposta_completa

logger = logging.getLogger(__name__)

MAX_TENTATIVAS_REGENERACAO = 2

_FALLBACK_MENSAGEM = Mensagem(
    tipo="texto",
    conteudo="Deixa eu verificar essa informação e já te respondo, tá? 💚",
)


@dataclass
class ValidacaoResult:
    """Resultado da validação de um conjunto de mensagens."""
    aprovado: bool
    mensagens: list[Mensagem]
    violacoes: list[RuleResult] = field(default_factory=list)
    usou_fallback: bool = False
    tentativas_regeneracao: int = 0


def _validar_mensagem_unica(
    msg: Mensagem,
    contexto: dict[str, Any],
) -> list[RuleResult]:
    """Valida uma mensagem individual. Retorna lista de violações."""
    if msg.tipo in ("delay", "imagem", "pdf"):
        return []  # tipos não-texto não têm conteúdo textual a validar
    return [r for r in validar_resposta_completa(msg.conteudo, contexto) if not r.passou]


def _coletar_violacoes(mensagens: list[Mensagem], contexto: dict[str, Any]) -> list[RuleResult]:
    violacoes: list[RuleResult] = []
    for msg in mensagens:
        msg_violacoes = _validar_mensagem_unica(msg, contexto)
        if msg_violacoes:
            for regra in msg_violacoes:
                logger.warning(
                    "Regra violada [%s]: %s | Conteúdo: %.80r",
                    regra.regra,
                    regra.motivo,
                    msg.conteudo,
                )
            violacoes.extend(msg_violacoes)
    return violacoes


def validar(
    mensagens: list[Mensagem],
    contexto: dict[str, Any],
) -> ValidacaoResult:
    """
    Valida todas as mensagens contra regras invioláveis globais.

    - Se todas passam → retorna ValidacaoResult(aprovado=True, mensagens=mensagens)
    - Se alguma viola → loga, registra violação, usa fallback seguro
    - Nunca levanta exceção — sempre retorna algo seguro

    Args:
        mensagens: lista de mensagens a validar
        contexto: contexto do turno (paciente_status, fluxo_contexto, etc.)

    Returns:
        ValidacaoResult com status e mensagens finais (aprovadas ou fallback)
    """
    todas_violacoes = _coletar_violacoes(mensagens, contexto)
    if not todas_violacoes:
        return ValidacaoResult(aprovado=True, mensagens=mensagens)

    # Há violações — usa fallback
    logger.error(
        "Output validator bloqueou %d mensagem(s). Violações: %s. Usando fallback.",
        len(mensagens),
        [v.regra for v in todas_violacoes],
    )
    return ValidacaoResult(
        aprovado=False,
        mensagens=[_FALLBACK_MENSAGEM],
        violacoes=todas_violacoes,
        usou_fallback=True,
    )


def validar_com_regeneracao(
    mensagens: list[Mensagem],
    contexto: dict[str, Any],
    regenerador: Callable[[list[RuleResult], int, list[Mensagem]], list[Mensagem]] | None = None,
    max_tentativas: int = MAX_TENTATIVAS_REGENERACAO,
) -> ValidacaoResult:
    """
    Valida e tenta regenerar quando houver violação.

    O callback `regenerador` recebe:
      - violacoes: list[RuleResult]
      - tentativa: int (1..max)
      - mensagens_atuais: list[Mensagem]
    E retorna nova lista de Mensagem para nova validação.
    """
    tentativas = 0
    atuais = mensagens

    while True:
        violacoes = _coletar_violacoes(atuais, contexto)
        if not violacoes:
            return ValidacaoResult(
                aprovado=True,
                mensagens=atuais,
                tentativas_regeneracao=tentativas,
            )
        if regenerador is None or tentativas >= max_tentativas:
            return ValidacaoResult(
                aprovado=False,
                mensagens=[_FALLBACK_MENSAGEM],
                violacoes=violacoes,
                usou_fallback=True,
                tentativas_regeneracao=tentativas,
            )
        tentativas += 1
        try:
            atuais = regenerador(violacoes, tentativas, atuais)
        except Exception as exc:
            logger.exception("Regeneração falhou: %s", exc)
            return ValidacaoResult(
                aprovado=False,
                mensagens=[_FALLBACK_MENSAGEM],
                violacoes=violacoes,
                usou_fallback=True,
                tentativas_regeneracao=tentativas,
            )


def validar_texto_simples(
    texto: str,
    contexto: dict[str, Any],
) -> ValidacaoResult:
    """Atalho para validar um único texto (sem construir Mensagem)."""
    return validar([Mensagem(tipo="texto", conteudo=texto)], contexto)
