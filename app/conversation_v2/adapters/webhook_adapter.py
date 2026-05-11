"""
Adapter do webhook Meta API para o conversation_v2.

Normaliza mensagens recebidas, chama o orchestrator e devolve as mensagens
que a camada externa deve enviar ao paciente.
"""
from __future__ import annotations

import logging
from typing import Any

from app.conversation_v2.orchestrator import processar_turno

logger = logging.getLogger(__name__)


def _texto_da_mensagem(message: dict[str, Any]) -> str:
    msg_type = message.get("type")
    if msg_type == "text":
        return str((message.get("text") or {}).get("body") or "")
    if msg_type == "button":
        return str((message.get("button") or {}).get("payload") or (message.get("button") or {}).get("text") or "")
    if msg_type == "interactive":
        interactive = message.get("interactive") or {}
        return str(
            (interactive.get("button_reply") or {}).get("id")
            or (interactive.get("list_reply") or {}).get("id")
            or ""
        )
    return str((message.get(msg_type) or {}).get("caption") or "")


def _normalizar_mensagem(message: dict[str, Any]) -> dict[str, Any]:
    msg_type = str(message.get("type") or "text")
    normalized: dict[str, Any] = {
        "id": message.get("id"),
        "from": message.get("from"),
        "type": msg_type,
        "text": _texto_da_mensagem(message),
        "raw": message,
    }
    if msg_type in ("image", "document", "audio"):
        media = message.get(msg_type) or {}
        normalized.update(
            {
                "media_id": media.get("id"),
                "mime_type": media.get("mime_type"),
                "caption": media.get("caption"),
            }
        )
    if msg_type == "interactive":
        normalized["interactive"] = message.get("interactive") or {}
    return normalized


def _iter_messages(payload: dict[str, Any]):
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for message in value.get("messages", []) or []:
                yield message


async def processar_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Processa payload Meta API pelo novo orchestrator."""
    resultados: list[dict[str, Any]] = []
    for message in _iter_messages(payload):
        phone = str(message.get("from") or "")
        if not phone:
            logger.warning("Mensagem Meta sem telefone no adapter v2: %s", message.get("id"))
            continue
        resultado = await processar_turno(phone=phone, mensagem=_normalizar_mensagem(message))
        resultados.append(
            {
                "phone": phone,
                "message_id": message.get("id"),
                "sucesso": resultado.sucesso,
                "novo_estado": resultado.novo_estado,
                "mensagens": [m.model_dump() for m in resultado.mensagens_enviadas],
                "erro": resultado.erro,
            }
        )
    return {"status": "ok", "agent": "v2", "resultados": resultados}

