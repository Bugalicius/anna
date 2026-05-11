from __future__ import annotations

from app.conversation_v2.models import Mensagem
from app.conversation_v2.output_validator import validar


def test_output_validator_bloqueia_numero_breno_em_contato() -> None:
    result = validar(
        [Mensagem(tipo="contato", conteudo="Contato interno", numero_contato="5531992059211")],
        {},
    )

    assert result.aprovado is False
    assert result.usou_fallback is True
    assert any(v.regra == "R1_nunca_expor_breno" for v in result.violacoes)


def test_output_validator_valida_legenda_de_imagem() -> None:
    result = validar(
        [Mensagem(tipo="imagem", conteudo="Fale com Breno para ver isso")],
        {},
    )

    assert result.aprovado is False
    assert any(v.regra == "R1_nunca_expor_breno" for v in result.violacoes)

