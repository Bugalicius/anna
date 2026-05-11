from __future__ import annotations

from app.conversation_v2.models import Estado, Fluxo, Situacao, TipoAcao
from app.conversation_v2 import state_machine


def _fluxo_mock() -> Fluxo:
    return Fluxo(
        fluxo_id="mock_fluxo",
        estado_inicial="inicio",
        estados={
            "inicio": Estado(
                descricao="estado inicial",
                situacoes={
                    "nome_ok": Situacao(
                        trigger="intent=informar_nome",
                        resposta="Prazer!",
                        proximo_estado="fim",
                        salva_no_estado={"collected_data.nome": "{nome_extraido}"},
                    )
                },
            ),
            "fim": Estado(descricao="fim"),
        },
    )


def test_proxima_acao_transicao_basica(monkeypatch) -> None:
    monkeypatch.setattr(state_machine.config, "get_fluxo", lambda _: _fluxo_mock())
    acao = state_machine.proxima_acao(
        estado_atual="inicio",
        intent="informar_nome",
        entities={"nome_extraido": "Maria"},
        fluxo_id="mock_fluxo",
    )
    assert acao is not None
    assert acao.tipo == TipoAcao.enviar_mensagem
    assert acao.proximo_estado == "fim"
    assert acao.salvar_no_estado["collected_data.nome"] == "Maria"


def test_proxima_acao_retorna_none_sem_match(monkeypatch) -> None:
    monkeypatch.setattr(state_machine.config, "get_fluxo", lambda _: _fluxo_mock())
    acao = state_machine.proxima_acao(
        estado_atual="inicio",
        intent="intent_desconhecida",
        entities={},
        fluxo_id="mock_fluxo",
    )
    assert acao is None

