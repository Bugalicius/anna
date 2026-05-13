"""
Fase 8.1 + 8.2 — Testes E2E com conversas reais.

Seleciona 50 conversas representativas do conversas_export.json e as replaya
pelo orchestrator v2, medindo taxa de respostas semanticamente aceitáveis.

Estrutura:
  - 20 agendamentos
  - 10 remarcações
  - 5 cancelamentos
  - 5 confirmações
  - 10 casos diversos
"""
from __future__ import annotations

import pytest

from tests.conversation_v2.e2e.runner import (
    ConversaResult,
    RunnerResult,
    classificar_conversa,
    executar_bateria,
    load_conversas,
    selecionar_conversas,
)

pytestmark = pytest.mark.asyncio

# ─── Fixture central ─────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def conversas_export():
    """Carrega conversas_export.json uma vez para todo o módulo."""
    try:
        return load_conversas()
    except FileNotFoundError:
        pytest.skip("conversas_export.json não encontrado — pule em CI sem arquivo")


@pytest.fixture(scope="module")
def conversas_selecionadas(conversas_export):
    return selecionar_conversas(
        conversas_export,
        n_agendamento=20,
        n_remarcacao=10,
        n_cancelamento=5,
        n_confirmacao=5,
        n_outros=10,
    )


# ─── 8.1 Seleção de conversas representativas ────────────────────────────────


def test_selecao_quantidade_minima(conversas_selecionadas):
    """Devem ser selecionadas pelo menos 40 conversas (pode ser menos se o export tiver poucos de algum tipo)."""
    assert len(conversas_selecionadas) >= 40, (
        f"Apenas {len(conversas_selecionadas)} conversas selecionadas — esperado >= 40"
    )


def test_selecao_tem_agendamentos(conversas_selecionadas):
    agend = [c for c in conversas_selecionadas if classificar_conversa(c) == "agendamento"]
    assert len(agend) >= 10, f"Apenas {len(agend)} agendamentos — esperado >= 10"


def test_selecao_tem_remarcacoes(conversas_selecionadas):
    remarc = [c for c in conversas_selecionadas if classificar_conversa(c) == "remarcacao"]
    assert len(remarc) >= 3, f"Apenas {len(remarc)} remarcações — esperado >= 3"


def test_selecao_tem_cancelamentos(conversas_selecionadas):
    cancel = [c for c in conversas_selecionadas if classificar_conversa(c) == "cancelamento"]
    assert len(cancel) >= 2, f"Apenas {len(cancel)} cancelamentos — esperado >= 2"


def test_selecao_reproducivel(conversas_export):
    """A seleção com mesmo seed deve ser determinística."""
    a = selecionar_conversas(conversas_export, seed=42)
    b = selecionar_conversas(conversas_export, seed=42)
    ids_a = [c.get("chat", {}).get("id") or c.get("remoteJid") for c in a]
    ids_b = [c.get("chat", {}).get("id") or c.get("remoteJid") for c in b]
    assert ids_a == ids_b, "Seleção não é determinística com mesmo seed"


def test_todas_conversas_tem_msgs_paciente(conversas_selecionadas):
    """Nenhuma conversa selecionada deve ter zero mensagens do paciente."""
    from tests.conversation_v2.e2e.runner import _mensagens_paciente
    for conv in conversas_selecionadas:
        msgs = _mensagens_paciente(conv)
        assert len(msgs) >= 1, f"Conversa {conv.get('remoteJid')} sem mensagens do paciente"


# ─── 8.2 Replay E2E — taxa de sucesso ────────────────────────────────────────


@pytest.fixture(scope="module")
def resultado_bateria(conversas_selecionadas) -> RunnerResult:
    """Roda o replay de todas as conversas selecionadas (uma vez por módulo)."""
    import asyncio
    return asyncio.run(executar_bateria(conversas_selecionadas))


def test_taxa_sucesso_global(resultado_bateria: RunnerResult):
    """Taxa de sucesso global deve ser >= 85%."""
    taxa = resultado_bateria.taxa_sucesso_global
    assert taxa >= 0.85, (
        f"Taxa de sucesso global {taxa:.1%} abaixo de 85%.\n"
        f"{resultado_bateria.resumo()}"
    )


def test_sem_erros_criticos(resultado_bateria: RunnerResult):
    """Não deve haver erros críticos (exceções não tratadas) na bateria."""
    assert len(resultado_bateria.erros) == 0, (
        f"Erros críticos na bateria:\n" + "\n".join(resultado_bateria.erros)
    )


def test_taxa_sucesso_agendamentos(resultado_bateria: RunnerResult):
    """Agendamentos devem ter taxa >= 85%."""
    convs = [c for c in resultado_bateria.conversas if c.tipo == "agendamento"]
    if not convs:
        pytest.skip("Nenhuma conversa de agendamento no resultado")
    turnos_total = sum(c.total_turnos for c in convs)
    turnos_ok = sum(c.turnos_aceitos for c in convs)
    taxa = turnos_ok / turnos_total if turnos_total else 0
    assert taxa >= 0.85, f"Taxa agendamentos: {taxa:.1%} < 85%"


def test_taxa_sucesso_remarcacoes(resultado_bateria: RunnerResult):
    """Remarcações devem ter taxa >= 80%."""
    convs = [c for c in resultado_bateria.conversas if c.tipo == "remarcacao"]
    if not convs:
        pytest.skip("Nenhuma conversa de remarcação no resultado")
    turnos_total = sum(c.total_turnos for c in convs)
    turnos_ok = sum(c.turnos_aceitos for c in convs)
    taxa = turnos_ok / turnos_total if turnos_total else 0
    assert taxa >= 0.80, f"Taxa remarcações: {taxa:.1%} < 80%"


def test_taxa_sucesso_cancelamentos(resultado_bateria: RunnerResult):
    """Cancelamentos devem ter taxa >= 80%."""
    convs = [c for c in resultado_bateria.conversas if c.tipo == "cancelamento"]
    if not convs:
        pytest.skip("Nenhuma conversa de cancelamento no resultado")
    turnos_total = sum(c.total_turnos for c in convs)
    turnos_ok = sum(c.turnos_aceitos for c in convs)
    taxa = turnos_ok / turnos_total if turnos_total else 0
    assert taxa >= 0.80, f"Taxa cancelamentos: {taxa:.1%} < 80%"


def test_nenhuma_resposta_expoe_breno(resultado_bateria: RunnerResult):
    """R1: nenhuma resposta pode conter número ou nome interno do Breno."""
    violacoes = [
        (c.conversa_id, t.turno_idx, t.motivo_rejeicao)
        for c in resultado_bateria.conversas
        for t in c.turnos
        if t.motivo_rejeicao and "R1_breno" in t.motivo_rejeicao
    ]
    assert len(violacoes) == 0, f"Violações R1 encontradas: {violacoes}"


def test_latencia_media_aceitavel(resultado_bateria: RunnerResult):
    """Latência média por turno deve ser < 2000 ms (com tools mockadas)."""
    assert resultado_bateria.latencia_media_ms < 2000, (
        f"Latência média {resultado_bateria.latencia_media_ms:.0f} ms está alta "
        "(tools mockadas — checar gargalo no orchestrator)"
    )


def test_turnos_totais_minimo(resultado_bateria: RunnerResult):
    """Pelo menos 100 turnos devem ter sido processados no total."""
    assert resultado_bateria.turnos_totais >= 100, (
        f"Apenas {resultado_bateria.turnos_totais} turnos processados — esperado >= 100"
    )


# ─── Análise de falhas ────────────────────────────────────────────────────────


def test_falhas_nao_sao_sistematicas(resultado_bateria: RunnerResult):
    """
    Falhas de LÓGICA não devem estar concentradas num único tipo de motivo.

    Exclui falhas de infraestrutura (excecao:*) que são esperadas em ambiente
    de teste sem LLM real. Só detecta bugs lógicos do orchestrator v2.
    """
    falhas = [
        t.motivo_rejeicao
        for c in resultado_bateria.conversas
        for t in c.turnos
        if not t.aceitavel
        and t.motivo_rejeicao
        and not t.motivo_rejeicao.startswith("excecao:")  # infra, não lógica
    ]
    if not falhas:
        return  # zero falhas lógicas = passa
    from collections import Counter
    contagem = Counter(falhas)
    mais_comum, n = contagem.most_common(1)[0]
    proporcao = n / len(falhas)
    assert proporcao < 0.5, (
        f"Falha lógica sistemática: '{mais_comum}' = {proporcao:.0%} das falhas. "
        "Isso indica um bug no orchestrator v2."
    )
