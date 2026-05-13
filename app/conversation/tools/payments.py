from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.conversation.config_loader import config
from app.conversation.tools import ToolResult

logger = logging.getLogger(__name__)


class GerarLinkPagamentoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plano: str
    modalidade: Literal["presencial", "online"]
    phone_hash: str


class AnalisarComprovanteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imagem_bytes: bytes
    mime_type: str
    plano: str
    modalidade: Literal["presencial", "online"]


class EncaminharComprovanteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    imagem_bytes: bytes
    resumo_formatado: str
    mime_type: str = "image/jpeg"


def _valor_plano_pix(plano: str, modalidade: str) -> float:
    plano_cfg = config.get_plano(plano)
    if modalidade == "presencial":
        return float(plano_cfg.valores.pix_presencial)
    return float(plano_cfg.valores.pix_online)


def _classificar_situacao(valor: float, valor_sinal: float, valor_total: float) -> tuple[str, float]:
    if valor >= valor_total:
        return "total_quitado", max(0.0, round(valor_total - valor, 2))
    if abs(valor - valor_sinal) < 0.01:
        return "exato_sinal", round(valor_total - valor, 2)
    if valor > valor_sinal:
        return "acima_sinal", round(valor_total - valor, 2)
    return "abaixo_sinal", round(valor_sinal - valor, 2)


async def gerar_link_pagamento(plano: str, modalidade: str, phone_hash: str) -> ToolResult:
    """Gera link via Rede."""
    from app.tools.payments import gerar_link

    try:
        resultado = await gerar_link(plano=plano, modalidade=modalidade, phone_hash=phone_hash)
        if not resultado.get("sucesso"):
            return ToolResult(sucesso=False, erro=resultado.get("erro") or "Falha ao gerar link")
        return ToolResult(
            sucesso=True,
            dados={
                "url": resultado.get("link_url"),
                "parcelas": int(resultado.get("parcelas") or 0),
                "parcela_valor": float(resultado.get("parcela_valor") or 0),
            },
        )
    except Exception as exc:
        logger.exception("Erro ao gerar link de pagamento: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def analisar_comprovante(
    imagem_bytes: bytes,
    mime_type: str,
    plano: str,
    modalidade: str,
) -> ToolResult:
    """
    Analisa comprovante PIX via Gemini Vision.
    """
    from app.media_handler import analisar_comprovante_pagamento_async

    try:
        analise = await analisar_comprovante_pagamento_async(imagem_bytes, mime_type)
        eh_comprovante = bool(analise.get("eh_comprovante"))
        valor = analise.get("valor")
        favorecido = analise.get("favorecido")
        if not eh_comprovante or valor is None:
            return ToolResult(
                sucesso=True,
                dados={
                    "eh_comprovante": False,
                    "valor": None,
                    "favorecido": favorecido,
                    "situacao": "ilegivel",
                    "valor_restante": None,
                },
            )

        valor = float(valor)
        valor_total = _valor_plano_pix(plano=plano, modalidade=modalidade)
        valor_sinal = round(valor_total * 0.5, 2)
        situacao, restante = _classificar_situacao(valor, valor_sinal, valor_total)
        return ToolResult(
            sucesso=True,
            dados={
                "eh_comprovante": True,
                "valor": valor,
                "favorecido": favorecido,
                "situacao": situacao,
                "valor_restante": restante,
                "valor_sinal": valor_sinal,
                "valor_total": valor_total,
            },
        )
    except Exception as exc:
        logger.exception("Erro ao analisar comprovante: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))


async def encaminhar_comprovante_thaynara(
    imagem_bytes: bytes,
    resumo_formatado: str,
    mime_type: str = "image/jpeg",
) -> ToolResult:
    """Envia comprovante + resumo para Thaynara."""
    from app.meta_api import MetaAPIClient

    try:
        numero = str(config.get_numero("thaynara").get("phone", "5531991394759"))
        client = MetaAPIClient()
        await client.encaminhar_midia(
            to=numero,
            image_bytes=imagem_bytes,
            mime_type=mime_type,
            caption=resumo_formatado,
        )
        return ToolResult(sucesso=True, dados={"destino": numero, "encaminhado": True})
    except Exception as exc:
        logger.exception("Erro ao encaminhar comprovante para Thaynara: %s", exc)
        return ToolResult(sucesso=False, erro=str(exc))
