"""
Testes de alinhamento comportamental da Ana (D-18, D-19, D-21).

Cobertura:
  test_waiting_indicator_antes_de_dietbox     — D-21: primeiro item é "Um instante"
  test_waiting_indicator_antes_de_pagamento   — D-21: waiting indicator ao gerar link
  test_waiting_indicator_antes_de_cadastro    — D-21: waiting indicator ao cadastrar Dietbox
  test_msg_boas_vindas_tom_informal           — D-18: saudação informal com emoji
  test_agendamento_nunca_mesmo_dia            — D-19: slots nunca no dia atual
  test_formulario_nunca_oferecido_proativamente — regra de negócio
  test_faq_aprendido_salva_e_carrega          — D-11: salvar_faq_aprendido persiste
  test_faq_aprendido_atualiza_duplicata       — D-11: mesma pergunta atualiza resposta
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Test: waiting indicator antes de operação Dietbox ─────────────────────────

def test_waiting_indicator_antes_de_dietbox():
    """D-21: _iniciar_agendamento retorna 'Um instante' ou similar como primeiro item."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990001", phone_hash="hash001")
    agente.etapa = "agendamento"
    agente.modalidade = "presencial"
    agente.plano_escolhido = "unica"

    slots_mock = [
        {"data_fmt": "15/04/2026", "hora": "09:00", "datetime": "2026-04-15T09:00"},
        {"data_fmt": "16/04/2026", "hora": "10:00", "datetime": "2026-04-16T10:00"},
    ]

    with patch("app.agents.atendimento.consultar_slots_disponiveis", return_value=slots_mock):
        respostas = agente._iniciar_agendamento()

    assert len(respostas) >= 2, "Deve ter ao menos 2 mensagens (waiting + opções)"
    primeira = respostas[0].lower()
    assert any(kw in primeira for kw in ["instante", "minutinho", "aguarda"]), (
        f"Primeira mensagem deve ser waiting indicator, obteve: '{respostas[0]}'"
    )


def test_waiting_indicator_antes_de_pagamento_cartao():
    """D-21: _etapa_forma_pagamento retorna waiting indicator como primeiro item (cartão)."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990002", phone_hash="hash002")
    agente.etapa = "forma_pagamento"
    agente.modalidade = "online"
    agente.plano_escolhido = "unica"
    agente.nome = "Maria"
    agente.slot_escolhido = {"data_fmt": "15/04/2026", "hora": "09:00", "datetime": "2026-04-15T09:00"}

    link_result = MagicMock()
    link_result.sucesso = True
    link_result.url = "https://pay.example.com/link"
    link_result.parcelas = 3
    link_result.parcela_valor = 73.0

    with patch("app.agents.atendimento.gerar_link_pagamento", return_value=link_result):
        respostas = agente._etapa_forma_pagamento("cartão")

    assert len(respostas) >= 2, "Deve ter ao menos 2 mensagens (waiting + link)"
    primeira = respostas[0].lower()
    assert any(kw in primeira for kw in ["instante", "minutinho", "aguarda"]), (
        f"Primeira mensagem deve ser waiting indicator, obteve: '{respostas[0]}'"
    )


def test_waiting_indicator_antes_de_cadastro_dietbox():
    """D-21: _etapa_cadastro_dietbox retorna waiting indicator como primeiro item."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990003", phone_hash="hash003")
    agente.etapa = "cadastro_dietbox"
    agente.modalidade = "presencial"
    agente.plano_escolhido = "unica"
    agente.nome = "Joana"
    agente.pagamento_confirmado = True
    agente.slot_escolhido = {
        "data_fmt": "15/04/2026",
        "hora": "09:00",
        "datetime": "2026-04-15T09:00",
    }

    resultado_mock = {
        "sucesso": True,
        "id_paciente": 12345,
        "id_agenda": "agenda-001",
    }

    with patch("app.agents.atendimento.processar_agendamento", return_value=resultado_mock):
        respostas = agente._etapa_cadastro_dietbox("ok")

    # Primeiro item deve ser waiting indicator
    assert len(respostas) >= 1
    primeira = respostas[0].lower()
    assert any(kw in primeira for kw in ["instante", "minutinho", "aguarda"]), (
        f"Primeira mensagem deve ser waiting indicator, obteve: '{respostas[0]}'"
    )


def test_cadastro_dietbox_falha_nao_confirma_consulta():
    """Falha no Dietbox não deve avançar para confirmação/finalização."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990007", phone_hash="hash007")
    agente.etapa = "cadastro_dietbox"
    agente.modalidade = "presencial"
    agente.plano_escolhido = "unica"
    agente.nome = "Joana"
    agente.pagamento_confirmado = True
    agente.slot_escolhido = {
        "data_fmt": "15/04/2026",
        "hora": "09:00",
        "datetime": "2026-04-15T09:00:00",
    }

    with patch("app.agents.atendimento.processar_agendamento", return_value={"sucesso": False, "erro": "Dietbox offline"}):
        respostas = agente._etapa_cadastro_dietbox("ok")

    texto = " ".join(respostas).lower()
    assert agente.etapa == "cadastro_dietbox"
    assert "não foi confirmado" in texto or "problema técnico" in texto


# ── Test: tom e mensagens ─────────────────────────────────────────────────────

def test_msg_boas_vindas_tom_informal():
    """D-18: MSG_BOAS_VINDAS usa tom informal e tem emoji."""
    from app.agents.atendimento import MSG_BOAS_VINDAS

    msg_lower = MSG_BOAS_VINDAS.lower()

    # Deve ter algum indicador de informalidade/acolhimento
    informal_keywords = ["oi", "ei", "olá", "ana", "sou a ana"]
    assert any(kw in msg_lower for kw in informal_keywords), (
        f"MSG_BOAS_VINDAS deve ter tom informal, obteve: '{MSG_BOAS_VINDAS[:100]}'"
    )

    # Deve ter emoji
    # O 💚 é um emoji comum no projeto
    assert "💚" in MSG_BOAS_VINDAS or "😊" in MSG_BOAS_VINDAS or "🌿" in MSG_BOAS_VINDAS, (
        "MSG_BOAS_VINDAS deve ter pelo menos um emoji"
    )


def test_agendamento_nunca_mesmo_dia():
    """D-19: slots oferecidos nunca incluem o dia atual (date filtering)."""
    from datetime import datetime, date, timedelta, timezone

    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990004", phone_hash="hash004")
    agente.etapa = "agendamento"
    agente.modalidade = "presencial"
    agente.plano_escolhido = "unica"

    # Inclui o dia de hoje deliberadamente
    hoje = datetime.now().date()
    amanha = hoje + timedelta(days=1)

    slots_com_hoje = [
        {
            "data_fmt": hoje.strftime("%d/%m/%Y"),
            "hora": "14:00",
            "datetime": hoje.strftime("%Y-%m-%d") + "T14:00",
        },
        {
            "data_fmt": amanha.strftime("%d/%m/%Y"),
            "hora": "09:00",
            "datetime": amanha.strftime("%Y-%m-%d") + "T09:00",
        },
    ]

    with patch("app.agents.atendimento.consultar_slots_disponiveis", return_value=slots_com_hoje):
        respostas = agente._iniciar_agendamento()

    # Junta todas as respostas para verificar
    texto_completo = " ".join(respostas)

    # O dia de hoje NÃO deve aparecer nas opções de horário
    assert hoje.strftime("%d/%m/%Y") not in texto_completo, (
        f"Slot do dia {hoje} não deve ser oferecido! Respostas: {respostas}"
    )


def test_formulario_nunca_oferecido_proativamente():
    """Regra: nenhuma MSG_* contém 'formulário' sendo oferecido proativamente."""
    from app.agents import atendimento

    # Lista todas as constantes MSG_* do módulo
    msg_constantes = {
        nome: getattr(atendimento, nome)
        for nome in dir(atendimento)
        if nome.startswith("MSG_") and isinstance(getattr(atendimento, nome), str)
    }

    # Nenhuma deve mencionar formulário proativamente (exceto MSG_ERRO_PAGAMENTO que é fallback)
    proibidos_em = []
    for nome, valor in msg_constantes.items():
        if "formulário" in valor.lower() or "formulario" in valor.lower():
            # MSG_ERRO_PAGAMENTO faz fallback para PIX — não oferece formulário proativamente
            # Verificar que não está sendo oferecido como opção primária
            proibidos_em.append(nome)

    assert len(proibidos_em) == 0, (
        f"As seguintes MSG_* mencionam 'formulário' proativamente: {proibidos_em}"
    )


def test_apresentacao_planos_modalidade_sem_plano_pede_plano():
    """Se a paciente informa só modalidade, deve manter contexto e pedir o plano."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990005", phone_hash="hash005")
    agente.etapa = "apresentacao_planos"
    agente.nome = "Breno"
    agente.historico = [{"role": "assistant", "content": "Qual modalidade faz mais sentido pra você agora?"}]

    respostas = agente._etapa_apresentacao_planos("presencial")

    assert agente.modalidade == "presencial"
    texto = " ".join(str(r) for r in respostas)
    assert "qual plano" in texto.lower()
    assert "consulta única" in texto.lower() or "plano ouro" in texto.lower()


def test_escolha_plano_duvida_parcelamento_mantem_etapa():
    """Dúvida de parcelamento após upsell não deve quebrar o fluxo nem avançar etapa."""
    from app.agents.atendimento import AgenteAtendimento

    agente = AgenteAtendimento(telefone="5531999990006", phone_hash="hash006")
    agente.etapa = "escolha_plano"
    agente.plano_escolhido = "unica"
    agente.modalidade = "presencial"
    agente.upsell_oferecido = True

    respostas = agente._etapa_escolha_plano("estou em dúvida, divide no cartão?")

    assert agente.etapa == "escolha_plano"
    texto = " ".join(respostas).lower()
    assert "cartão" in texto or "cartao" in texto
    assert "consulta única" in texto
    assert "plano ouro" in texto


# ── Test: FAQ aprendido ───────────────────────────────────────────────────────

def test_faq_aprendido_salva_e_carrega(tmp_path):
    """D-11: salvar_faq_aprendido persiste e faq_combinado inclui a resposta."""
    faq_file = tmp_path / "faq_aprendido.json"

    with patch("app.knowledge_base._FAQ_APRENDIDO_FILE", faq_file):
        from app.knowledge_base import salvar_faq_aprendido, KnowledgeBase

        salvar_faq_aprendido("Posso comer pizza?", "Com moderação, sim!")

        # Verificar que foi salvo
        assert faq_file.exists()
        dados = json.loads(faq_file.read_text(encoding="utf-8"))
        assert len(dados) == 1
        assert dados[0]["pergunta"] == "Posso comer pizza?"
        assert dados[0]["resposta"] == "Com moderação, sim!"
        assert dados[0]["source"] == "breno_relay"

        # Verificar que faq_combinado inclui
        kb = KnowledgeBase()
        combinado = kb.faq_combinado()
        perguntas = [item["pergunta"] for item in combinado]
        assert "Posso comer pizza?" in perguntas, (
            "FAQ aprendido deve aparecer em faq_combinado()"
        )


def test_faq_aprendido_atualiza_duplicata(tmp_path):
    """D-11: mesma pergunta atualiza resposta em vez de duplicar."""
    faq_file = tmp_path / "faq_aprendido.json"

    with patch("app.knowledge_base._FAQ_APRENDIDO_FILE", faq_file):
        from app.knowledge_base import salvar_faq_aprendido

        salvar_faq_aprendido("Pode comer arroz?", "Sim, pode!")
        salvar_faq_aprendido("Pode comer arroz?", "Sim, pode com feijão!")

        dados = json.loads(faq_file.read_text(encoding="utf-8"))
        # Deve ter apenas 1 entrada (sem duplicata)
        assert len(dados) == 1
        # Resposta deve ser a atualizada
        assert dados[0]["resposta"] == "Sim, pode com feijão!"


def test_faq_aprendido_vazio_nao_quebra(tmp_path):
    """faq_combinado não quebra quando faq_aprendido.json não existe."""
    faq_file = tmp_path / "faq_aprendido_nao_existe.json"

    with patch("app.knowledge_base._FAQ_APRENDIDO_FILE", faq_file):
        from app.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        combinado = kb.faq_combinado()
        assert isinstance(combinado, list)
        assert len(combinado) >= 1  # FAQ estático sempre presente
