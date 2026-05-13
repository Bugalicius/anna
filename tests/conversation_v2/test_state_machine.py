from __future__ import annotations

from app.conversation.models import Estado, Fluxo, Situacao, TipoAcao
from app.conversation import state_machine


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


def test_trigger_in_e_flag_booleana() -> None:
    ctx = {"intent": "remarcar", "passaram_24h_sem_resposta": True}
    assert state_machine._avaliar_trigger(
        "intent IN [agendar_consulta, remarcar] AND passaram_24h_sem_resposta",
        ctx,
    ) is True


def test_action_sem_prefixo_resolve_tool_registrada(monkeypatch) -> None:
    fluxo = Fluxo(
        fluxo_id="mock_fluxo",
        estado_inicial="inicio",
        estados={
            "inicio": Estado(
                situacoes={
                    "comprovante": Situacao(
                        trigger="intent=confirmar_pagamento",
                        action="encaminhar_comprovante_thaynara",
                    )
                }
            )
        },
    )
    monkeypatch.setattr(state_machine.config, "get_fluxo", lambda _: fluxo)

    acao = state_machine.proxima_acao(
        estado_atual="inicio",
        intent="confirmar_pagamento",
        entities={},
        fluxo_id="mock_fluxo",
    )

    assert acao is not None
    assert acao.tipo == TipoAcao.executar_tool
    assert acao.tool_a_executar == "encaminhar_comprovante_thaynara"


def test_action_tool_prefixo_resolve_registry_alias(monkeypatch) -> None:
    fluxo = Fluxo(
        fluxo_id="mock_fluxo",
        estados={
            "inicio": Estado(
                situacoes={
                    "imagem": Situacao(
                        trigger="intent=mandou_imagem",
                        action="tool_analisar_imagem",
                    )
                }
            )
        },
    )
    monkeypatch.setattr(state_machine.config, "get_fluxo", lambda _: fluxo)

    acao = state_machine.proxima_acao(
        estado_atual="inicio",
        intent="mandou_imagem",
        entities={},
        fluxo_id="mock_fluxo",
    )

    assert acao is not None
    assert acao.tool_a_executar == "classificar_imagem"


def test_salva_no_estado_preserva_placeholder_ausente(monkeypatch) -> None:
    fluxo = Fluxo(
        fluxo_id="mock_fluxo",
        estados={
            "inicio": Estado(
                situacoes={
                    "ok": Situacao(
                        trigger="intent=ok",
                        salva_no_estado={"collected_data.nome": "{nome_extraido}"},
                    )
                }
            )
        },
    )
    monkeypatch.setattr(state_machine.config, "get_fluxo", lambda _: fluxo)

    acao = state_machine.proxima_acao(
        estado_atual="inicio",
        intent="ok",
        entities={},
        fluxo_id="mock_fluxo",
    )

    assert acao is not None
    assert acao.salvar_no_estado["collected_data.nome"] == "{nome_extraido}"
