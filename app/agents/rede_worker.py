"""
Agente 4 — Gateway de Pagamento Worker

Gera links de pagamento por cartão de crédito via portal meu.userede.com.br.

Fluxo: login Playwright → navega "Link de Pagamento" → preenche form → captura URL
Exige: REDE_EMAIL + REDE_SENHA no .env
Retorna: URL de checkout hospedada pela Rede (enviável via WhatsApp)

NOTA: Os seletores CSS foram mapeados inspecionando meu.userede.com.br.
Se a Rede alterar o HTML, ajuste as constantes em _SELETORES abaixo.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Tabela de valores por plano e modalidade ──────────────────────────────────

VALORES_PLANOS: dict[str, dict[str, float]] = {
    "premium": {"presencial": 1200.00, "online": 1080.00},
    "ouro": {"presencial": 690.00, "online": 570.00},
    "com_retorno": {"presencial": 480.00, "online": 400.00},
    "unica": {"presencial": 260.00, "online": 220.00},
    "formulario": {"presencial": 100.00, "online": 100.00},
}

PARCELAS_PLANOS: dict[str, int] = {
    "premium": 10,
    "ouro": 6,
    "com_retorno": 4,
    "unica": 3,
    "formulario": 2,
}

# ── Seletores do portal meu.userede.com.br ────────────────────────────────────
# Ajustar se a Rede atualizar o HTML do portal.

_PORTAL_URL = "https://meu.userede.com.br"

_SELETORES = {
    # Tela de login
    "login_email":    'input[name="username"], input[type="email"], #username',
    "login_senha":    'input[name="password"], input[type="password"], #password',
    "login_botao":    'button[type="submit"], input[type="submit"]',

    # Menu / navegação para "Link de Pagamento"
    "menu_link_pag":  'a[href*="link"], a:has-text("Link de Pagamento"), '
                      'span:has-text("Link de Pagamento")',

    # Formulário de criação do link
    "form_valor":      'input[name="amount"], input[placeholder*="valor"], #amount',
    "form_descricao":  'input[name="description"], input[placeholder*="descri"], #description',
    "form_parcelas":   'select[name="installments"], select[name="parcelas"], #installments',
    "form_validade":   'input[name="expirationDate"], input[placeholder*="validade"], #expirationDate',
    "form_submit":     'button[type="submit"]:has-text("Gerar"), '
                       'button:has-text("Criar Link"), button:has-text("Gerar Link")',

    # Link gerado (após submit)
    "link_gerado":     'input[readonly][value*="http"], a[href*="pagamento"], '
                       '.link-pagamento, [data-testid="payment-link"]',
}

# Cache de sessão Playwright (por processo)
_PORTAL_SESSION: dict = {}


@dataclass
class LinkPagamento:
    url: str | None
    valor: float
    parcelas: int
    sucesso: bool
    erro: str | None = None


def valor_plano(plano: str, modalidade: str) -> float:
    return VALORES_PLANOS.get(plano.lower(), {}).get(modalidade.lower(), 0.0)


def parcelas_plano(plano: str) -> int:
    return PARCELAS_PLANOS.get(plano.lower(), 1)


# ── Geração de link via portal meu.userede.com.br ────────────────────────────

def _gerar_link_portal(
    valor: float,
    parcelas: int,
    descricao: str,
    referencia: str,
) -> LinkPagamento:
    """
    Gera link de pagamento via automação no portal meu.userede.com.br.

    Fluxo:
      1. Abre Chromium headless
      2. Faz login com REDE_EMAIL + REDE_SENHA
      3. Navega para "Link de Pagamento" → "Criar novo link"
      4. Preenche valor, descrição, parcelas e validade (7 dias)
      5. Captura a URL gerada e retorna

    IMPORTANTE: se a Rede mudar o HTML, ajuste _SELETORES acima.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    email = os.environ.get("REDE_EMAIL", "")
    senha = os.environ.get("REDE_SENHA", "")

    if not email or not senha:
        return LinkPagamento(
            url=None, valor=valor, parcelas=parcelas, sucesso=False,
            erro="REDE_EMAIL ou REDE_SENHA não configurados",
        )

    from datetime import datetime, timedelta
    validade = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")
    valor_str = f"{valor:.2f}".replace(".", ",")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # 1. Login
            page.goto(f"{_PORTAL_URL}/login", wait_until="networkidle", timeout=30_000)
            page.fill(_SELETORES["login_email"], email)
            page.fill(_SELETORES["login_senha"], senha)
            page.click(_SELETORES["login_botao"])
            page.wait_for_load_state("networkidle", timeout=20_000)

            if "login" in page.url.lower():
                browser.close()
                return LinkPagamento(
                    url=None, valor=valor, parcelas=parcelas, sucesso=False,
                    erro="Login falhou — verifique REDE_EMAIL e REDE_SENHA",
                )

            # 2. Navega para "Link de Pagamento"
            page.click(_SELETORES["menu_link_pag"], timeout=15_000)
            page.wait_for_load_state("networkidle", timeout=15_000)

            novo_link_btn = page.locator(
                'button:has-text("Novo"), button:has-text("Criar"), a:has-text("Novo Link")'
            )
            if novo_link_btn.count() > 0:
                novo_link_btn.first.click()
                page.wait_for_load_state("networkidle", timeout=10_000)

            # 3. Preenche formulário
            page.fill(_SELETORES["form_valor"], valor_str)

            desc_field = page.locator(_SELETORES["form_descricao"])
            if desc_field.count() > 0:
                desc_field.first.fill(descricao[:100])

            parc_field = page.locator(_SELETORES["form_parcelas"])
            if parc_field.count() > 0:
                parc_field.first.select_option(str(parcelas))

            val_field = page.locator(_SELETORES["form_validade"])
            if val_field.count() > 0:
                val_field.first.fill(validade)

            ref_field = page.locator(
                'input[name="reference"], input[placeholder*="referência"], #reference'
            )
            if ref_field.count() > 0:
                ref_field.first.fill(referencia[:50])

            # 4. Submete
            page.click(_SELETORES["form_submit"], timeout=10_000)
            page.wait_for_load_state("networkidle", timeout=20_000)

            # 5. Captura o link gerado
            link_el = page.locator(_SELETORES["link_gerado"])
            link_url = None

            if link_el.count() > 0:
                el = link_el.first
                link_url = el.get_attribute("href") or el.get_attribute("value") or el.inner_text()
                link_url = link_url.strip() if link_url else None

            if not link_url:
                all_links = page.locator("a[href*='pagamento'], a[href*='link'], a[href*='checkout']")
                if all_links.count() > 0:
                    link_url = all_links.first.get_attribute("href")

            browser.close()

            if not link_url:
                return LinkPagamento(
                    url=None, valor=valor, parcelas=parcelas, sucesso=False,
                    erro="Link não encontrado na página após submissão — ajustar _SELETORES['link_gerado']",
                )

            logger.info("Link Rede gerado: %s...", link_url[:60])
            return LinkPagamento(url=link_url, valor=valor, parcelas=parcelas, sucesso=True)

    except PWTimeout as e:
        logger.error("Timeout no portal Rede: %s", e)
        return LinkPagamento(
            url=None, valor=valor, parcelas=parcelas, sucesso=False,
            erro=f"Timeout ao navegar no portal: {e}",
        )
    except Exception as e:
        logger.error("Erro no portal Rede: %s", e)
        return LinkPagamento(url=None, valor=valor, parcelas=parcelas, sucesso=False, erro=str(e))


# ── Interface principal do Agente 4 ──────────────────────────────────────────

def gerar_link_pagamento(
    plano: str,
    modalidade: str,
    referencia: str,
) -> LinkPagamento:
    """
    Função principal do Agente 4.
    Gera link de pagamento via portal meu.userede.com.br.

    Args:
        plano:      "premium" | "ouro" | "com_retorno" | "unica" | "formulario"
        modalidade: "presencial" | "online"
        referencia: ID único do agendamento (para rastreamento)

    Returns:
        LinkPagamento com .url contendo o link para enviar ao paciente
    """
    valor = valor_plano(plano, modalidade)
    parcelas = parcelas_plano(plano)

    if valor == 0:
        return LinkPagamento(
            url=None, valor=0, parcelas=1, sucesso=False,
            erro=f"Plano '{plano}' / modalidade '{modalidade}' não encontrado na tabela de valores",
        )

    descricao = f"Nutricionista Thaynara Teixeira — {plano.title()} {modalidade.title()}"
    return _gerar_link_portal(valor, parcelas, descricao, referencia)
