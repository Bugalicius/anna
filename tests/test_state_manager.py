"""
Testes para RedisStateManager e serialização dos agentes (to_dict/from_dict).

Cobre:
  - Serialização round-trip de AgenteAtendimento
  - Serialização round-trip de AgenteRetencao
  - RedisStateManager.save() / load() / delete() com Redis mockado
  - Graceful degradation em falha do Redis
  - Ausência de TTL nas chaves Redis (D-12)
  - Limite de 20 entradas no historico (T-01-01)
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.atendimento import AgenteAtendimento
from app.agents.retencao import AgenteRetencao
from app.state_manager import RedisStateManager


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_atendimento_completo() -> AgenteAtendimento:
    """Cria instância com todos os campos preenchidos."""
    a = AgenteAtendimento(telefone="5531999999999", phone_hash="abc123")
    a.etapa = "pagamento"
    a.nome = "Maria Silva"
    a.status_paciente = "novo"
    a.objetivo = "Perda de peso"
    a.plano_escolhido = "com_retorno"
    a.modalidade = "online"
    a.upsell_oferecido = True
    a.slot_escolhido = {"datetime": "2026-04-15T09:00", "data_fmt": "15/04/2026", "hora": "09:00"}
    a.forma_pagamento = "pix"
    a.pagamento_confirmado = False
    a.id_paciente_dietbox = 42
    a.id_agenda_dietbox = "agenda-99"
    a.historico = [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
    return a


def _make_retencao_completo() -> AgenteRetencao:
    """Cria instância com todos os campos preenchidos."""
    r = AgenteRetencao(telefone="5531888888888", nome="João Pereira", modalidade="presencial")
    r.etapa = "oferecendo_slots"
    r.motivo = "viagem"
    r.consulta_atual = {"id": "c-1", "data_fmt": "10/04/2026", "hora": "14:00"}
    r.novo_slot = {"datetime": "2026-04-17T10:00", "data_fmt": "17/04/2026", "hora": "10:00"}
    r.historico = [{"role": "user", "content": "preciso remarcar"}]
    return r


def _make_mock_redis() -> MagicMock:
    """Cria mock assíncrono do cliente Redis."""
    mock = MagicMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.delete = AsyncMock(return_value=1)
    return mock


# ── Testes de serialização AgenteAtendimento ──────────────────────────────────

def test_atendimento_to_dict_tem_tipo():
    """Test 1: to_dict() retorna dict com _tipo: 'atendimento'."""
    a = AgenteAtendimento(telefone="55319", phone_hash="hash1")
    d = a.to_dict()
    assert d["_tipo"] == "atendimento"


def test_atendimento_to_dict_todos_campos():
    """Test 1b: to_dict() serializa todos os campos de estado."""
    a = _make_atendimento_completo()
    d = a.to_dict()

    assert d["telefone"] == "5531999999999"
    assert d["phone_hash"] == "abc123"
    assert d["etapa"] == "pagamento"
    assert d["nome"] == "Maria Silva"
    assert d["status_paciente"] == "novo"
    assert d["objetivo"] == "Perda de peso"
    assert d["plano_escolhido"] == "com_retorno"
    assert d["modalidade"] == "online"
    assert d["upsell_oferecido"] is True
    assert d["slot_escolhido"] is not None
    assert d["forma_pagamento"] == "pix"
    assert d["pagamento_confirmado"] is False
    assert d["id_paciente_dietbox"] == 42
    assert d["id_agenda_dietbox"] == "agenda-99"


def test_atendimento_round_trip():
    """Test 2: from_dict(to_dict()) restaura estado identico."""
    original = _make_atendimento_completo()
    d = original.to_dict()
    restaurado = AgenteAtendimento.from_dict(d)

    assert restaurado.telefone == original.telefone
    assert restaurado.phone_hash == original.phone_hash
    assert restaurado.etapa == original.etapa
    assert restaurado.nome == original.nome
    assert restaurado.status_paciente == original.status_paciente
    assert restaurado.objetivo == original.objetivo
    assert restaurado.plano_escolhido == original.plano_escolhido
    assert restaurado.modalidade == original.modalidade
    assert restaurado.upsell_oferecido == original.upsell_oferecido
    assert restaurado.slot_escolhido == original.slot_escolhido
    assert restaurado.forma_pagamento == original.forma_pagamento
    assert restaurado.pagamento_confirmado == original.pagamento_confirmado
    assert restaurado.id_paciente_dietbox == original.id_paciente_dietbox
    assert restaurado.id_agenda_dietbox == original.id_agenda_dietbox
    assert restaurado.historico == original.historico


# ── Testes de serialização AgenteRetencao ────────────────────────────────────

def test_retencao_to_dict_tem_tipo():
    """Test 3: to_dict() retorna dict com _tipo: 'retencao'."""
    r = AgenteRetencao(telefone="5531", nome=None)
    d = r.to_dict()
    assert d["_tipo"] == "retencao"


def test_retencao_round_trip():
    """Test 4: from_dict(to_dict()) restaura estado idêntico."""
    original = _make_retencao_completo()
    d = original.to_dict()
    restaurado = AgenteRetencao.from_dict(d)

    assert restaurado.telefone == original.telefone
    assert restaurado.nome == original.nome
    assert restaurado.modalidade == original.modalidade
    assert restaurado.etapa == original.etapa
    assert restaurado.motivo == original.motivo
    assert restaurado.consulta_atual == original.consulta_atual
    assert restaurado.novo_slot == original.novo_slot
    assert restaurado.historico == original.historico


# ── Testes do RedisStateManager ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_save_and_load_round_trip():
    """Test 5: save() + load() faz round-trip de AgenteAtendimento."""
    manager = RedisStateManager.__new__(RedisStateManager)
    manager._client = _make_mock_redis()

    original = _make_atendimento_completo()
    captured_json: list[str] = []

    async def fake_set(key, value):
        captured_json.append(value)
        return True

    async def fake_get(key):
        return captured_json[0] if captured_json else None

    manager._client.set = fake_set
    manager._client.get = fake_get

    await manager.save("abc123", original)
    carregado = await manager.load("abc123")

    assert carregado is not None
    assert isinstance(carregado, AgenteAtendimento)
    assert carregado.nome == original.nome
    assert carregado.etapa == original.etapa


@pytest.mark.asyncio
async def test_redis_load_none_para_chave_inexistente():
    """Test 6: load() retorna None para phone_hash desconhecido."""
    manager = RedisStateManager.__new__(RedisStateManager)
    manager._client = _make_mock_redis()
    manager._client.get = AsyncMock(return_value=None)

    resultado = await manager.load("hash_inexistente")
    assert resultado is None


@pytest.mark.asyncio
async def test_redis_delete_remove_chave():
    """Test 7: delete() chama client.delete com a chave correta."""
    manager = RedisStateManager.__new__(RedisStateManager)
    mock_client = _make_mock_redis()
    manager._client = mock_client

    await manager.delete("minha_hash")

    mock_client.delete.assert_awaited_once_with("agent_state:minha_hash")


@pytest.mark.asyncio
async def test_redis_save_sem_ttl():
    """Test 8: save() NÃO define TTL (ex=, px=, exat=, etc.) — per D-12."""
    manager = RedisStateManager.__new__(RedisStateManager)
    mock_client = _make_mock_redis()
    manager._client = mock_client

    agente = AgenteAtendimento(telefone="55319", phone_hash="h1")
    await manager.save("h1", agente)

    # Verifica que set foi chamado sem argumentos de TTL
    call_kwargs = mock_client.set.call_args
    assert call_kwargs is not None
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    positional = call_kwargs.args if call_kwargs.args else ()

    # Nenhum argumento de TTL deve estar presente
    ttl_kwargs = {"ex", "px", "exat", "pxat", "keepttl"}
    for kwarg_name in ttl_kwargs:
        assert kwarg_name not in kwargs, f"TTL kwarg '{kwarg_name}' não deve estar presente"


@pytest.mark.asyncio
async def test_redis_load_falha_retorna_none():
    """Test 9: load() em falha do Redis loga erro e retorna None (D-15)."""
    manager = RedisStateManager.__new__(RedisStateManager)
    mock_client = _make_mock_redis()
    mock_client.get = AsyncMock(side_effect=ConnectionError("Redis offline"))
    manager._client = mock_client

    resultado = await manager.load("qualquer_hash")
    assert resultado is None


def test_to_dict_limita_historico_a_20_entradas():
    """Test 10: to_dict() inclui no máximo 20 entradas do historico (T-01-01)."""
    a = AgenteAtendimento(telefone="55319", phone_hash="h2")
    # Preenche 30 entradas
    a.historico = [{"role": "user", "content": f"msg {i}"} for i in range(30)]
    d = a.to_dict()

    assert len(d["historico"]) == 20
    # Deve ser as 20 últimas
    assert d["historico"][0]["content"] == "msg 10"
    assert d["historico"][-1]["content"] == "msg 29"
