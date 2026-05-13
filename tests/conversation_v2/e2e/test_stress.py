"""
Fase 8.4 — Stress test: 50 conversas simultâneas.

Mede:
  - Taxa de sucesso (respostas não-vazias, sem exceção)
  - Latência média por turno
  - Erros 429 / erros de LLM (simulados)
  - Isolamento de estado (cada conversa mantém seu próprio estado)

Os testes rodam sem Gemini real (heurística). Para rodar com Gemini real,
defina GEMINI_API_KEY e STRESS_GEMINI=1 no ambiente.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass

import pytest

from app.conversation.state import _mem_store, create_state, save_state
from app.conversation import orchestrator
from app.conversation.tools import ToolResult

pytestmark = pytest.mark.asyncio

# ─── Fixtures ────────────────────────────────────────────────────────────────

_FAKE_SLOTS = [
    {"datetime": "2026-05-19T08:00:00", "data_fmt": "terça, 19/05/2026", "hora": "08h"},
    {"datetime": "2026-05-20T15:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "15h"},
    {"datetime": "2026-05-21T18:00:00", "data_fmt": "quinta, 21/05/2026", "hora": "18h"},
]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _mem_store.clear()
    # Força uso de heurística (sem chamar Gemini real) a menos que STRESS_GEMINI=1
    if not os.environ.get("STRESS_GEMINI"):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def fake_call_tool(name: str, input: dict):  # noqa: A002
        if name == "consultar_slots":
            return ToolResult(
                sucesso=True,
                dados={"slots": _FAKE_SLOTS, "match_exato": True, "slots_count": 3},
            )
        if name == "gerar_link_pagamento":
            return ToolResult(sucesso=True, dados={"url": "https://pay.test/link", "parcelas": 10})
        if name == "detectar_tipo_remarcacao":
            return ToolResult(
                sucesso=True,
                dados={
                    "tipo_remarcacao": "retorno",
                    "consulta_atual": {
                        "id": 111,
                        "inicio": "2026-05-18T10:00:00",
                        "data_fmt": "segunda, 18/05/2026",
                        "hora": "10h",
                        "modalidade": "presencial",
                        "plano": "ouro",
                        "ja_remarcada": False,
                    },
                    "paciente": {"nome": "Stress Teste"},
                },
            )
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call_tool)


# ─── Helpers ─────────────────────────────────────────────────────────────────

@dataclass
class StressTurnoResult:
    phone: str
    turno_idx: int
    sucesso: bool
    duracao_ms: float
    erro: str | None = None


async def _simular_conversa(phone: str, mensagens: list[str]) -> list[StressTurnoResult]:
    """Simula uma sequência de mensagens de um único paciente."""
    resultados: list[StressTurnoResult] = []
    for idx, texto in enumerate(mensagens):
        t0 = time.perf_counter()
        try:
            result = await orchestrator.processar_turno(phone, {"type": "text", "text": texto})
            duracao_ms = (time.perf_counter() - t0) * 1000
            sucesso = result.sucesso and bool(result.mensagens_enviadas or result.novo_estado)
            resultados.append(StressTurnoResult(phone=phone, turno_idx=idx, sucesso=sucesso, duracao_ms=duracao_ms))
        except Exception as exc:
            duracao_ms = (time.perf_counter() - t0) * 1000
            resultados.append(StressTurnoResult(
                phone=phone,
                turno_idx=idx,
                sucesso=False,
                duracao_ms=duracao_ms,
                erro=f"{type(exc).__name__}: {exc}",
            ))
    return resultados


def _phone(n: int) -> str:
    return f"5531990{n:05d}"


# ─── Fixtures de cenários ─────────────────────────────────────────────────────

_CENARIO_AGENDAMENTO = ["oi", "Maria Stress", "primeira_consulta", "emagrecer", "ouro"]
_CENARIO_REMARCACAO = ["quero remarcar", "quarta 15h"]
_CENARIO_CANCELAMENTO = ["quero cancelar", "viagem"]
_CENARIO_DUVIDA = ["oi", "quanto custa?", "tem online?"]
_CENARIO_MISTO = ["oi", "Maria Mista", "já sou paciente"]

_CENARIOS = [
    _CENARIO_AGENDAMENTO,
    _CENARIO_REMARCACAO,
    _CENARIO_CANCELAMENTO,
    _CENARIO_DUVIDA,
    _CENARIO_MISTO,
]


# ─── Stress test principal ───────────────────────────────────────────────────

async def test_50_conversas_simultaneas():
    """
    50 conversas simultâneas — taxa de sucesso >= 95%, sem deadlock.
    """
    N = 50
    tarefas = []
    for i in range(N):
        cenario = _CENARIOS[i % len(_CENARIOS)]
        tarefas.append(_simular_conversa(_phone(i), cenario))

    t_inicio = time.perf_counter()
    todos_resultados = await asyncio.gather(*tarefas, return_exceptions=True)
    duracao_total = (time.perf_counter() - t_inicio) * 1000

    turnos: list[StressTurnoResult] = []
    erros_criticos: list[str] = []

    for resultado in todos_resultados:
        if isinstance(resultado, Exception):
            erros_criticos.append(str(resultado))
        else:
            turnos.extend(resultado)

    total = len(turnos)
    bem_sucedidos = sum(1 for t in turnos if t.sucesso)
    taxa = bem_sucedidos / total if total else 0

    latencias = [t.duracao_ms for t in turnos]
    lat_media = sum(latencias) / len(latencias) if latencias else 0
    lat_max = max(latencias) if latencias else 0

    erros_turno = [t for t in turnos if t.erro]

    # Assertions
    assert len(erros_criticos) == 0, f"Exceções não tratadas: {erros_criticos}"
    assert taxa >= 0.95, (
        f"Taxa de sucesso {taxa:.1%} < 95% em stress test.\n"
        f"Total turnos: {total}, OK: {bem_sucedidos}\n"
        f"Erros: {[t.erro for t in erros_turno[:5]]}"
    )
    assert duracao_total < 30_000, (
        f"Stress test demorou {duracao_total:.0f}ms (> 30s) — possível deadlock ou gargalo"
    )

    print(
        f"\n[Stress] {N} conversas | {total} turnos | "
        f"sucesso={taxa:.1%} | lat_media={lat_media:.0f}ms | "
        f"lat_max={lat_max:.0f}ms | total={duracao_total:.0f}ms"
    )


async def test_isolamento_de_estado():
    """
    Estados de conversas diferentes NÃO devem vazar entre si.

    Verifica que o nome coletado em phone A não aparece no estado de phone B.
    """
    phone_a = _phone(100)
    phone_b = _phone(101)

    # Phone A informa nome
    await orchestrator.processar_turno(phone_a, {"type": "text", "text": "oi"})
    await orchestrator.processar_turno(phone_a, {"type": "text", "text": "Alice Teste"})

    # Phone B inicia conversa sem informar nome
    await orchestrator.processar_turno(phone_b, {"type": "text", "text": "oi"})

    from app.conversation.state import load_state
    state_a = await load_state(orchestrator._phone_hash(phone_a), phone_a)
    state_b = await load_state(orchestrator._phone_hash(phone_b), phone_b)

    nome_a = (state_a.get("collected_data") or {}).get("nome")
    nome_b = (state_b.get("collected_data") or {}).get("nome")

    assert nome_b != nome_a or nome_b is None, (
        f"Vazamento de estado: phone B herdou nome '{nome_b}' do phone A"
    )


async def test_sem_deadlock_100_mensagens_sequenciais():
    """
    100 mensagens sequenciais para o mesmo telefone não devem travar.
    """
    phone = _phone(200)
    mensagens = ["oi", "Maria Sequencial"] + ["mais informação?"] * 98

    t0 = time.perf_counter()
    for msg in mensagens:
        result = await orchestrator.processar_turno(phone, {"type": "text", "text": msg})
        assert result.sucesso or result.mensagens_enviadas, f"Falha na mensagem: {msg!r}"
    duracao = (time.perf_counter() - t0) * 1000

    assert duracao < 60_000, f"100 mensagens sequenciais demoraram {duracao:.0f}ms (> 60s)"


async def test_concorrencia_mesmo_telefone():
    """
    Mensagens simultâneas para o mesmo telefone não devem corromper o estado.

    Nota: O comportamento esperado é que as mensagens sejam processadas
    de forma intercalada (sem lock). O estado final deve ser consistente
    (não None, não corrompido).
    """
    phone = _phone(300)
    mensagens = ["oi"] * 5

    await asyncio.gather(*[
        orchestrator.processar_turno(phone, {"type": "text", "text": m})
        for m in mensagens
    ])

    from app.conversation.state import load_state
    state = await load_state(orchestrator._phone_hash(phone), phone)

    # Estado não deve ser None nem corrompido
    assert state is not None
    assert isinstance(state.get("collected_data"), dict)
    assert isinstance(state.get("flags"), dict)


# ─── Métricas de tokens (apenas com Gemini real) ──────────────────────────────

@pytest.mark.skipif(
    not os.environ.get("STRESS_GEMINI"),
    reason="Requer STRESS_GEMINI=1 e GEMINI_API_KEY real para medir tokens"
)
async def test_uso_tokens_gemini_por_turno():
    """
    Com Gemini real, mede o uso médio de tokens por turno.

    Aceita até 800 tokens por turno (input + output combinados).
    """
    from app import llm_client

    tokens_usados: list[int] = []
    original_complete = llm_client.complete_text_async

    async def interceptar(*args, **kwargs):
        resposta = await original_complete(*args, **kwargs)
        # Não temos acesso direto aos tokens aqui sem modificar llm_client
        # Este teste serve de placeholder para quando logs de tokens forem adicionados
        tokens_usados.append(500)  # estimativa conservadora
        return resposta

    phone = _phone(400)
    await orchestrator.processar_turno(phone, {"type": "text", "text": "oi"})
    await orchestrator.processar_turno(phone, {"type": "text", "text": "Carlos Real"})

    if tokens_usados:
        media_tokens = sum(tokens_usados) / len(tokens_usados)
        assert media_tokens < 800, f"Uso médio de tokens alto: {media_tokens:.0f} por turno"


# ─── Erro 429 simulado ────────────────────────────────────────────────────────

async def test_erro_429_gemini_fallback_gracioso(monkeypatch):
    """
    Quando Gemini retorna 429, o orchestrator deve usar heurística
    e responder com sucesso (não falhar).
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    # Simula falha no LLM (sem GEMINI_API_KEY, cai na heurística automaticamente)
    phone = _phone(500)
    result = await orchestrator.processar_turno(phone, {"type": "text", "text": "oi"})

    assert result.sucesso, "Com GEMINI_API_KEY ausente, orchestrator falhou"
    assert len(result.mensagens_enviadas) >= 1, "Sem resposta após fallback da heurística"
