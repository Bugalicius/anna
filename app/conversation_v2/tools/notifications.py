from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from typing import Any

from app.conversation_v2.config_loader import config
from app.conversation_v2.tools import ToolResult

logger = logging.getLogger(__name__)
BRT = timezone(timedelta(hours=-3))

_ESCALACOES_PENDENTES: dict[str, dict[str, Any]] = {}


async def notificar_breno(mensagem: str) -> ToolResult:
    """Envia mensagem ao Breno via Meta API."""
    from app.meta_api import MetaAPIClient

    try:
        numero = str(config.get_numero("breno").get("phone", "5531992059211"))
        client = MetaAPIClient()
        await client.send_text(to=numero, text=mensagem)
        return ToolResult(sucesso=True, dados={"destino": numero})
    except Exception as exc:
        logger.exception("Erro ao notificar Breno: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def notificar_thaynara(mensagem: str, anexo_imagem: bytes | None = None) -> ToolResult:
    """Envia mensagem para Thaynara e anexo opcional."""
    from app.meta_api import MetaAPIClient

    try:
        numero = str(config.get_numero("thaynara").get("phone", "5531991394759"))
        client = MetaAPIClient()
        if anexo_imagem:
            await client.encaminhar_midia(
                to=numero,
                image_bytes=anexo_imagem,
                mime_type="image/jpeg",
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
    notificacao = await notificar_breno(mensagem)
    if not notificacao.sucesso:
        return ToolResult(
            sucesso=False,
            erro=notificacao.erro,
            dados={"escalacao_id": escala_id, "registro_criado": True},
        )
    return ToolResult(
        sucesso=True,
        dados={"escalacao_id": escala_id, "registro": registro, "notificado": True},
    )

