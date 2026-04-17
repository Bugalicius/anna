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


def test_detectar_tipo_remarcacao_popula_consulta_atual():
    """Quando tipo='retorno', _detectar_tipo_remarcacao deve preencher self.consulta_atual."""
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
        agent._detectar_tipo_remarcacao()

    # consulta_atual deve estar preenchida com os dados do agendamento encontrado
    assert agent.consulta_atual is not None
    assert agent.consulta_atual["inicio"] == "2026-04-24T09:00:00"


def test_fluxo_remarcacao_inicio_retorno_exibe_data_consulta_atual():
    """Ao iniciar remarcação com agendamento ativo, a resposta deve mostrar a data da consulta atual."""
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
        respostas = agent.processar_remarcacao("quero remarcar mas não lembro minha data")

    texto = " ".join(respostas)
    # A data da consulta (24/04 ou 24 de abril) deve aparecer na resposta
    assert "24/04" in texto or "24" in texto


def test_fluxo_remarcacao_inicio_retorno_nao_cai_no_llm():
    """Remarcação com agendamento ativo no Dietbox não deve cair no LLM fallback."""
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
         patch("app.agents.retencao.verificar_lancamento_financeiro", return_value=True), \
         patch("app.agents.retencao._gerar_resposta_llm_retencao") as mock_llm:
        agent.processar_remarcacao("quero remarcar mas não sei minha data")

    # LLM não deve ser chamado — a resposta é determinística
    mock_llm.assert_not_called()


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


# ── Fluxo de negociação — 2 rodadas + perda de retorno ───────────────────────

def _agent_com_slots(num_slots: int = 6) -> "AgenteRetencao":
    """Cria AgenteRetencao já em etapa 'oferecendo_slots' com pool pré-preenchido."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "oferecendo_slots"
    # Cria pool de slots em dias variados
    agent._slots_pool = [_make_slot(i % 5, 9 + (i % 3)) for i in range(num_slots)]
    # Slots oferecidos = os 3 primeiros do pool
    agent._slots_oferecidos = agent._slots_pool[:3]
    return agent


def test_rejeicao_primeira_rodada_oferece_segunda_rodada():
    """Rejeição com rodada_negociacao=0 e pool com mais slots → rodada 2 com novos 3 slots."""
    agent = _agent_com_slots(num_slots=6)
    assert agent.rodada_negociacao == 0

    # Mensagem sem número ou data válida = rejeição
    respostas = agent.processar_remarcacao("nenhum desses me serve")

    assert agent.rodada_negociacao == 1
    assert agent.etapa == "oferecendo_slots"
    # Resposta deve conter a segunda rodada
    texto = " ".join(respostas)
    assert any(c.isdigit() for c in texto)  # contém opções numeradas


def test_rejeicao_segunda_rodada_declara_perda_retorno():
    """Rejeição com rodada_negociacao=1 → etapa 'perda_retorno' e MSG_PERDA_RETORNO."""
    agent = _agent_com_slots(num_slots=6)
    agent.rodada_negociacao = 1

    respostas = agent.processar_remarcacao("não gostei de nenhum")

    assert agent.etapa == "perda_retorno"
    texto = " ".join(respostas)
    assert "prazo" in texto.lower() or "retorno" in texto.lower()


def test_etapa_perda_retorno_oferece_nova_consulta():
    """Na etapa 'perda_retorno', qualquer msg → redirecionando_atendimento."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "perda_retorno"

    respostas = agent.processar_remarcacao("ok, quero agendar nova consulta")

    assert agent.etapa == "redirecionando_atendimento"
    texto = " ".join(respostas)
    assert len(texto) > 0


def test_pool_com_so_3_slots_rejeicao_declara_perda_direto():
    """Pool com apenas 3 slots — rejeição → sem next_batch → perda_retorno direta."""
    agent = _agent_com_slots(num_slots=3)
    assert agent.rodada_negociacao == 0

    respostas = agent.processar_remarcacao("nenhum desses funciona pra mim")

    assert agent.etapa == "perda_retorno"


def test_escolha_valida_segunda_rodada_confirma_normalmente():
    """Paciente escolhe slot na rodada 2 → etapa vai para aguardando_confirmacao_dietbox ou concluido."""
    agent = _agent_com_slots(num_slots=6)
    agent.rodada_negociacao = 1

    respostas = agent.processar_remarcacao("1")

    # Escolheu → não deve declarar perda de retorno
    assert agent.etapa != "perda_retorno"
    texto = " ".join(respostas)
    assert len(texto) > 0


def test_msg_inicio_remarcacao_nao_cita_data_calculada():
    """MSG_INICIO_REMARCACAO contém '7 dias' e 'prazo máximo' mas não cita data ISO."""
    from app.agents.retencao import MSG_INICIO_REMARCACAO

    assert "7 dias" in MSG_INICIO_REMARCACAO
    assert "prazo máximo" in MSG_INICIO_REMARCACAO
    # Não deve conter padrão de data ISO (YYYY-MM-DD) embutida no template
    import re
    assert not re.search(r'\d{4}-\d{2}-\d{2}', MSG_INICIO_REMARCACAO)


# ── Etapa aguardando_confirmacao_dietbox ──────────────────────────────────────

def _agent_aguardando_confirmacao(id_agenda: str = "ID-999") -> "AgenteRetencao":
    """Cria AgenteRetencao já em etapa 'aguardando_confirmacao_dietbox' com novo_slot."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "aguardando_confirmacao_dietbox"
    agent.id_agenda_original = id_agenda
    agent.modalidade = "presencial"
    agent.novo_slot = {
        "datetime": "2026-04-21T09:00:00",
        "data_fmt": "segunda, 21/04",
        "hora": "9h",
    }
    agent.consulta_atual = {"inicio": "2026-04-14T09:00:00"}
    return agent


def test_escolha_slot_muda_etapa_para_aguardando_confirmacao():
    """Paciente escolhe slot válido → etapa 'aguardando_confirmacao_dietbox', novo_slot salvo, retorna espera."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "oferecendo_slots"
    agent.id_agenda_original = "ID-999"
    agent._slots_pool = [_make_slot(0, 9), _make_slot(1, 10), _make_slot(2, 14)]
    agent._slots_oferecidos = agent._slots_pool[:3]

    respostas = agent.processar_remarcacao("1")

    assert agent.etapa == "aguardando_confirmacao_dietbox"
    assert agent.novo_slot is not None
    assert "instante" in " ".join(respostas).lower() or "💚" in " ".join(respostas)


def test_aguardando_confirmacao_sucesso_dietbox_retorna_confirmacao():
    """Na etapa aguardando_confirmacao_dietbox com alterar_agendamento=True → etapa concluido, retorna confirmação."""
    agent = _agent_aguardando_confirmacao()

    with patch("app.agents.retencao.alterar_agendamento", return_value=True):
        respostas = agent.processar_remarcacao("qualquer msg")

    assert agent.etapa == "concluido"
    texto = " ".join(respostas)
    assert "remarcada" in texto.lower() or "sucesso" in texto.lower()


def test_aguardando_confirmacao_falha_dietbox_retorna_erro():
    """Na etapa aguardando_confirmacao_dietbox com alterar_agendamento=False → etapa erro_remarcacao, sem confirmação falsa."""
    agent = _agent_aguardando_confirmacao()

    with patch("app.agents.retencao.alterar_agendamento", return_value=False):
        respostas = agent.processar_remarcacao("qualquer msg")

    assert agent.etapa == "erro_remarcacao"
    texto = " ".join(respostas)
    # Não deve conter "✅" (confirmação falsa)
    assert "✅" not in texto
    # Deve informar sobre o problema técnico
    assert "problema" in texto.lower() or "técnico" in texto.lower() or "dificuldade" in texto.lower()


def test_aguardando_confirmacao_sem_id_agenda_retorna_erro():
    """Na etapa aguardando_confirmacao_dietbox com id_agenda_original=None → trata como erro, retorna MSG_ERRO_REMARCACAO_DIETBOX."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "aguardando_confirmacao_dietbox"
    agent.id_agenda_original = None
    agent.novo_slot = {
        "datetime": "2026-04-21T09:00:00",
        "data_fmt": "segunda, 21/04",
        "hora": "9h",
    }

    # Quando id_agenda_original é None, chama alterar_agendamento com "" → retorna False
    with patch("app.agents.retencao.alterar_agendamento", return_value=False):
        respostas = agent.processar_remarcacao("qualquer msg")

    assert agent.etapa == "erro_remarcacao"
    assert "✅" not in " ".join(respostas)


def test_aguardando_confirmacao_sucesso_contem_data_hora_slot():
    """MSG_CONFIRMACAO_REMARCACAO retornada contém data_fmt e hora do slot escolhido (não hardcoded)."""
    agent = _agent_aguardando_confirmacao()

    with patch("app.agents.retencao.alterar_agendamento", return_value=True):
        respostas = agent.processar_remarcacao("qualquer msg")

    texto = " ".join(respostas)
    assert "21/04" in texto or "segunda" in texto.lower()
    assert "9h" in texto


def test_etapa_erro_remarcacao_retorna_orientacao():
    """Na etapa erro_remarcacao com qualquer mensagem → retorna orientação para contato direto."""
    from app.agents.retencao import AgenteRetencao
    agent = AgenteRetencao(telefone="5531999990000", nome="Ana")
    agent.etapa = "erro_remarcacao"

    respostas = agent.processar_remarcacao("o que aconteceu?")

    texto = " ".join(respostas)
    assert len(texto) > 0
    # Deve orientar o paciente a entrar em contato
    assert "thaynara" in texto.lower() or "contato" in texto.lower() or "dificuldade" in texto.lower()
