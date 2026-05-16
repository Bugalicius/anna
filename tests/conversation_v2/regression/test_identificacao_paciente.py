"""
Testes de identificacao de paciente via base CSV no Redis.
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


def _mock_redis_vazio():
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    return r


def _mock_redis_com_paciente(phone: str, nome: str = "Renata Oliveira"):
    primeiro = nome.split()[0]
    payload = json.dumps({
        "nome": nome,
        "primeiro_nome": primeiro,
        "email": "renata@email.com",
        "sexo": "Feminino",
        "telefone": phone,
        "origem": "csv_dietbox",
    })
    r = AsyncMock()
    async def _get(key):
        if key == f"agente:paciente:{phone}":
            return payload
        return None
    r.get = _get
    return r


# ── patient_lookup unit tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lookup_encontra_paciente():
    from app.conversation.patient_lookup import identificar_paciente
    phone = "5531998565102"
    redis = _mock_redis_com_paciente(phone, "Renata Oliveira")
    result = await identificar_paciente(phone, redis)
    assert result is not None
    assert result["nome"] == "Renata Oliveira"
    assert result["primeiro_nome"] == "Renata"


@pytest.mark.asyncio
async def test_lookup_retorna_none_desconhecido():
    from app.conversation.patient_lookup import identificar_paciente
    redis = _mock_redis_vazio()
    result = await identificar_paciente("5531000000001", redis)
    assert result is None


@pytest.mark.asyncio
async def test_lookup_variacao_9_digito_sem_para_com():
    """
    CSV tem 553112345678 (12 digitos, sem 9o digito).
    WhatsApp envia 5531912345678 (13 digitos, com 9o digito).
    O lookup deve encontrar pelo candidato sem 9.
    """
    from app.conversation.patient_lookup import identificar_paciente

    phone_com9 = "5531912345678"   # 13 digitos (como WA envia)
    phone_sem9 = "553112345678"    # 12 digitos (como esta no CSV)

    payload = json.dumps({
        "nome": "Gabriela Rodrigues",
        "primeiro_nome": "Gabriela",
        "email": "",
        "sexo": "Feminino",
        "telefone": phone_sem9,
        "origem": "csv_dietbox",
    })
    r = AsyncMock()
    async def _get(key):
        if key == f"agente:paciente:{phone_sem9}":
            return payload
        return None
    r.get = _get

    result = await identificar_paciente(phone_com9, r)
    assert result is not None
    assert result["nome"] == "Gabriela Rodrigues"


@pytest.mark.asyncio
async def test_lookup_redis_none_retorna_none():
    from app.conversation.patient_lookup import identificar_paciente
    result = await identificar_paciente("5531999999999", None)
    assert result is None


@pytest.mark.asyncio
async def test_lookup_redis_excecao_retorna_none():
    from app.conversation.patient_lookup import identificar_paciente
    r = AsyncMock()
    r.get = AsyncMock(side_effect=Exception("Redis down"))
    result = await identificar_paciente("5531999999999", r)
    assert result is None


# ── orchestrator integration tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_paciente_conhecido_saudado_pelo_nome():
    """
    Paciente no Redis -> agente cumprimenta pelo nome, nao pergunta nome.
    """
    from app.conversation import orchestrator, state as conv_state

    phone = "5531998000001"
    phone_hash = _phone_hash(phone)
    # Estado vazio (primeiro contato)
    conv_state._mem_store.pop(f"conv_state:{phone_hash}", None)

    paciente_payload = json.dumps({
        "nome": "Renata Oliveira",
        "primeiro_nome": "Renata",
        "email": "r@email.com",
        "sexo": "Feminino",
        "telefone": phone,
        "origem": "csv_dietbox",
    })

    redis_mock = AsyncMock()
    async def _get(key):
        if key == f"agente:paciente:{phone}":
            return paciente_payload
        return None
    redis_mock.get = _get

    with patch.object(conv_state, "_state_mgr", None), \
         patch("app.conversation.orchestrator.get_state_redis", return_value=redis_mock), \
         patch("app.conversation.orchestrator._acquire_processing_lock", return_value=True), \
         patch("app.conversation.orchestrator._release_processing_lock", return_value=None), \
         patch("app.conversation.orchestrator._log_metric", new_callable=AsyncMock):

        result = await orchestrator.processar_turno(phone, {"type": "text", "text": "oi"})

    assert result.sucesso
    textos = " ".join(m.conteudo for m in result.mensagens_enviadas)
    assert "Renata" in textos
    assert result.novo_estado == "aguardando_status_paciente"
    # Nao deve pedir nome
    assert "nome" not in textos.lower() or "sobrenome" not in textos.lower()


@pytest.mark.asyncio
async def test_lead_novo_pergunta_nome():
    """
    Numero desconhecido -> fluxo normal, pede nome e sobrenome.
    """
    from app.conversation import orchestrator, state as conv_state

    phone = "5531998000002"
    phone_hash = _phone_hash(phone)
    conv_state._mem_store.pop(f"conv_state:{phone_hash}", None)

    redis_vazio = _mock_redis_vazio()

    with patch.object(conv_state, "_state_mgr", None), \
         patch("app.conversation.orchestrator.get_state_redis", return_value=redis_vazio), \
         patch("app.conversation.orchestrator._acquire_processing_lock", return_value=True), \
         patch("app.conversation.orchestrator._release_processing_lock", return_value=None), \
         patch("app.conversation.orchestrator._log_metric", new_callable=AsyncMock):

        result = await orchestrator.processar_turno(phone, {"type": "text", "text": "oi"})

    assert result.sucesso
    textos = " ".join(m.conteudo for m in result.mensagens_enviadas)
    assert "nome" in textos.lower() or "sobrenome" in textos.lower()


@pytest.mark.asyncio
async def test_nome_restaurado_apos_reset_inatividade():
    """
    Paciente conhecido volta apos 1h+ (reset) -> nome restaurado via Redis, nao perguntado.
    """
    from datetime import datetime, timedelta, timezone
    from app.conversation import orchestrator, state as conv_state

    phone = "5531998000003"
    phone_hash = _phone_hash(phone)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    # Estado antigo com nome preservado mas flags resetadas
    conv_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps({
        "phone": phone,
        "phone_hash": phone_hash,
        "estado": "inicio",
        "fluxo_id": "agendamento_paciente_novo",
        "collected_data": {"nome": "Carla Mendes"},
        "flags": {},
        "history": [],
        "last_message_at": old_ts,
    })

    paciente_payload = json.dumps({
        "nome": "Carla Mendes",
        "primeiro_nome": "Carla",
        "email": "",
        "sexo": "Feminino",
        "telefone": phone,
        "origem": "csv_dietbox",
    })
    redis_mock = AsyncMock()
    async def _get(key):
        if key == f"agente:paciente:{phone}":
            return paciente_payload
        return None
    redis_mock.get = _get

    with patch.object(conv_state, "_state_mgr", None), \
         patch("app.conversation.orchestrator.get_state_redis", return_value=redis_mock), \
         patch("app.conversation.orchestrator._acquire_processing_lock", return_value=True), \
         patch("app.conversation.orchestrator._release_processing_lock", return_value=None), \
         patch("app.conversation.orchestrator._log_metric", new_callable=AsyncMock):

        result = await orchestrator.processar_turno(phone, {"type": "text", "text": "oi"})

    assert result.sucesso
    textos = " ".join(m.conteudo for m in result.mensagens_enviadas)
    assert "Carla" in textos
    assert result.novo_estado == "aguardando_status_paciente"
