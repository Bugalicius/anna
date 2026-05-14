"""
Testes de regressão dos bugs do print de produção (2026-05).

Cada caso cobre um comportamento visível para o paciente:
- contexto antigo deve virar conversa nova;
- fallback repetido deve escalar e parar o loop;
- processamento concorrente do mesmo telefone deve ter lock;
- debounce deve aguardar 15s após a última mensagem.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


@pytest.mark.asyncio
async def test_bug1_contexto_nao_expira(monkeypatch):
    """
    GIVEN: paciente deixou estado em `aguardando_escolha_plano`
    WHEN: manda "Oi" 5h depois
    THEN: agente reseta e trata como nova conversa.
    """
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state

    phone = "5531999990001"
    phone_hash = _phone_hash(phone)
    old = datetime.now(timezone.utc) - timedelta(hours=5, minutes=32)
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_escolha_plano",
            "collected_data": {"nome": "Maria"},
            "history": [
                {"role": "assistant", "content": "Hoje temos estas opções. Qual faz mais sentido pra você agora?"}
            ],
            "last_message_at": old.isoformat(),
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", AsyncMock(), raising=False)

    result = await orchestrator.processar_turno(
        phone=phone,
        mensagem={"type": "text", "text": "Oi", "from": phone, "id": "m1"},
    )

    assert result.novo_estado == "aguardando_nome"
    assert "outro jeito" not in "\n".join(m.conteudo for m in result.mensagens_enviadas).lower()
    saved = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    assert saved["reset_reason"] == "inatividade"


@pytest.mark.asyncio
async def test_bug2_loop_fallback_escala(monkeypatch):
    """
    GIVEN: paciente já recebeu a mesma resposta de fallback duas vezes
    WHEN: cai em fallback novamente
    THEN: escala silenciosamente e responde a mensagem de handoff.
    """
    from app.conversation import orchestrator
    from app.conversation.models import Interpretacao
    from app.conversation import state as legacy_state

    phone = "5531999990002"
    phone_hash = _phone_hash(phone)
    fallback_text = "Pode me mandar de outro jeito para eu entender certinho?"
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_escolha_plano",
            "collected_data": {},
            "history": [],
            "fallback_streak": 2,
            "last_response_hash": hashlib.sha256(fallback_text.encode()).hexdigest()[:16],
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(
        orchestrator,
        "interpretar",
        AsyncMock(
            return_value=Interpretacao(
                intent="desconhecido",
                confidence=0.1,
                texto_original="Mandar oq?",
                entities={},
            )
        ),
    )
    monkeypatch.setattr(orchestrator.state_machine, "proxima_acao", lambda **_: None)
    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", AsyncMock(), raising=False)
    mock_tool = AsyncMock()
    monkeypatch.setattr(orchestrator, "call_tool", mock_tool)

    result = await orchestrator.processar_turno(
        phone=phone,
        mensagem={"type": "text", "text": "Mandar oq?", "from": phone, "id": "m2"},
    )

    assert [m.conteudo for m in result.mensagens_enviadas] == [
        "Deixa eu chamar alguém da equipe pra te dar atenção especial 💚"
    ]
    mock_tool.assert_awaited()
    saved = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    assert saved["estado"] == "aguardando_orientacao_breno"
    assert saved["fallback_streak"] == 0


@pytest.mark.asyncio
async def test_bug2b_handoff_nao_repete_escalacao(monkeypatch):
    """
    GIVEN: paciente ja esta aguardando orientacao humana
    WHEN: manda mais uma mensagem aleatoria
    THEN: Ana nao repete a escala inicial nem cria nova escalacao.
    """
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state

    phone = "5531999990202"
    phone_hash = _phone_hash(phone)
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_orientacao_breno",
            "collected_data": {},
            "history": [],
            "fallback_streak": 0,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", AsyncMock(), raising=False)
    mock_tool = AsyncMock()
    monkeypatch.setattr(orchestrator, "call_tool", mock_tool)

    result = await orchestrator.processar_turno(
        phone=phone,
        mensagem={"type": "text", "text": "???", "from": phone, "id": "m2b"},
    )

    textos = "\n".join(m.conteudo for m in result.mensagens_enviadas)
    assert "Deixa eu chamar" not in textos
    assert "equipe já foi chamada" in textos
    mock_tool.assert_not_awaited()
    saved = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    assert saved["estado"] == "aguardando_orientacao_breno"


@pytest.mark.asyncio
async def test_bug2c_handoff_saudacao_reinicia_conversa(monkeypatch):
    """
    GIVEN: conversa ficou presa em aguardando orientacao humana
    WHEN: paciente volta com saudacao
    THEN: Ana reinicia a conversa em vez de repetir a escala.
    """
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state

    phone = "5531999990203"
    phone_hash = _phone_hash(phone)
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_orientacao_breno",
            "collected_data": {},
            "history": [],
            "fallback_streak": 0,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", AsyncMock(), raising=False)
    mock_tool = AsyncMock()
    monkeypatch.setattr(orchestrator, "call_tool", mock_tool)

    result = await orchestrator.processar_turno(
        phone=phone,
        mensagem={"type": "text", "text": "boa tarde", "from": phone, "id": "m2c"},
    )

    textos = "\n".join(m.conteudo for m in result.mensagens_enviadas)
    assert result.novo_estado == "aguardando_nome"
    assert "Deixa eu chamar" not in textos
    assert textos
    mock_tool.assert_not_awaited()
    saved = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    assert saved["reset_reason"] == "retomada_apos_handoff"


@pytest.mark.asyncio
async def test_bug3_mensagens_paralelas_nao_duplicam(monkeypatch):
    """
    GIVEN: duas execuções concorrentes para o mesmo telefone
    WHEN: a segunda tenta iniciar durante a primeira
    THEN: só uma entra no pipeline; a outra retorna sem resposta.
    """
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state

    phone = "5531999990003"
    phone_hash = _phone_hash(phone)
    legacy_state._mem_store.pop(f"conv_state:{phone_hash}", None)

    locks = [True, False]
    acquire = AsyncMock(side_effect=lambda *_args, **_kwargs: locks.pop(0))
    release = AsyncMock()
    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", acquire, raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", release, raising=False)

    first = await orchestrator.processar_turno(phone, {"type": "text", "text": "Oi", "from": phone, "id": "m1"})
    second = await orchestrator.processar_turno(phone, {"type": "text", "text": "Oi de novo", "from": phone, "id": "m2"})

    assert first.mensagens_enviadas
    assert second.mensagens_enviadas == []
    assert acquire.await_count == 2
    release.assert_awaited_once()


@pytest.mark.asyncio
async def test_bug5_paciente_chamado_breno_avanca_estado(monkeypatch):
    """
    GIVEN: paciente está em aguardando_nome
    WHEN: manda "Breno" como nome
    THEN: estado avança para aguardando_status_paciente (não cai em fallback).

    Regressão: R1_nunca_expor_breno bloqueava "Prazer, Breno!" e o
    regenerador retornava o fallback genérico.
    """
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state

    phone = "5531999990005"
    phone_hash = _phone_hash(phone)
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_nome",
            "collected_data": {k: None for k in (
                "nome", "nome_completo", "status_paciente", "objetivo",
                "plano", "modalidade", "preferencia_horario",
                "preferencia_horario_nova", "forma_pagamento", "data_nascimento",
                "email", "whatsapp_contato", "instagram", "profissao",
                "cep_endereco", "indicacao_origem", "motivo_cancelamento",
            )},
            "history": [{"role": "assistant", "content": "Qual é o seu nome e sobrenome?"}],
            "flags": {"pagamento_confirmado": False},
            "last_message_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )

    monkeypatch.setattr(orchestrator, "_acquire_processing_lock", AsyncMock(return_value=True), raising=False)
    monkeypatch.setattr(orchestrator, "_release_processing_lock", AsyncMock(), raising=False)

    result = await orchestrator.processar_turno(
        phone=phone,
        mensagem={"type": "text", "text": "Breno", "from": phone, "id": "m5"},
    )

    assert result.novo_estado == "aguardando_status_paciente", (
        f"Estado esperado: aguardando_status_paciente, obtido: {result.novo_estado}"
    )
    textos = "\n".join(m.conteudo for m in result.mensagens_enviadas)
    assert "mais detalhes" not in textos.lower(), (
        "Agente caiu no fallback genérico em vez de aceitar o nome Breno"
    )
    saved = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    assert saved["collected_data"]["nome"] == "Breno"


@pytest.mark.asyncio
async def test_bug4_debounce_15s_apos_ultima(monkeypatch):
    """
    GIVEN: paciente manda msg em t=0, t=5s, t=10s
    WHEN: nenhuma msg nova chega até t=25s
    THEN: pipeline executa só no disparo da última mensagem.
    """
    from app import webhook

    class FakeRedis:
        queues: dict[str, list[str]] = {}
        values: dict[str, str] = {}

        @classmethod
        def from_url(cls, *_args, **_kwargs):
            return cls()

        async def rpush(self, key, value):
            self.queues.setdefault(key, []).append(value)

        async def expire(self, *_args, **_kwargs):
            return True

        async def set(self, key, value, **_kwargs):
            self.values[key] = str(value)
            return True

        async def get(self, key):
            return self.values.get(key)

        async def lrange(self, key, start, end):
            return list(self.queues.get(key, []))

        async def delete(self, *keys):
            for key in keys:
                self.queues.pop(key, None)
                self.values.pop(key, None)

        async def aclose(self):
            return None

    calls: list[str] = []
    sleeps: list[float] = []
    all_sleeping = asyncio.Event()
    release_sleep = asyncio.Event()

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) == 3:
            all_sleeping.set()
        await release_sleep.wait()

    async def fake_process(message, metadata):
        calls.append(message["text"]["body"])

    monkeypatch.setattr(webhook.aioredis, "Redis", FakeRedis)
    monkeypatch.setenv("DEBOUNCE_SECONDS", "15")
    monkeypatch.setattr(webhook.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(webhook, "process_message", fake_process)

    base = {"from": "5531999990004", "type": "text"}
    tasks = [
        asyncio.create_task(webhook.process_message_debounced({**base, "id": "m1", "text": {"body": "oi"}}, {})),
        asyncio.create_task(webhook.process_message_debounced({**base, "id": "m2", "text": {"body": "quero"}}, {})),
        asyncio.create_task(webhook.process_message_debounced({**base, "id": "m3", "text": {"body": "agendar"}}, {})),
    ]
    await asyncio.wait_for(all_sleeping.wait(), timeout=1)
    release_sleep.set()
    await asyncio.gather(*tasks)

    assert sleeps == [15.0, 15.0, 15.0]
    assert calls == ["oi\nquero\nagendar"]
