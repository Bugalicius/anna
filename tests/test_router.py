"""
Testes do roteamento — Orquestrador (Agente 0).
Todos os testes usam mock do Claude para não fazer chamadas reais à API.
"""
from unittest.mock import MagicMock, patch

import pytest


# ── rotear — primeiro contato ─────────────────────────────────────────────────

def test_primeiro_contato_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="oi", stage_atual=None, primeiro_contato=True)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "novo_lead"


def test_stage_cold_lead_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="quero informações", stage_atual="cold_lead", primeiro_contato=True)
    assert rota["agente"] == "atendimento"


def test_stage_new_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    rota = rotear(mensagem="olá", stage_atual="new", primeiro_contato=True)
    assert rota["agente"] == "atendimento"


# ── rotear — intenções via LLM (mock) ─────────────────────────────────────────

def _mock_classificacao(intencao: str, confianca: float = 0.9):
    """Helper: mocka _classificar_intencao para retornar intenção/confiança fixas."""
    return patch(
        "app.agents.orchestrator._classificar_intencao",
        return_value=(intencao, confianca),
    )


def test_intencao_agendar_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("agendar"):
        rota = rotear("quero marcar uma consulta", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "agendar"


def test_intencao_pagar_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("pagar"):
        rota = rotear("como faço o pagamento?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"


def test_intencao_tirar_duvida_vai_para_atendimento():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("tirar_duvida"):
        rota = rotear("qual o valor da consulta?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"


def test_intencao_remarcar_vai_para_retencao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("remarcar"):
        rota = rotear("preciso remarcar", stage_atual="agendado", primeiro_contato=False)
    assert rota["agente"] == "retencao"
    assert rota["intencao"] == "remarcar"


def test_intencao_cancelar_vai_para_retencao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("cancelar"):
        rota = rotear("quero cancelar minha consulta", stage_atual="agendado", primeiro_contato=False)
    assert rota["agente"] == "retencao"
    assert rota["intencao"] == "cancelar"


def test_intencao_duvida_clinica_vai_para_escalacao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("duvida_clinica"):
        rota = rotear("tenho diabetes posso comer açúcar?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "escalacao"


def test_intencao_fora_de_contexto_retorna_resposta_padrao():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("fora_de_contexto"):
        rota = rotear("qual o resultado do flamengo?", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "padrao"
    assert rota["resposta_padrao"] is not None
    assert len(rota["resposta_padrao"]) > 10


def test_confianca_preenchida():
    from app.agents.orchestrator import rotear
    with _mock_classificacao("agendar", confianca=0.95):
        rota = rotear("quero agendar", stage_atual="presenting", primeiro_contato=False)
    assert rota["confianca"] == pytest.approx(0.95)


def test_fallback_erro_llm_vai_para_atendimento():
    """Se a chamada ao Claude falhar, deve fazer fallback para atendimento (novo_lead)."""
    from app.agents.orchestrator import rotear
    with patch(
        "app.agents.orchestrator._classificar_intencao",
        side_effect=Exception("API error"),
    ):
        rota = rotear("qualquer coisa", stage_atual="presenting", primeiro_contato=False)
    assert rota["agente"] == "atendimento"
    assert rota["intencao"] == "novo_lead"
