"""
Testes do ConfigLoader — carregamento de YAMLs de configuração.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.conversation.config_loader import ConfigLoader


@pytest.fixture
def loader() -> ConfigLoader:
    """Loader fresco (não usa o singleton global)."""
    l = ConfigLoader()
    l.load()
    return l


def test_global_yaml_carrega(loader: ConfigLoader) -> None:
    """global.yaml carrega sem erros e tem estrutura mínima."""
    cfg = loader.global_config
    assert cfg.identidade["nome"] == "Ana"
    assert "thaynara" in cfg.numeros
    assert "breno" in cfg.numeros
    assert len(cfg.planos) >= 4


def test_todos_fluxos_carregam(loader: ConfigLoader) -> None:
    """Todos os YAMLs de fluxo carregam sem erros."""
    fluxos = loader.list_fluxos()
    arquivos = list((Path("config") / "fluxos").glob("*.yaml"))
    assert len(fluxos) >= len(arquivos), (
        f"Esperado pelo menos {len(arquivos)} fluxos, got {len(fluxos)}: {fluxos}"
    )
    assert "remarcacao" in fluxos
    assert "cancelamento" in fluxos


def test_get_plano_ouro(loader: ConfigLoader) -> None:
    """config.get_plano('ouro') retorna dados corretos."""
    plano = loader.get_plano("ouro")
    assert plano.nome_publico == "Plano Ouro"
    assert plano.consultas == 3
    assert plano.duracao_dias == 130
    assert plano.valores.pix_presencial == 690.00
    assert plano.valores.pix_online == 650.00
    assert plano.valores.cartao_presencial == 750.00
    assert plano.upsell_para == "premium"


def test_get_plano_premium_sem_upsell(loader: ConfigLoader) -> None:
    """Premium não tem upsell (é o teto)."""
    plano = loader.get_plano("premium")
    # O YAML tem upsell_para: NENHUM — normalizamos para None
    assert plano.upsell_para in (None, "NENHUM")


def test_get_plano_inexistente_levanta_keyerror(loader: ConfigLoader) -> None:
    with pytest.raises(KeyError, match="platinum"):
        loader.get_plano("platinum")


def test_get_fluxo_agendamento(loader: ConfigLoader) -> None:
    """Fluxo de agendamento carrega com estados corretos."""
    fluxo = loader.get_fluxo("agendamento_paciente_novo")
    assert fluxo.estado_inicial == "inicio"
    assert "aguardando_nome" in fluxo.estados
    assert "aguardando_status_paciente" in fluxo.estados
    assert "confirmacao_final" in fluxo.estados


def test_estados_tem_situacoes(loader: ConfigLoader) -> None:
    """Estado aguardando_nome tem situações definidas."""
    fluxo = loader.get_fluxo("agendamento_paciente_novo")
    estado = fluxo.estados["aguardando_nome"]
    assert len(estado.situacoes) >= 2
    assert "nome_valido" in estado.situacoes
    assert "nome_palavra_generica" in estado.situacoes


def test_get_regra_global_r1(loader: ConfigLoader) -> None:
    """R1_nunca_expor_breno existe e tem palavras_proibidas."""
    regra = loader.get_regra_global("R1_nunca_expor_breno")
    assert "palavras_proibidas" in regra
    assert any("Breno" in str(p) for p in regra["palavras_proibidas"])


def test_reload_funciona(loader: ConfigLoader) -> None:
    """reload() recarrega sem erros."""
    loader.reload()
    assert len(loader.list_fluxos()) >= 7


def test_numero_breno_nunca_exposto_via_config(loader: ConfigLoader) -> None:
    """Número do Breno está marcado como NUNCA no YAML."""
    breno = loader.get_numero("breno")
    assert breno.get("pode_receber_contato_paciente") == "NUNCA"


def test_grade_horarios_sexta_sem_noite(loader: ConfigLoader) -> None:
    """Sexta não tem horários de noite na grade."""
    grade = loader.global_config.grade_horarios
    sexta = grade.get("sexta", {})
    noite = sexta.get("noite", [])
    assert noite == [] or noite is None, f"Sexta tem noite: {noite}"
