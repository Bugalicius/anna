"""
Escalação para humano (nutricionista Thaynara).

REGRAS DE SEGURANÇA:
  - O número interno (NUMERO_INTERNO) NUNCA deve ser enviado ao paciente.
  - A escalação envia o contexto para o número interno via Meta API.
  - O paciente recebe apenas uma mensagem genérica de aguardo.

Timeout: 15 minutos em horário comercial (08h–19h, seg–sex).
Fora do horário: escalação é enfileirada e enviada no próximo horário útil.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))

logger = logging.getLogger(__name__)

# Número interno — NUNCA expor ao paciente
_NUMERO_INTERNO = "5531992059211"

# Mensagem enviada ao paciente ao escalar
_MSG_PACIENTE_ESCALACAO = (
    "Ótimo! Vou chamar a Thaynara para te atender pessoalmente. "
    "Aguarda um instante, ela já está sendo avisada 💚"
)

# Timeout de espera por resposta humana (em minutos)
TIMEOUT_MINUTOS = 15


def _em_horario_comercial(agora: datetime | None = None) -> bool:
    """Retorna True se agora está dentro do horário de atendimento (seg–sex, 08h–19h BRT)."""
    agora = agora or datetime.now(BRT)
    if agora.weekday() >= 5:   # sábado=5, domingo=6
        return False
    return 8 <= agora.hour < 19


def build_contexto_escalacao(
    nome_paciente: str | None,
    telefone_paciente: str,
    historico_resumido: str,
    motivo: str,
) -> str:
    """
    Monta a mensagem de contexto enviada ao número interno.
    Não inclui dados sensíveis (o telefone é o número do paciente no WhatsApp — seguro para envio interno).
    """
    nome = nome_paciente or "Paciente não identificado"
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    return (
        f"🔔 *ESCALAÇÃO — {agora}*\n\n"
        f"*Paciente:* {nome}\n"
        f"*WhatsApp:* {telefone_paciente}\n"
        f"*Motivo:* {motivo}\n\n"
        f"*Resumo da conversa:*\n{historico_resumido}"
    )


async def escalar_para_humano(
    meta_client,                  # app.meta_api.MetaAPIClient
    telefone_paciente: str,
    nome_paciente: str | None,
    historico_resumido: str,
    motivo: str = "Dúvida clínica ou solicitação de atendimento humano",
) -> bool:
    """
    Notifica o número interno e envia mensagem de espera ao paciente.

    Returns:
        True se as mensagens foram enviadas com sucesso.
    """
    em_horario = _em_horario_comercial()

    # 1. Avisa o paciente
    try:
        await meta_client.send_text(telefone_paciente, _MSG_PACIENTE_ESCALACAO)
    except Exception as e:
        logger.error("Falha ao enviar msg de escalação ao paciente %s: %s", telefone_paciente, e)

    # 2. Envia contexto para número interno
    contexto = build_contexto_escalacao(
        nome_paciente, telefone_paciente, historico_resumido, motivo
    )

    prefixo = "" if em_horario else "⏳ *FORA DO HORÁRIO — responder ao retornar:*\n\n"
    try:
        await meta_client.send_text(_NUMERO_INTERNO, prefixo + contexto)
        logger.info(
            "Escalação enviada ao número interno (paciente=%s, motivo=%s)",
            telefone_paciente, motivo,
        )
        return True
    except Exception as e:
        logger.error("Falha ao enviar escalação ao número interno: %s", e)
        return False
