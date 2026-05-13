"""
Interceptador de imagens — classifica ANTES de qualquer ação do fluxo principal.

Cenários tratados:
  1. Sticker → "Hihi 💚 Como posso te ajudar?"  (determinístico, sem LLM)
  2. Comprovante de pagamento (4 subcenários):
       a. Exato sinal         → aprova + saldo restante
       b. Acima sinal/abaixo total → aprova + saldo restante
       c. Total quitado       → aprova "quitado"
       d. Abaixo sinal        → pede complemento + não encaminha Thaynara
     Todos os aprovados: encaminha imagem + resumo à Thaynara.
  3. Imagem não-comprovante quando estado=aguardando_pagamento_pix
       → "Hmm, essa imagem não parece ser um comprovante..."
  4. Imagem não-comprovante em outro contexto
       → "Recebo comprovantes de pagamento por aqui 😊..."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_NUMERO_THAYNARA = "5531991394759"


@dataclass
class InterceptResult:
    interceptado: bool
    mensagens: list[dict[str, Any]] = field(default_factory=list)
    salvar_no_estado: dict[str, Any] = field(default_factory=dict)
    proximo_estado: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Entrada principal
# ─────────────────────────────────────────────────────────────────────────────

async def interceptar_imagem(mensagem: dict[str, Any], state: dict[str, Any]) -> InterceptResult:
    """
    Verifica se a mensagem é imagem/sticker e, se for, intercepta antes do fluxo.
    Retorna InterceptResult(interceptado=False) se não houver intercepção.
    """
    tipo_mensagem = str(mensagem.get("type") or mensagem.get("message_type") or "")
    image_bytes: bytes = mensagem.get("image_bytes") or mensagem.get("bytes") or b""
    mime_type: str = mensagem.get("mime_type") or "image/jpeg"
    media_id: str = str(mensagem.get("media_id") or "")

    # 1. Sticker — determinístico, sem LLM
    if tipo_mensagem == "sticker":
        return InterceptResult(
            interceptado=True,
            mensagens=[{"tipo": "texto", "conteudo": "Hihi 💚 Como posso te ajudar?"}],
        )

    # Não é imagem → sem intercepção
    if tipo_mensagem not in ("image", "document"):
        return InterceptResult(interceptado=False)

    # Se não temos bytes mas temos media_id, tentamos baixar
    if not image_bytes and media_id:
        image_bytes, mime_type = await _baixar_midia(media_id, mime_type)

    if not image_bytes:
        return InterceptResult(interceptado=False)

    return await _processar_imagem(image_bytes, mime_type, state)


# ─────────────────────────────────────────────────────────────────────────────
# Download de mídia
# ─────────────────────────────────────────────────────────────────────────────

async def _baixar_midia(media_id: str, mime_fallback: str) -> tuple[bytes, str]:
    import asyncio
    try:
        from app.media_handler import download_media
        loop = asyncio.get_event_loop()
        content, mime = await loop.run_in_executor(None, lambda: download_media(media_id))
        return content, mime or mime_fallback
    except Exception as exc:
        logger.warning("Falha ao baixar midia media_id=%s: %s", media_id, exc)
        return b"", mime_fallback


# ─────────────────────────────────────────────────────────────────────────────
# Classificação e roteamento
# ─────────────────────────────────────────────────────────────────────────────

async def _processar_imagem(
    image_bytes: bytes, mime_type: str, state: dict[str, Any]
) -> InterceptResult:
    from app.conversation.tools.registry import call_tool

    cd = state.get("collected_data") or {}
    plano = str(cd.get("plano") or "ouro")
    modalidade = str(cd.get("modalidade") or "presencial")

    try:
        result = await call_tool(
            "analisar_comprovante",
            {
                "imagem_bytes": image_bytes,
                "mime_type": mime_type,
                "plano": plano,
                "modalidade": modalidade,
            },
        )
    except Exception as exc:
        logger.exception("Erro ao analisar imagem no interceptor: %s", exc)
        return InterceptResult(interceptado=False)

    if not result.sucesso:
        return InterceptResult(interceptado=False)

    dados = result.dados
    eh_comprovante = bool(dados.get("eh_comprovante"))

    if not eh_comprovante:
        return _resposta_nao_comprovante(state)

    return await _processar_comprovante(dados, state, image_bytes, mime_type)


def _resposta_nao_comprovante(state: dict[str, Any]) -> InterceptResult:
    estado_atual = str(state.get("estado") or "")
    if estado_atual == "aguardando_pagamento_pix":
        return InterceptResult(
            interceptado=True,
            mensagens=[{
                "tipo": "texto",
                "conteudo": (
                    "Hmm, essa imagem não parece ser um comprovante 😅\n"
                    "Pode me mandar a tela do PIX confirmado?"
                ),
            }],
        )
    return InterceptResult(
        interceptado=True,
        mensagens=[{
            "tipo": "texto",
            "conteudo": "Recebo comprovantes de pagamento por aqui 😊\nPosso te ajudar com mais alguma coisa?",
        }],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validação e resposta de comprovante
# ─────────────────────────────────────────────────────────────────────────────

async def _processar_comprovante(
    dados: dict[str, Any],
    state: dict[str, Any],
    image_bytes: bytes,
    mime_type: str,
) -> InterceptResult:
    from app.conversation.tools.registry import call_tool

    situacao = str(dados.get("situacao") or "ilegivel")
    valor = float(dados.get("valor") or 0)
    valor_sinal = float(dados.get("valor_sinal") or 0)
    valor_total = float(dados.get("valor_total") or 0)
    valor_restante = float(dados.get("valor_restante") or 0)

    cd = state.get("collected_data") or {}
    nome = str(cd.get("nome") or "Paciente")
    plano = str(cd.get("plano") or "")
    modalidade = str(cd.get("modalidade") or "")

    # Ilegível / erro → escala Breno, responde paciente
    if situacao == "ilegivel":
        await call_tool(
            "escalar_breno_silencioso",
            {"contexto": {"motivo": "comprovante_ilegivel", "plano": plano, "modalidade": modalidade}},
        )
        return InterceptResult(
            interceptado=True,
            mensagens=[{
                "tipo": "texto",
                "conteudo": "Recebi seu comprovante! Deixa eu confirmar com a equipe e já te respondo 💚",
            }],
        )

    # Abaixo do sinal mínimo → não aprova, pede complemento
    if situacao == "abaixo_sinal":
        falta = round(valor_sinal - valor, 2)
        return InterceptResult(
            interceptado=True,
            mensagens=[{
                "tipo": "texto",
                "conteudo": (
                    f"Recebi seu comprovante de R$ {valor:.2f}, mas o sinal mínimo é R$ {valor_sinal:.2f} 💚\n"
                    f"Pode me mandar mais R$ {falta:.2f} pra completar?\n\n"
                    "Chave PIX (CPF): 14994735670"
                ),
            }],
        )

    # Aprovado — monta texto e encaminha para Thaynara
    if situacao == "total_quitado":
        texto_paciente = f"Recebi pagamento integral de R$ {valor:.2f}! ✅\nTudo quitado, sem saldo a acertar 💚"
        resumo_tipo = "✅ Pago integral - quitado"
    else:  # exato_sinal ou acima_sinal
        texto_paciente = f"Recebi R$ {valor:.2f}! ✅\nFalta R$ {valor_restante:.2f} pra acertar no dia da consulta."
        resumo_tipo = f"⚠️ Sinal pago, saldo de R$ {valor_restante:.2f} a acertar no dia"

    resumo = (
        f"🧾 Comprovante recebido\n\n"
        f"👤 Paciente: {nome}\n"
        f"💰 Valor: R$ {valor:.2f}\n"
        f"📋 Plano: {plano} ({modalidade})\n"
        f"{resumo_tipo}"
    )

    try:
        await call_tool(
            "encaminhar_comprovante_thaynara",
            {
                "imagem_bytes": image_bytes,
                "resumo_formatado": resumo,
                "mime_type": mime_type,
            },
        )
    except Exception as exc:
        logger.exception("Erro ao encaminhar comprovante para Thaynara: %s", exc)

    salvar: dict[str, Any] = {
        "flags.pagamento_confirmado": True,
        "collected_data.valor_pago_sinal": valor,
    }
    if situacao == "total_quitado":
        salvar["flags.pago_integral"] = True

    # Retorna ao fluxo de agendamento após comprovante aprovado
    estado_atual = str(state.get("estado") or "")
    proximo = "aguardando_cadastro" if estado_atual == "aguardando_pagamento_pix" else None

    return InterceptResult(
        interceptado=True,
        mensagens=[{"tipo": "texto", "conteudo": texto_paciente}],
        salvar_no_estado=salvar,
        proximo_estado=proximo,
    )
