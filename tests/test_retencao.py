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


# ── _priorizar_slots ──────────────────────────────────────────────────────────

def _make_slot(weekday: int, hora: int, semana_offset: int = 0) -> dict:
    """Cria um slot de teste com a data correta para o weekday/hora dados."""
    from datetime import date, timedelta
    # Encontra a próxima data com o weekday dado a partir de 2026-04-20 (segunda)
    base = date(2026, 4, 20) + timedelta(weeks=semana_offset)
    delta = (weekday - base.weekday()) % 7
    d = base + timedelta(days=delta)
    _NOMES_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    return {
        "datetime": f"{d.isoformat()}T{hora:02d}:00:00",
        "data_fmt": f"{_NOMES_DIAS[weekday]}, {d.strftime('%d/%m')}",
        "hora": f"{hora}h",
    }


def test_priorizar_slots_com_preferencia_dia_e_hora():
    """Pool tem segunda às 9h → opção 1 é essa segunda; opções 2 e 3 em dias diferentes."""
    from app.agents.retencao import _priorizar_slots

    pool = [
        _make_slot(0, 9),    # segunda 9h ← preferência
        _make_slot(1, 10),   # terça 10h
        _make_slot(2, 14),   # quarta 14h
        _make_slot(3, 8),    # quinta 8h
    ]

    resultado = _priorizar_slots(pool, dia_preferido=0, hora_preferida=9)

    assert len(resultado) == 3
    # primeira opção deve ser segunda às 9h
    from datetime import datetime
    assert datetime.fromisoformat(resultado[0]["datetime"]).weekday() == 0
    assert _make_slot(0, 9)["hora"] == resultado[0]["hora"]
    # os outros 2 devem ser em dias diferentes da opção 1 e entre si
    dias = [datetime.fromisoformat(s["datetime"]).weekday() for s in resultado]
    assert dias[0] != dias[1]
    assert dias[0] != dias[2]


def test_priorizar_slots_com_preferencia_so_dia():
    """Sem hora → opção 1 é qualquer slot de segunda; opções 2 e 3 em outros dias."""
    from app.agents.retencao import _priorizar_slots
    from datetime import datetime

    pool = [
        _make_slot(0, 14),   # segunda 14h ← preferência de dia
        _make_slot(1, 10),   # terça
        _make_slot(2, 8),    # quarta
    ]

    resultado = _priorizar_slots(pool, dia_preferido=0, hora_preferida=None)

    assert len(resultado) == 3
    assert datetime.fromisoformat(resultado[0]["datetime"]).weekday() == 0


def test_priorizar_slots_sem_slot_da_preferencia():
    """Sem slot de segunda no pool → retorna 3 primeiros disponíveis em dias diferentes."""
    from app.agents.retencao import _priorizar_slots
    from datetime import datetime

    pool = [
        _make_slot(1, 9),    # terça
        _make_slot(2, 10),   # quarta
        _make_slot(3, 14),   # quinta
    ]

    resultado = _priorizar_slots(pool, dia_preferido=0, hora_preferida=9)

    assert len(resultado) == 3
    # segunda não está no pool — deve retornar sem mencionar segunda
    dias = [datetime.fromisoformat(s["datetime"]).weekday() for s in resultado]
    assert 0 not in dias  # segunda ausente


def test_priorizar_slots_pool_vazio():
    """Pool vazio → retorna []."""
    from app.agents.retencao import _priorizar_slots

    resultado = _priorizar_slots([], dia_preferido=None, hora_preferida=None)

    assert resultado == []


def test_priorizar_slots_todos_mesmo_dia():
    """Pool com 5 slots todos na terça → retorna até 3 slots (da terça)."""
    from app.agents.retencao import _priorizar_slots

    pool = [_make_slot(1, h) for h in [8, 9, 10, 14, 15]]

    resultado = _priorizar_slots(pool, dia_preferido=None, hora_preferida=None)

    assert len(resultado) == 3  # retorna 3 mesmo que todos no mesmo dia


def test_priorizar_slots_4_dias_diferentes():
    """Pool com slots em 4 dias diferentes → retorna exatamente 3 slots em dias diferentes."""
    from app.agents.retencao import _priorizar_slots
    from datetime import datetime

    pool = [
        _make_slot(1, 9),   # terça
        _make_slot(2, 10),  # quarta
        _make_slot(3, 14),  # quinta
        _make_slot(4, 8),   # sexta
    ]

    resultado = _priorizar_slots(pool, dia_preferido=None, hora_preferida=None)

    assert len(resultado) == 3
    dias = [datetime.fromisoformat(s["datetime"]).weekday() for s in resultado]
    assert len(set(dias)) == 3  # todos em dias diferentes


def test_priorizar_slots_retorna_max_3():
    """Pool grande → retorna no máximo 3 slots."""
    from app.agents.retencao import _priorizar_slots

    pool = [_make_slot(i % 5, 9 + (i % 3)) for i in range(10)]

    resultado = _priorizar_slots(pool, dia_preferido=None, hora_preferida=None)

    assert len(resultado) <= 3
