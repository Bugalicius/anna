from __future__ import annotations

from app.conversation_v2.models import AcaoAutorizada, TipoAcao
from app.conversation_v2.response_writer import escrever


def test_response_writer_processa_acoes_em_sequencia_dict() -> None:
    acao = AcaoAutorizada(
        tipo=TipoAcao.enviar_mensagem,
        dados={
            "acoes_em_sequencia": {
                "1_texto": {"tipo": "enviar_texto", "texto": "Oi {primeiro_nome}"},
                "2_delay": {"tipo": "delay", "segundos": 2},
                "3_pdf": {"tipo": "enviar_pdf", "arquivo_dinamico": "guia-{plano}.pdf"},
            }
        },
    )

    mensagens = escrever(acao, {"primeiro_nome": "Maria", "plano": "ouro"})

    assert [m.tipo for m in mensagens] == ["texto", "delay", "pdf"]
    assert mensagens[0].conteudo == "Oi Maria"
    assert mensagens[1].delay_segundos == 2
    assert mensagens[2].arquivo == "guia-ouro.pdf"


def test_response_writer_suporta_botoes_alias_botoes() -> None:
    acao = AcaoAutorizada(
        tipo=TipoAcao.enviar_mensagem,
        dados={
            "acoes_em_sequencia": [
                {
                    "tipo": "enviar_texto",
                    "texto": "Escolha",
                    "botoes": [{"id": "sim", "label": "Sim"}],
                }
            ]
        },
    )

    mensagens = escrever(acao, {})

    assert mensagens[0].tipo == "botoes"
    assert mensagens[0].botoes[0].id == "sim"

