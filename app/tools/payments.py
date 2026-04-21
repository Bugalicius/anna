"""Tools de pagamento — wrapper async sobre rede_worker."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def gerar_link(plano: str, modalidade: str, phone_hash: str) -> dict:
    """Gera link de pagamento via cartão (Rede portal)."""
    from app.integrations.payment_gateway import gerar_link_pagamento
    from datetime import datetime, timedelta, timezone

    BRT = timezone(timedelta(hours=-3))
    ref = f"{phone_hash[:12]}-{datetime.now(BRT).strftime('%Y%m%d%H%M')}"
    try:
        resultado = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: gerar_link_pagamento(plano=plano, modalidade=modalidade, referencia=ref),
        )
        if resultado.sucesso and resultado.url:
            return {
                "sucesso": True,
                "link_url": resultado.url,
                "parcelas": resultado.parcelas,
                "parcela_valor": resultado.parcela_valor,
            }
        return {"sucesso": False, "erro": resultado.erro}
    except Exception as e:
        logger.error("Erro ao gerar link pagamento: %s", e)
        return {"sucesso": False, "erro": str(e)}
