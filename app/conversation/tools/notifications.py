from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.conversation.config_loader import config
from app.conversation.tools import ToolResult
from app.conversation.alerter_simples import (
    alertar_breno,
    alertar_duvida_clinica,
    alertar_escalacao,
    alertar_loop_mensagem,
)

logger = logging.getLogger(__name__)
BRT = timezone(timedelta(hours=-3))

_ESCALACOES_PENDENTES: dict[str, dict[str, Any]] = {}


class NotificarBrenoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mensagem: str


class NotificarThaynaraInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mensagem: str
    anexo_imagem: bytes | None = None
    mime_type: str = "image/jpeg"


class EscalarBrenoSilenciosoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contexto: dict[str, Any]


async def notificar_breno(mensagem: str) -> ToolResult:
    """Envia mensagem simples ao Breno sem bloquear o fluxo do agente."""
    await alertar_breno(mensagem)
    return ToolResult(sucesso=True, dados={"destino": "breno"})


async def notificar_thaynara(
    mensagem: str,
    anexo_imagem: bytes | None = None,
    mime_type: str = "image/jpeg",
) -> ToolResult:
    """Envia mensagem para Thaynara e anexo opcional."""
    from app.meta_api import MetaAPIClient

    try:
        numero = str(config.get_numero("thaynara").get("phone", "5531991394759"))
        client = MetaAPIClient()
        if anexo_imagem:
            await client.encaminhar_midia(
                to=numero,
                image_bytes=anexo_imagem,
                mime_type=mime_type,
                caption=mensagem,
            )
        else:
            await client.send_text(to=numero, text=mensagem)
        return ToolResult(sucesso=True, dados={"destino": numero, "anexo": bool(anexo_imagem)})
    except Exception as exc:
        logger.exception("Erro ao notificar Thaynara: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def escalar_breno_silencioso(contexto: dict[str, Any]) -> ToolResult:
    """Cria escalação pendente e notifica Breno com contexto do caso."""
    escala_id = f"esc_{uuid4().hex[:12]}"
    registro = {
        "id": escala_id,
        "status": "pendente",
        "criado_em": datetime.now(BRT).isoformat(),
        "contexto": contexto,
    }
    _ESCALACOES_PENDENTES[escala_id] = registro

    mensagem = (
        f"[ESCALACAO SILENCIOSA] id={escala_id}\n"
        f"Contexto:\n{json.dumps(contexto, ensure_ascii=False, default=str)}"
    )
    await _alertar_contexto_escalacao(contexto=contexto, fallback=mensagem)
    return ToolResult(
        sucesso=True,
        dados={"escalacao_id": escala_id, "registro": registro, "notificado": True},
    )


def _valor_contexto(contexto: dict[str, Any], *chaves: str) -> str:
    for chave in chaves:
        valor = contexto.get(chave)
        if valor:
            return str(valor)

    state = contexto.get("state")
    if isinstance(state, dict):
        cd = state.get("collected_data") or {}
        for chave in chaves:
            valor = state.get(chave) or cd.get(chave)
            if valor:
                return str(valor)
    return ""


def _resumo_contexto(contexto: dict[str, Any]) -> str:
    resumo = _valor_contexto(contexto, "resumo", "erro", "ultima_mensagem", "mensagem")
    if resumo:
        return resumo[:500]
    return json.dumps(contexto, ensure_ascii=False, default=str)[:500]


def _is_loop_contexto(contexto: dict[str, Any]) -> bool:
    motivo = _valor_contexto(contexto, "motivo", "reason").lower()
    return "loop_fallback" in motivo or "fallback_loop" in motivo


def _is_duvida_clinica_contexto(contexto: dict[str, Any]) -> bool:
    motivo = _valor_contexto(contexto, "motivo", "reason", "intent").lower()
    return (
        bool(contexto.get("duvida_clinica"))
        or "clinica" in motivo
        or "clínica" in motivo
        or "pergunta_clinica" in motivo
        or motivo == "gestante"
    )


async def _alertar_contexto_escalacao(contexto: dict[str, Any], fallback: str) -> None:
    phone = _valor_contexto(contexto, "telefone", "phone", "whatsapp", "whatsapp_contato")
    nome = _valor_contexto(contexto, "nome", "paciente", "nome_completo")
    motivo = _valor_contexto(contexto, "motivo", "reason") or "agente_nao_soube_responder"

    if _is_loop_contexto(contexto):
        await alertar_loop_mensagem(
            phone=phone,
            nome=nome,
            mensagem_repetida=_valor_contexto(contexto, "resposta_repetida", "mensagem_repetida") or _resumo_contexto(contexto),
        )
        return

    if _is_duvida_clinica_contexto(contexto):
        await alertar_duvida_clinica(
            phone=phone,
            nome=nome,
            pergunta=_valor_contexto(contexto, "pergunta", "mensagem", "ultima_mensagem") or _resumo_contexto(contexto),
        )
        return

    if contexto:
        await alertar_escalacao(
            phone=phone,
            nome=nome,
            motivo=motivo,
            resumo=_resumo_contexto(contexto),
        )
        return

    await alertar_breno(fallback)
