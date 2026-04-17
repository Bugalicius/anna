"""
Agente 4 — Gateway de Pagamento Worker

Gera links de pagamento por cartão de crédito via portal meu.userede.com.br.

Fluxo: login Playwright → navega "Link de Pagamento" → preenche form → captura URL
Exige: REDE_EMAIL + REDE_SENHA no .env
Retorna: URL de checkout hospedada pela Rede (enviável via WhatsApp)

Seletores mapeados em 2026-04-07 inspecionando meu.userede.com.br.
Se a Rede alterar o HTML, ajuste a função _gerar_link_portal_sync.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ── Tabelas de valores por plano e modalidade ─────────────────────────────────
# PIX: valor com desconto (pago à vista)
# Cartão: valor por parcela × número de parcelas = total cobrado no link

VALORES_PLANOS_PIX: dict[str, dict[str, float]] = {
    "premium":     {"presencial": 1200.00, "online": 1080.00},
    "ouro":        {"presencial":  690.00, "online":  570.00},
    "com_retorno": {"presencial":  480.00, "online":  400.00},
    "unica":       {"presencial":  260.00, "online":  220.00},
    "formulario":  {"presencial":  100.00, "online":  100.00},
}

# Valor por parcela no cartão
PARCELA_PLANOS: dict[str, dict[str, float]] = {
    "premium":     {"presencial": 140.00, "online": 126.00},
    "ouro":        {"presencial": 128.00, "online": 106.00},
    "com_retorno": {"presencial": 130.00, "online": 109.00},
    "unica":       {"presencial":  93.00, "online":  79.00},
    "formulario":  {"presencial":  53.00, "online":  53.00},
}

PARCELAS_PLANOS: dict[str, int] = {
    "premium":     10,
    "ouro":         6,
    "com_retorno":  4,
    "unica":        3,
    "formulario":   2,
}

# Retrocompatibilidade — usado por código externo que referencia VALORES_PLANOS
VALORES_PLANOS = VALORES_PLANOS_PIX

_PORTAL_URL = "https://meu.userede.com.br"
_PV = "101801637"  # Código do estabelecimento Rede


# ── Dataclass de retorno ──────────────────────────────────────────────────────

@dataclass
class LinkPagamento:
    url: str | None
    valor: float        # total cobrado no link (cartão) ou PIX se sem link
    parcelas: int
    sucesso: bool
    parcela_valor: float = 0.0  # valor por parcela (para exibição)
    erro: str | None = None


# ── Helpers de tabela ─────────────────────────────────────────────────────────

def valor_plano(plano: str, modalidade: str) -> float:
    """Valor PIX (à vista com desconto)."""
    return VALORES_PLANOS_PIX.get(plano.lower(), {}).get(modalidade.lower(), 0.0)


def valor_plano_cartao(plano: str, modalidade: str) -> float:
    """Valor total cobrado no cartão (parcela × num_parcelas)."""
    p = PARCELA_PLANOS.get(plano.lower(), {}).get(modalidade.lower(), 0.0)
    n = PARCELAS_PLANOS.get(plano.lower(), 1)
    return round(p * n, 2)


def parcela_plano(plano: str, modalidade: str) -> float:
    """Valor por parcela no cartão."""
    return PARCELA_PLANOS.get(plano.lower(), {}).get(modalidade.lower(), 0.0)


def parcelas_plano(plano: str) -> int:
    return PARCELAS_PLANOS.get(plano.lower(), 1)


# ── Geração de link via portal meu.userede.com.br ────────────────────────────

def _gerar_link_portal(
    valor: float,
    parcelas: int,
    descricao: str,
    referencia: str,
) -> "LinkPagamento":
    """
    Executa a geração de link no portal usando ThreadPoolExecutor para
    evitar conflito com o event loop do asyncio (FastAPI).
    """
    from datetime import datetime, timedelta
    import concurrent.futures

    email = os.environ.get("REDE_EMAIL", "")
    senha = os.environ.get("REDE_SENHA", "")

    if not email or not senha:
        return LinkPagamento(
            url=None, valor=valor, parcelas=parcelas, sucesso=False,
            erro="REDE_EMAIL ou REDE_SENHA não configurados",
        )

    validade = (datetime.now() + timedelta(days=7)).strftime("%m/%d/%Y")
    valor_str = f"{valor:.2f}".replace(".", ",")

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                _gerar_link_portal_sync,
                valor, parcelas, descricao, referencia, email, senha, validade, valor_str,
            )
            return future.result(timeout=180)
    except Exception as e:
        logger.error("Erro no portal Rede: %s", e)
        return LinkPagamento(url=None, valor=valor, parcelas=parcelas, sucesso=False, erro=str(e))


def _gerar_link_portal_sync(
    valor: float, parcelas: int, descricao: str, referencia: str,
    email: str, senha: str, validade: str, valor_str: str,
) -> "LinkPagamento":
    """
    Automação Playwright no portal meu.userede.com.br.

    Fluxo confirmado em 2026-04-07:
      1. Login (headless=False obrigatório — reCAPTCHA bloqueia headless=True)
      2. Remove overlay joyride
      3. Navega para /link-pagamento via menu JS
      4. Fecha modal "obrigado" e survey de satisfação
      5. Preenche Nome, Valor, Prazo (7 dias), Parcelas
      6. Clica "Criar link de pagamento" (dentro de shadow DOM — usa get_by_text)
      7. Captura URL do link a partir da resposta da API
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    link_url: str | None = None

    def on_response(resp):
        nonlocal link_url
        # Captura resposta da criação do link
        if (
            "payment-link" in resp.url
            and "pv=" in resp.url
            and resp.request.method == "POST"
        ):
            try:
                body = resp.json()
                if "url" in body and "paymentLinkId" in body:
                    link_url = body["url"]
                    logger.info("Link Rede capturado da API: %s", link_url)
            except Exception:
                pass

    try:
        with sync_playwright() as p:
            # headless=False: obrigatório, portal usa reCAPTCHA que bloqueia headless=True
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.on("response", on_response)

            # ── 1. Login ──────────────────────────────────────────────────────
            page.goto(f"{_PORTAL_URL}/login", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3000)

            # Clica "Acessar conta" para mostrar o formulário
            page.locator("button:has-text('Acessar conta')").first.click()
            page.wait_for_timeout(2000)

            # Dispensa modal "Agora não" se aparecer
            agora = page.locator("button:has-text('Agora')")
            if agora.count() > 0:
                agora.first.click()
                page.wait_for_timeout(1000)

            page.fill("#ids-input-0", email)
            page.fill("#ids-input-1", senha)
            page.locator("button.ids-main-button:not(.ids-main-button--secondary)").first.click()

            try:
                page.wait_for_url("**/home", timeout=25_000)
            except PWTimeout:
                pass
            page.wait_for_timeout(5000)

            if "/home" not in page.url:
                browser.close()
                return LinkPagamento(
                    url=None, valor=valor, parcelas=parcelas, sucesso=False,
                    erro="Login falhou — verifique REDE_EMAIL e REDE_SENHA",
                )
            logger.info("Login Rede OK")

            # ── 2. Remove overlay joyride ─────────────────────────────────────
            page.evaluate(
                "document.querySelectorAll('.joyride-backdrop, .backdrop-container, "
                "[id*=\"backdrop\"]').forEach(el => el.remove())"
            )
            page.wait_for_timeout(500)

            # ── 3. Navega para Link de Pagamento ──────────────────────────────
            page.evaluate("document.querySelector('#menu-recebimentos')?.click()")
            page.wait_for_timeout(500)
            page.evaluate(
                "([...document.querySelectorAll('a')].find(a => "
                "a.textContent.trim().toLowerCase().includes('link de pagamento')))?.click()"
            )
            page.wait_for_timeout(5000)

            if "link-pagamento" not in page.url:
                page.goto(
                    f"{_PORTAL_URL}/link-pagamento",
                    wait_until="domcontentloaded", timeout=20_000,
                )
                page.wait_for_timeout(5000)

            logger.info("Pagina link-pagamento OK: %s", page.url)

            # ── 4. Fecha modais ───────────────────────────────────────────────
            _fechar_modais(page)
            page.wait_for_timeout(800)

            # ── 5. Preenche formulário ────────────────────────────────────────
            nome_field = page.get_by_role("textbox", name="Nome do produto")
            nome_field.first.wait_for(state="visible", timeout=15_000)
            nome_field.first.fill(descricao[:100])

            valor_field = page.get_by_role("textbox", name="Valor do link")
            if valor_field.count() == 0:
                valor_field = page.get_by_role("textbox", name="Informe um valor")
            valor_field.first.fill(valor_str)
            page.wait_for_timeout(500)

            # ── 6. Prazo de vencimento (7 dias) ───────────────────────────────
            prazo_el = page.locator("dsr-input-select[formcontrolname='linkDuration']")
            prazo_el.first.scroll_into_view_if_needed()
            prazo_el.first.click()
            page.wait_for_timeout(1200)
            # Escopo no elemento para piercear apenas o shadow DOM do dropdown
            prazo_el.locator("text=7 dias").first.click()
            page.wait_for_timeout(500)

            # ── 7. Limite de parcelas ─────────────────────────────────────────
            page.evaluate("window.scrollTo(0, 400)")
            page.wait_for_timeout(500)

            parc_el = page.locator("dsr-input-select[formcontrolname='installments']")
            parc_el.first.scroll_into_view_if_needed()
            parc_el.first.click()
            page.wait_for_timeout(1200)

            # Opção tem formato "em até Nx de R$ xx,xx" — escopo no elemento
            parc_opt = parc_el.locator(f"text=em até {parcelas}x")
            if parc_opt.count() == 0:
                parc_opt = parc_el.locator(f"text=em até {parcelas}")
            parc_opt.first.click()
            page.wait_for_timeout(500)

            # ── 8. Fecha survey que pode aparecer durante o preenchimento ─────
            _fechar_modais(page)
            page.wait_for_timeout(500)

            # ── 9. Clica "Criar link de pagamento" ────────────────────────────
            # O botão está dentro de shadow DOM — get_by_text pierca automaticamente
            criar = page.get_by_text("Criar link de pagamento", exact=True)
            criar.first.click()

            # Aguarda resposta da API (capturada em on_response)
            page.wait_for_timeout(12_000)

            browser.close()

            if not link_url:
                return LinkPagamento(
                    url=None, valor=valor, parcelas=parcelas, sucesso=False,
                    erro="Link não retornado pela API — verificar seletores ou estado do form",
                )

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


def _fechar_modais(page) -> None:
    """Fecha overlay joyride, modal 'obrigado' e survey de satisfação."""
    # Modal "obrigado" (fim do tutorial joyride)
    for sel in ["a:has-text('obrigado')", "button:has-text('obrigado')"]:
        el = page.locator(sel)
        if el.count() > 0 and el.first.is_visible():
            el.first.click()
            page.wait_for_timeout(600)

    # Survey de satisfação (Muito boa / Boa / Nem boa...)
    page.keyboard.press("Escape")
    survey = page.locator(
        "button:has-text('Muito boa'), button:has-text('Boa'), button:has-text('Nem boa')"
    )
    if survey.count() > 0 and survey.first.is_visible():
        survey.first.click()
        page.wait_for_timeout(800)
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)


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
    parcelas = parcelas_plano(plano)
    parcela  = parcela_plano(plano, modalidade)
    valor_cartao = valor_plano_cartao(plano, modalidade)

    if valor_cartao == 0:
        return LinkPagamento(
            url=None, valor=0, parcelas=1, parcela_valor=0, sucesso=False,
            erro=f"Plano '{plano}' / modalidade '{modalidade}' não encontrado",
        )

    descricao = f"Nutricionista Thaynara Teixeira — {plano.title()} {modalidade.title()}"
    result = _gerar_link_portal(valor_cartao, parcelas, descricao, referencia)
    result.parcela_valor = parcela
    return result
