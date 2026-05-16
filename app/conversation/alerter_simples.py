"""
Alerter simples: notifica Breno apenas em situacoes que precisam de acao humana.

1. Sistema offline (UptimeRobot externo)
2. Loop de mensagem
3. Duvida clinica escalada
4. Escalacao geral
"""
from __future__ import annotations

import logging
import os

from app.meta_api import MetaAPIClient

logger = logging.getLogger(__name__)

BRENO_PHONE = "5531992059211"


def _get_template_name() -> str:
    return os.getenv("ESCALATION_TEMPLATE_NAME", "")


async def alertar_breno(mensagem: str) -> None:
    """Envia mensagem simples para o WhatsApp do Breno sem travar o agente."""
    try:
        client = MetaAPIClient()
        template_name = _get_template_name()
        if hasattr(client, "send_template") and template_name:
            try:
                await client.send_template(BRENO_PHONE, template_name, "pt_BR")
            except Exception as exc:
                logger.warning("Template de alerta para Breno falhou: %s", exc)
        await client.send_text(BRENO_PHONE, mensagem)
    except Exception as exc:
        logger.error("Falhou ao alertar Breno: %s", exc)


async def alertar_duvida_clinica(phone: str, nome: str, pergunta: str) -> None:
    """Alerta 3: duvida clinica."""
    await alertar_breno(
        f"🏥 Dúvida clínica\n\n"
        f"Paciente: {nome or phone}\n"
        f"WhatsApp: {phone}\n"
        f"Pergunta: {pergunta}"
    )


async def alertar_escalacao(phone: str, nome: str, motivo: str, resumo: str = "") -> None:
    """Alerta 4: agente nao soube responder / escalacao geral."""
    await alertar_breno(
        f"🔔 Escalação\n\n"
        f"Paciente: {nome or phone}\n"
        f"WhatsApp: {phone}\n"
        f"Motivo: {motivo}"
        + (f"\nResumo: {resumo}" if resumo else "")
    )


async def alertar_loop_mensagem(phone: str, nome: str, mensagem_repetida: str) -> None:
    """Alerta 2: agente mandou a mesma mensagem repetida."""
    await alertar_breno(
        f"🔁 Loop detectado\n\n"
        f"Paciente: {nome or phone}\n"
        f"WhatsApp: {phone}\n"
        f"Mensagem repetida 3x: {mensagem_repetida[:100]}"
    )
