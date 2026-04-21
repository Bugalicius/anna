"""Integrations — Gateway de pagamento. Re-exporta o worker existente."""
from app.agents.rede_worker import gerar_link_pagamento, LinkPagamento

__all__ = ["gerar_link_pagamento", "LinkPagamento"]
