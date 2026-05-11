from __future__ import annotations

from app.conversation_v2.rules import (
    R1_nunca_expor_breno,
    R3_nunca_inventar_valor,
    R12_validar_nome_nao_generico,
)


def test_r1_bloqueia_texto_com_breno() -> None:
    result = R1_nunca_expor_breno("Pode falar com o Breno no 5531992059211")
    assert result.passou is False


def test_r3_bloqueia_valor_divergente() -> None:
    result = R3_nunca_inventar_valor(
        "O valor é R$ 999,00 para esse plano.",
        valores_validos=[260.0, 440.0, 690.0, 1200.0],
    )
    assert result.passou is False


def test_r12_bloqueia_nome_generico_consulta() -> None:
    result = R12_validar_nome_nao_generico("consulta")
    assert result.passou is False

