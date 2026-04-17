"""
Testes do Agente 4 — Gateway de Pagamento Worker (todos com mock Playwright).
"""
import os
from unittest.mock import MagicMock, patch

import pytest


# ── valor_plano ───────────────────────────────────────────────────────────────

def test_valor_plano_premium_presencial():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("premium", "presencial") == 1200.00


def test_valor_plano_premium_online():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("premium", "online") == 1080.00


def test_valor_plano_ouro_presencial():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("ouro", "presencial") == 690.00


def test_valor_plano_unica_online():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("unica", "online") == 220.00


def test_valor_plano_formulario():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("formulario", "presencial") == 100.00
    assert valor_plano("formulario", "online") == 100.00


def test_valor_plano_desconhecido_retorna_zero():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("inexistente", "presencial") == 0.0


def test_valor_plano_case_insensitive():
    from app.agents.rede_worker import valor_plano
    assert valor_plano("PREMIUM", "PRESENCIAL") == 1200.00


# ── parcelas_plano ────────────────────────────────────────────────────────────

def test_parcelas_premium():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("premium") == 10


def test_parcelas_ouro():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("ouro") == 6


def test_parcelas_com_retorno():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("com_retorno") == 4


def test_parcelas_unica():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("unica") == 3


def test_parcelas_formulario():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("formulario") == 2


def test_parcelas_desconhecido_retorna_1():
    from app.agents.rede_worker import parcelas_plano
    assert parcelas_plano("inexistente") == 1


# ── gerar_link_pagamento ──────────────────────────────────────────────────────

def test_gerar_link_sucesso():
    """Portal Rede via Playwright retorna URL de checkout."""
    link_fake = "https://meu.userede.com.br/link/pagamento/abc123"

    with patch("app.agents.rede_worker._gerar_link_portal") as mock_portal:
        from app.agents.rede_worker import LinkPagamento
        mock_portal.return_value = LinkPagamento(
            url=link_fake, valor=690.00, parcelas=6, sucesso=True,
        )

        from app.agents.rede_worker import gerar_link_pagamento
        result = gerar_link_pagamento(
            plano="ouro",
            modalidade="presencial",
            referencia="AGD-001",
        )

    assert result.sucesso is True
    assert result.url == link_fake
    assert result.valor == 690.00
    assert result.parcelas == 6


def test_gerar_link_sem_credenciais():
    """Sem REDE_EMAIL/REDE_SENHA retorna erro."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("REDE_EMAIL", "REDE_SENHA")}

    with patch.dict(os.environ, env, clear=True):
        from app.agents.rede_worker import gerar_link_pagamento
        result = gerar_link_pagamento(
            plano="ouro",
            modalidade="presencial",
            referencia="AGD-002",
        )

    assert result.sucesso is False
    assert result.erro is not None
    assert "REDE_EMAIL" in result.erro or "REDE_SENHA" in result.erro


def test_gerar_link_falha_playwright():
    """Erro no Playwright retorna LinkPagamento com sucesso=False."""
    with patch("app.agents.rede_worker._gerar_link_portal") as mock_portal:
        from app.agents.rede_worker import LinkPagamento
        mock_portal.return_value = LinkPagamento(
            url=None, valor=690.00, parcelas=6, sucesso=False, erro="Timeout ao navegar",
        )

        from app.agents.rede_worker import gerar_link_pagamento
        result = gerar_link_pagamento(
            plano="ouro",
            modalidade="presencial",
            referencia="AGD-003",
        )

    assert result.sucesso is False
    assert result.erro is not None


def test_gerar_link_plano_invalido():
    from app.agents.rede_worker import gerar_link_pagamento
    result = gerar_link_pagamento(
        plano="plano_inexistente",
        modalidade="presencial",
        referencia="AGD-004",
    )

    assert result.sucesso is False
    assert result.valor == 0
    assert "não encontrado" in (result.erro or "").lower()


def test_gerar_link_todos_planos_tem_valor():
    """Garante que todos os planos e modalidades retornam valor > 0."""
    from app.agents.rede_worker import valor_plano
    planos = ["premium", "ouro", "com_retorno", "unica", "formulario"]
    for plano in planos:
        for modalidade in ["presencial", "online"]:
            assert valor_plano(plano, modalidade) > 0, f"{plano}/{modalidade} sem valor"
