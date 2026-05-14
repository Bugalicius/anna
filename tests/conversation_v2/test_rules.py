from __future__ import annotations

from app.conversation.rules import (
    R1_nunca_expor_breno,
    R3_nunca_inventar_valor,
    R12_validar_nome_nao_generico,
)


def test_r1_bloqueia_texto_com_breno() -> None:
    result = R1_nunca_expor_breno("Pode falar com o Breno no 5531992059211")
    assert result.passou is False


def test_r1_nao_bloqueia_sobrenome() -> None:
    result = R1_nunca_expor_breno("Pra começar, qual é o seu nome e sobrenome?")
    assert result.passou is True


def test_r1_nao_bloqueia_saudacao_quando_paciente_chama_breno() -> None:
    # Agente cumprimentando paciente cujo nome é Breno — não deve bloquear
    result = R1_nunca_expor_breno("Prazer, Breno! É sua primeira consulta?", nome_paciente="Breno")
    assert result.passou is True


def test_r1_ainda_bloqueia_numero_mesmo_paciente_breno() -> None:
    # Número de contato sempre bloqueado, mesmo que o paciente se chame Breno
    result = R1_nunca_expor_breno("Fale com o Breno no 5531992059211", nome_paciente="Breno")
    assert result.passou is False


def test_r1_bloqueia_nome_breno_sem_contexto_paciente() -> None:
    # Sem nome_paciente informado, a proteção original continua ativa
    result = R1_nunca_expor_breno("Fale com o Breno")
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
