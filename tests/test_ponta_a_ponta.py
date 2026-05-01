from __future__ import annotations

import asyncio
import os

import pytest


class _FakeRedis:
    store: dict[str, int | str] = {}

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return int(self.store[key])

    async def expire(self, key: str, ttl: int) -> None:
        return None

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_rate_limit_bloqueia_apos_30_mensagens(monkeypatch):
    from app import rate_limit

    _FakeRedis.store = {}
    monkeypatch.setattr(rate_limit.aioredis.Redis, "from_url", _FakeRedis.from_url)
    monkeypatch.setenv("WHATSAPP_RATE_LIMIT_MAX_PER_HOUR", "30")

    results = [await rate_limit.is_whatsapp_rate_limited("hash-paciente") for _ in range(31)]

    assert results[:30] == [False] * 30
    assert results[30] is True


@pytest.mark.asyncio
async def test_audio_responde_pedindo_texto(monkeypatch):
    from app import webhook

    sent = []
    monkeypatch.setenv("DISABLE_AFTER_HOURS_NOTICE", "true")
    monkeypatch.setattr(webhook, "_is_duplicate_message", lambda meta_id: asyncio.sleep(0, result=False))
    monkeypatch.setattr("app.rate_limit.is_whatsapp_rate_limited", lambda phone_hash: asyncio.sleep(0, result=False))
    monkeypatch.setattr(webhook, "_send_text_direct", lambda phone, text, message_id="": asyncio.sleep(0, result=sent.append(text)))

    await webhook.process_message({"id": "audio-1", "from": "5531999990001", "type": "audio"}, {})

    assert sent == [webhook.MSG_AUDIO_FALHOU]


@pytest.mark.skip(reason="_em_horario_atendimento e MSG_FORA_HORARIO removidos do webhook; feature de horário comercial não existe mais neste módulo")
@pytest.mark.asyncio
async def test_fora_do_horario_responde_uma_vez(monkeypatch):
    from app import webhook

    sent = []
    _FakeRedis.store = {}
    monkeypatch.delenv("DISABLE_AFTER_HOURS_NOTICE", raising=False)
    monkeypatch.setattr(webhook.aioredis.Redis, "from_url", _FakeRedis.from_url)
    monkeypatch.setattr(webhook, "_em_horario_atendimento", lambda now=None: False)
    monkeypatch.setattr(webhook, "_is_duplicate_message", lambda meta_id: asyncio.sleep(0, result=False))
    monkeypatch.setattr("app.rate_limit.is_whatsapp_rate_limited", lambda phone_hash: asyncio.sleep(0, result=False))
    monkeypatch.setattr(webhook, "_send_text_direct", lambda phone, text, message_id="": asyncio.sleep(0, result=sent.append(text)))

    msg = {"id": "fora-1", "from": "5531999990002", "type": "text", "text": {"body": "oi"}}
    await webhook.process_message(msg, {})
    msg["id"] = "fora-2"
    await webhook.process_message(msg, {})

    assert sent == [webhook.MSG_FORA_HORARIO]


@pytest.mark.asyncio
async def test_menor_de_16_anos_recusa_atendimento():
    from app.conversation.planner import decidir_acao
    from app.conversation.state import create_state

    plano = await decidir_acao(
        {"intent": "tirar_duvida", "_raw_message": "tenho 15 anos, posso consultar?"},
        create_state("hash-menor", "5531999990003"),
    )

    assert plano["action"] == "answer_question"
    assert "menores de 16 anos" in plano["draft_message"]


@pytest.mark.asyncio
async def test_gestante_recusa_atendimento():
    from app.conversation.planner import decidir_acao
    from app.conversation.state import create_state

    plano = await decidir_acao(
        {"intent": "tirar_duvida", "_raw_message": "estou gestante, queria marcar"},
        create_state("hash-gestante", "5531999990004"),
    )

    assert plano["action"] == "answer_question"
    assert "gestantes" in plano["draft_message"]


@pytest.mark.asyncio
async def test_timeout_de_turno_retorna_fallback(monkeypatch):
    from app.conversation.engine import ConversationEngine

    async def lento(self, phone_hash: str, message: str, phone: str = ""):
        await asyncio.sleep(0.05)
        return ["nao deveria chegar aqui"]

    monkeypatch.setenv("TURN_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr("app.conversation.engine.record_turn_error", lambda phone_hash, reason: asyncio.sleep(0, result=1))
    monkeypatch.setattr("app.conversation.engine.ConversationEngine._handle_message_impl", lento)

    resposta = await ConversationEngine().handle_message("hash-timeout", "oi")

    assert "instabilidade" in resposta[0]


@pytest.mark.asyncio
async def test_remarcacao_com_prazo_vencido(monkeypatch):
    from app.integrations import dietbox
    from app.tools.patients import detectar_tipo_remarcacao

    monkeypatch.setattr(dietbox, "buscar_paciente_por_telefone", lambda telefone: {"id": 123})
    monkeypatch.setattr(dietbox, "buscar_paciente_por_identificador", lambda identificador: None)
    monkeypatch.setattr(
        dietbox,
        "consultar_agendamento_ativo",
        lambda id_paciente: {"id": "agenda-1", "inicio": "2025-01-01T10:00:00"},
    )
    monkeypatch.setattr(dietbox, "verificar_lancamento_financeiro", lambda id_agenda: True)

    resultado = await detectar_tipo_remarcacao("5531999990005")

    assert resultado["tipo_remarcacao"] == "perda_retorno"
    assert resultado["fim_janela"] == "2025-04-01"
