"""
Testes do Agente 2 — Retenção (todos com mock onde necessário).
Cobre: calcular_fim_janela, serialização/deserialização de novos campos,
       _detectar_tipo_remarcacao.
"""
from datetime import date
from unittest.mock import patch, MagicMock

import pytest


# ── calcular_fim_janela ───────────────────────────────────────────────────────

def test_calcular_fim_janela_terça():
    """Consulta terça 14/abr/2026 (semana 13-17/abr) → sexta da semana seguinte = 24/abr."""
    from app.agents.retencao import calcular_fim_janela
    resultado = calcular_fim_janela(date(2026, 4, 14))
    assert resultado == date(2026, 4, 24)


def test_calcular_fim_janela_sexta():
    """Consulta sexta 17/abr/2026 → semana seguinte começa 20/abr → sexta = 24/abr."""
    from app.agents.retencao import calcular_fim_janela
    resultado = calcular_fim_janela(date(2026, 4, 17))
    assert resultado == date(2026, 4, 24)


def test_calcular_fim_janela_segunda():
    """Consulta segunda 20/abr/2026 → semana seguinte começa 27/abr → sexta = 01/mai."""
    from app.agents.retencao import calcular_fim_janela
    resultado = calcular_fim_janela(date(2026, 4, 20))
    assert resultado == date(2026, 5, 1)


# ── AgenteRetencao.from_dict — novos campos opcionais ────────────────────────

def test_from_dict_sem_rodada_negociacao_usa_zero():
    """from_dict com dict sem rodada_negociacao → rodada_negociacao = 0 (não quebra)."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao.from_dict({
        "_tipo": "retencao",
        "telefone": "5531999990000",
        "nome": "Ana",
        "etapa": "inicio",
    })
    assert agent.rodada_negociacao == 0


def test_from_dict_sem_tipo_remarcacao_usa_none():
    """from_dict com dict sem tipo_remarcacao → tipo_remarcacao = None."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao.from_dict({
        "_tipo": "retencao",
        "telefone": "5531999990000",
        "nome": "Ana",
        "etapa": "inicio",
    })
    assert agent.tipo_remarcacao is None


def test_to_dict_inclui_novos_campos():
    """to_dict deve incluir rodada_negociacao, _slots_pool, tipo_remarcacao, id_agenda_original."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.rodada_negociacao = 2
    agent.tipo_remarcacao = "retorno"
    agent.id_agenda_original = "AGENDA-001"
    agent._slots_pool = [{"datetime": "2026-04-24T09:00:00"}]

    d = agent.to_dict()
    assert "rodada_negociacao" in d
    assert d["rodada_negociacao"] == 2
    assert "_slots_pool" in d
    assert "tipo_remarcacao" in d
    assert d["tipo_remarcacao"] == "retorno"
    assert "id_agenda_original" in d
    assert d["id_agenda_original"] == "AGENDA-001"


# ── _detectar_tipo_remarcacao ─────────────────────────────────────────────────

def test_detectar_tipo_remarcacao_sem_paciente_retorna_nova_consulta():
    """buscar_paciente_por_telefone retorna None → tipo = 'nova_consulta'."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")

    with patch("app.agents.retencao.buscar_paciente_por_telefone", return_value=None):
        tipo = agent._detectar_tipo_remarcacao()

    assert tipo == "nova_consulta"
    assert agent.tipo_remarcacao == "nova_consulta"


def test_detectar_tipo_remarcacao_paciente_sem_lancamento_retorna_nova_consulta():
    """Paciente encontrado mas verificar_lancamento_financeiro=False → 'nova_consulta'."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")

    agenda_mock = {
        "id": "AGENDA-001",
        "inicio": "2026-04-24T09:00:00",
        "fim": "2026-04-24T10:00:00",
        "id_servico": "SVC-001",
    }

    with patch("app.agents.retencao.buscar_paciente_por_telefone",
               return_value={"id": 42, "nome": "Ana", "telefone": "5531999990000"}), \
         patch("app.agents.retencao.consultar_agendamento_ativo", return_value=agenda_mock), \
         patch("app.agents.retencao.verificar_lancamento_financeiro", return_value=False):
        tipo = agent._detectar_tipo_remarcacao()

    assert tipo == "nova_consulta"
    assert agent.tipo_remarcacao == "nova_consulta"


def test_detectar_tipo_remarcacao_paciente_com_lancamento_retorna_retorno():
    """Paciente encontrado, agenda ativa e lançamento financeiro → tipo = 'retorno'."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")

    agenda_mock = {
        "id": "AGENDA-001",
        "inicio": "2026-04-24T09:00:00",
        "fim": "2026-04-24T10:00:00",
        "id_servico": "SVC-001",
    }

    with patch("app.agents.retencao.buscar_paciente_por_telefone",
               return_value={"id": 42, "nome": "Ana", "telefone": "5531999990000"}), \
         patch("app.agents.retencao.consultar_agendamento_ativo", return_value=agenda_mock), \
         patch("app.agents.retencao.verificar_lancamento_financeiro", return_value=True):
        tipo = agent._detectar_tipo_remarcacao()

    assert tipo == "retorno"
    assert agent.tipo_remarcacao == "retorno"
    assert agent.id_agenda_original == "AGENDA-001"
    assert agent.fim_janela is not None
