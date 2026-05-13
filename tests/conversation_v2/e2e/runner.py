"""
runner.py — Runner E2E: replaya conversas reais e mede qualidade do orchestrator v2.

Uso em pytest:
    from tests.conversation_v2.e2e.runner import selecionar_conversas, executar_bateria

Uso standalone:
    python -m tests.conversation_v2.e2e.runner
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

# ─── Caminhos ────────────────────────────────────────────────────────────────

CONVERSAS_PATH = Path(__file__).parents[3] / "conversas_export.json"

# ─── Mocks de tools ──────────────────────────────────────────────────────────

_SLOTS_MOCK = [
    {"datetime": "2026-05-19T08:00:00", "data_fmt": "terça, 19/05/2026", "hora": "08h"},
    {"datetime": "2026-05-20T15:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "15h"},
    {"datetime": "2026-05-21T18:00:00", "data_fmt": "quinta, 21/05/2026", "hora": "18h"},
]

_CONSULTA_MOCK = {
    "id": 1234,
    "inicio": "2026-05-19T08:00:00",
    "data_fmt": "terça, 19/05/2026",
    "hora": "08h",
    "modalidade": "presencial",
    "plano": "ouro",
    "ja_remarcada": False,
}


async def _fake_call_tool(name: str, input: dict) -> Any:  # noqa: A002
    from app.conversation.tools import ToolResult

    if name == "consultar_slots":
        return ToolResult(
            sucesso=True,
            dados={"slots": _SLOTS_MOCK, "match_exato": True, "slots_count": len(_SLOTS_MOCK)},
        )
    if name == "gerar_link_pagamento":
        return ToolResult(sucesso=True, dados={"url": "https://pagamento.test/abc", "parcelas": 10})
    if name == "detectar_tipo_remarcacao":
        return ToolResult(
            sucesso=True,
            dados={
                "tipo_remarcacao": "retorno",
                "consulta_atual": _CONSULTA_MOCK,
                "paciente": {"nome": "Paciente Teste"},
            },
        )
    if name == "analisar_comprovante":
        plano = input.get("plano") or "ouro"
        from app.conversation.config_loader import config
        cfg = config.get_plano(plano)
        valor = float(cfg.valores.pix_presencial)
        return ToolResult(sucesso=True, dados={"valor": valor * 0.5, "aprovado": True})
    if name == "transcrever_audio":
        return ToolResult(sucesso=True, dados={"transcricao": "mensagem de áudio transcrita"})
    return ToolResult(sucesso=True, dados={})


# ─── Modelos de resultado ─────────────────────────────────────────────────────

@dataclass
class TurnoResult:
    turno_idx: int
    mensagem_paciente: str
    respostas_orchestrator: list[str]
    estado_antes: str
    estado_depois: str
    aceitavel: bool
    motivo_rejeicao: str | None = None
    duracao_ms: float = 0.0


@dataclass
class ConversaResult:
    conversa_id: str
    tipo: str
    total_turnos: int
    turnos_aceitos: int
    turnos: list[TurnoResult] = field(default_factory=list)
    erro: str | None = None

    @property
    def taxa_sucesso(self) -> float:
        if not self.total_turnos:
            return 0.0
        return self.turnos_aceitos / self.total_turnos


@dataclass
class RunnerResult:
    total_conversas: int
    conversas_por_tipo: dict[str, int]
    taxa_sucesso_global: float
    turnos_totais: int
    turnos_aceitos: int
    latencia_media_ms: float
    erros: list[str]
    conversas: list[ConversaResult]

    def resumo(self) -> str:
        linhas = [
            f"Conversas: {self.total_conversas}",
            f"Turnos: {self.turnos_totais} | Aceitos: {self.turnos_aceitos}",
            f"Taxa de sucesso: {self.taxa_sucesso_global:.1%}",
            f"Latência média: {self.latencia_media_ms:.0f} ms/turno",
            f"Erros críticos: {len(self.erros)}",
            "Por tipo: " + ", ".join(f"{k}={v}" for k, v in self.conversas_por_tipo.items()),
        ]
        return "\n".join(linhas)


# ─── Carregamento e classificação ────────────────────────────────────────────

def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


def _mensagens_paciente(conv: dict) -> list[str]:
    """Extrai textos das mensagens do paciente (fromMe=False)."""
    msgs = []
    for m in conv.get("messages") or []:
        if m.get("fromMe"):
            continue
        texto = (
            m.get("text")
            or (m.get("message") or {}).get("conversation")
            or (m.get("message") or {}).get("extendedTextMessage", {}).get("text")
            or ""
        )
        texto = str(texto).strip()
        if texto and len(texto) >= 2:
            msgs.append(texto)
    return msgs


def classificar_conversa(conv: dict) -> str:
    """Classifica uma conversa por tipo baseando-se nas mensagens do paciente."""
    paciente_msgs = _mensagens_paciente(conv)
    texto_total = _norm(" ".join(paciente_msgs))

    # Cancelamento tem prioridade sobre remarcação
    if any(t in texto_total for t in ("cancelar", "cancelamento", "desmarcar", "quero cancelar")):
        return "cancelamento"

    # Remarcação
    if any(t in texto_total for t in ("remarcar", "mudar horario", "alterar horario", "trocar horario", "reagendar", "preciso remarcar")):
        return "remarcacao"

    # Confirmação de presença
    if any(t in texto_total for t in ("confirmar presenca", "confirmar presença", "vou estar", "confirmo minha presenca")):
        return "confirmacao"

    # Casos especiais (outros)
    if any(t in texto_total for t in ("gravida", "gestante", "gestacao", "gravidez", "lipedema", "diabetes", "menor de", "crianca")):
        return "outros"

    # Dúvidas sem agendamento
    msgs_count = len(paciente_msgs)
    if msgs_count <= 2 and any(t in texto_total for t in ("quanto custa", "qual o valor", "como funciona", "informacao")):
        return "outros"

    return "agendamento"


def load_conversas(path: Path = CONVERSAS_PATH) -> list[dict]:
    """Carrega o arquivo de conversas exportadas."""
    if not path.exists():
        raise FileNotFoundError(f"conversas_export.json não encontrado em: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return data.get("conversations") or []


def selecionar_conversas(
    conversas: list[dict] | None = None,
    *,
    n_agendamento: int = 20,
    n_remarcacao: int = 10,
    n_cancelamento: int = 5,
    n_confirmacao: int = 5,
    n_outros: int = 10,
    seed: int = 42,
    min_msgs_paciente: int = 2,
) -> list[dict]:
    """
    Seleciona N conversas representativas de cada tipo.

    Retorna lista com até (n_agendamento + n_remarcacao + n_cancelamento +
    n_confirmacao + n_outros) conversas.
    """
    if conversas is None:
        conversas = load_conversas()

    rng = random.Random(seed)

    por_tipo: dict[str, list[dict]] = {
        "agendamento": [],
        "remarcacao": [],
        "cancelamento": [],
        "confirmacao": [],
        "outros": [],
    }

    for conv in conversas:
        msgs = _mensagens_paciente(conv)
        if len(msgs) < min_msgs_paciente:
            continue
        tipo = classificar_conversa(conv)
        por_tipo[tipo].append(conv)

    limites = {
        "agendamento": n_agendamento,
        "remarcacao": n_remarcacao,
        "cancelamento": n_cancelamento,
        "confirmacao": n_confirmacao,
        "outros": n_outros,
    }

    selecionadas: list[dict] = []
    for tipo, limite in limites.items():
        pool = por_tipo[tipo]
        # Preferir conversas mais longas (mais ricas)
        pool_sorted = sorted(pool, key=lambda c: len(_mensagens_paciente(c)), reverse=True)
        escolhidas = pool_sorted[:limite * 3]  # pega o triplo para diversificar
        rng.shuffle(escolhidas)
        selecionadas.extend(escolhidas[:limite])

    return selecionadas


# ─── Avaliação de qualidade ───────────────────────────────────────────────────

_PALAVRAS_PT = re.compile(
    r"\b(que|de|do|da|em|um|uma|para|com|por|mas|seu|sua|você|vou|está|esse|essa|isso|aqui|bem|não)\b",
    re.I,
)

_NUMEROS_BRENO = ["99205", "31992059211", "5531992059211"]


def avaliar_resposta(
    respostas: list[str],
    estado_antes: str,
    estado_depois: str,
    msg_paciente: str,
) -> tuple[bool, str | None]:
    """
    Verifica se as respostas do orchestrator são aceitáveis.

    Retorna (aceitavel, motivo_rejeicao).
    """
    texto = " ".join(respostas).strip()

    # Resposta vazia
    if not texto or len(texto) < 10:
        return False, "resposta_vazia"

    # Fallback de erro sistêmico
    if "instabilidade" in texto.lower() and len(texto) < 60:
        return False, "fallback_erro_sistemico"

    # Violação R1: número interno exposto
    for num in _NUMEROS_BRENO:
        if num in texto:
            return False, f"violacao_R1_breno:{num}"

    return True, None


# ─── Replay de conversa ───────────────────────────────────────────────────────

_PHONE_COUNTER = 0


def _proximo_phone() -> str:
    global _PHONE_COUNTER
    _PHONE_COUNTER += 1
    return f"5531989{_PHONE_COUNTER:06d}"


async def replay_conversa(conv: dict, phone: str | None = None) -> ConversaResult:
    """
    Replaya uma conversa real pelo orchestrator v2 e mede qualidade.

    Usa mock de tools para não depender de Dietbox/APIs externas.
    """
    from app.conversation.state import _mem_store
    import app.conversation.orchestrator as orch

    if phone is None:
        phone = _proximo_phone()

    conv_id = conv.get("chat", {}).get("id") or conv.get("remoteJid") or phone
    tipo = classificar_conversa(conv)
    msgs_paciente = _mensagens_paciente(conv)

    # Limita a 10 turnos por conversa para manter os testes rápidos
    msgs_paciente = msgs_paciente[:10]

    turnos: list[TurnoResult] = 0 and []  # tipo annotation workaround
    turnos = []
    turnos_aceitos = 0

    # Isola estado desta conversa (phone único por replay)
    phone_hash = orch._phone_hash(phone)

    async def _fake_complete_text_async(system: str = "", user: str = "", **kw: Any) -> str:
        """Substituto para complete_text_async — retorna JSON mínimo aceitável."""
        return '{"intent": "agendar_consulta", "confidence": 0.85, "entities": {}, "validacoes": {}}'

    import app.llm_client as _llm

    with (
        patch.object(orch, "call_tool", _fake_call_tool),
        patch.object(_llm, "complete_text_async", _fake_complete_text_async),
    ):
        import os
        # Garante que Gemini não é chamado (usa heurística)
        gemini_key_bak = os.environ.pop("GEMINI_API_KEY", None)
        try:
            for idx, msg_texto in enumerate(msgs_paciente):
                mensagem = {"type": "text", "text": msg_texto}
                estado_antes = "inicio"

                # Tenta carregar estado atual
                try:
                    from app.conversation.state import load_state
                    estado_atual = await load_state(phone_hash, phone)
                    estado_antes = estado_atual.get("estado") or "inicio"
                except Exception:
                    pass

                t0 = time.perf_counter()
                try:
                    resultado = await orch.processar_turno(phone, mensagem)
                    duracao_ms = (time.perf_counter() - t0) * 1000

                    respostas = [m.conteudo for m in resultado.mensagens_enviadas if m.conteudo]
                    estado_depois = resultado.novo_estado or estado_antes

                    aceitavel, motivo = avaliar_resposta(respostas, estado_antes, estado_depois, msg_texto)
                    if aceitavel:
                        turnos_aceitos += 1

                    turnos.append(TurnoResult(
                        turno_idx=idx,
                        mensagem_paciente=msg_texto[:80],
                        respostas_orchestrator=respostas,
                        estado_antes=estado_antes,
                        estado_depois=estado_depois,
                        aceitavel=aceitavel,
                        motivo_rejeicao=motivo,
                        duracao_ms=duracao_ms,
                    ))
                except Exception as exc:
                    duracao_ms = (time.perf_counter() - t0) * 1000
                    turnos.append(TurnoResult(
                        turno_idx=idx,
                        mensagem_paciente=msg_texto[:80],
                        respostas_orchestrator=[],
                        estado_antes=estado_antes,
                        estado_depois=estado_antes,
                        aceitavel=False,
                        motivo_rejeicao=f"excecao:{type(exc).__name__}",
                        duracao_ms=duracao_ms,
                    ))
        finally:
            # Limpa estado desta conversa
            _mem_store.pop(phone_hash, None)
            if gemini_key_bak is not None:
                os.environ["GEMINI_API_KEY"] = gemini_key_bak

    return ConversaResult(
        conversa_id=str(conv_id),
        tipo=tipo,
        total_turnos=len(turnos),
        turnos_aceitos=turnos_aceitos,
        turnos=turnos,
    )


# ─── Bateria completa ─────────────────────────────────────────────────────────

async def executar_bateria(
    conversas: list[dict],
    *,
    concorrente: bool = False,
) -> RunnerResult:
    """
    Executa replay de uma lista de conversas e agrega métricas.

    Args:
        conversas: lista retornada por selecionar_conversas()
        concorrente: se True, usa asyncio.gather (stress test)
    """
    if concorrente:
        resultados = await asyncio.gather(
            *[replay_conversa(conv) for conv in conversas],
            return_exceptions=True,
        )
    else:
        resultados = []
        for conv in conversas:
            r = await replay_conversa(conv)
            resultados.append(r)

    conv_results: list[ConversaResult] = []
    erros: list[str] = []
    for r in resultados:
        if isinstance(r, Exception):
            erros.append(f"excecao_bateria:{type(r).__name__}:{r}")
        else:
            conv_results.append(r)

    turnos_totais = sum(c.total_turnos for c in conv_results)
    turnos_aceitos = sum(c.turnos_aceitos for c in conv_results)
    taxa_global = turnos_aceitos / turnos_totais if turnos_totais else 0.0

    todas_latencias = [t.duracao_ms for c in conv_results for t in c.turnos]
    latencia_media = sum(todas_latencias) / len(todas_latencias) if todas_latencias else 0.0

    por_tipo: dict[str, int] = {}
    for c in conv_results:
        por_tipo[c.tipo] = por_tipo.get(c.tipo, 0) + 1

    return RunnerResult(
        total_conversas=len(conv_results),
        conversas_por_tipo=por_tipo,
        taxa_sucesso_global=taxa_global,
        turnos_totais=turnos_totais,
        turnos_aceitos=turnos_aceitos,
        latencia_media_ms=latencia_media,
        erros=erros,
        conversas=conv_results,
    )


# ─── Standalone ──────────────────────────────────────────────────────────────

async def _main() -> None:
    print("Carregando conversas...")
    conversas = load_conversas()
    print(f"Total no arquivo: {len(conversas)} conversas")

    selecionadas = selecionar_conversas(conversas)
    print(f"Selecionadas: {len(selecionadas)} conversas para replay\n")

    result = await executar_bateria(selecionadas)
    print(result.resumo())

    # Detalhes de falhas
    falhas = [
        (c.conversa_id, c.tipo, t)
        for c in result.conversas
        for t in c.turnos
        if not t.aceitavel
    ]
    if falhas:
        print(f"\nPrimeiras 10 falhas:")
        for conv_id, tipo, turno in falhas[:10]:
            print(f"  [{tipo}] {conv_id[:20]} turno={turno.turno_idx}: {turno.motivo_rejeicao}")
            print(f"    msg: {turno.mensagem_paciente[:60]}")
            print(f"    resp: {' | '.join(turno.respostas_orchestrator)[:80]}")


if __name__ == "__main__":
    asyncio.run(_main())
