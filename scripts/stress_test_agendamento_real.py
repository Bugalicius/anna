"""Stress test de agendamento com paciente exigente.

O modo padrão usa o orchestrator real. Use ``--mock-tools`` para evitar chamadas
externas ao Dietbox/Meta em ambiente local. Se ``GEMINI_API_KEY`` estiver no
ambiente, o interpreter usa Gemini real.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from app.conversation import orchestrator  # noqa: E402
from app.conversation.state import load_state  # noqa: E402
from app.conversation.tools import ToolResult  # noqa: E402


CENARIOS = [
    {
        "nome": "Paciente recusa 3x, aceita 4a",
        "mensagens": [
            "oi",
            "Maria Silva",
            "primeira consulta",
            "emagrecer",
            "plano ouro",
            "presencial",
            "segunda às 8h",
            "nenhum serve, quero outra opção",
            "outro turno, por favor",
            "nenhum desses também",
            "outra semana",
            "nenhum serve ainda",
            "qualquer horário",
            "essa primeira eu aceito",
        ],
        "espera_escalacao": False,
    },
    {
        "nome": "Paciente impossivel escala",
        "mensagens": [
            "oi",
            "João Santos",
            "primeira consulta",
            "ganhar massa",
            "premium",
            "online",
            "domingo às 14h",
            "sábado então",
            "sexta às 22h",
            "11h",
            "13h",
            "12h",
            "qualquer horário",
        ],
        "espera_escalacao": True,
    },
    {
        "nome": "Paciente preco sensivel",
        "mensagens": [
            "oi",
            "Ana Costa",
            "primeira consulta",
            "emagrecer",
            "qual o valor mais barato?",
            "tá caro",
            "tem desconto?",
            "plano única então",
            "online",
            "terça às 9h",
            "ok essa serve",
            "PIX",
        ],
        "espera_escalacao": False,
    },
    {
        "nome": "Paciente muda de ideia",
        "mensagens": [
            "oi",
            "Carla Mendes",
            "primeira consulta",
            "emagrecer",
            "plano ouro",
            "espera, qual é mesmo o premium?",
            "fica ouro mesmo",
            "online",
            "ah não, presencial",
            "segunda às 8h",
            "terça às 8h",
            "essa ok",
        ],
        "espera_escalacao": False,
    },
    {
        "nome": "Paciente agressivo no meio",
        "mensagens": [
            "oi",
            "Pedro Lima",
            "primeira consulta",
            "ganhar massa",
            "plano ouro",
            "presencial",
            "segunda às 9h",
            "DEMORA DEMAIS PORRA",
            "tá brincando que custa isso?",
            "plano único então",
            "segunda às 9h",
        ],
        "espera_escalacao": False,
    },
]

SLOTS_MOCK = [
    {"datetime": "2026-05-18T08:00:00", "data_fmt": "segunda, 18/05/2026", "hora": "08h"},
    {"datetime": "2026-05-19T15:00:00", "data_fmt": "terça, 19/05/2026", "hora": "15h"},
    {"datetime": "2026-05-20T18:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "18h"},
    {"datetime": "2026-05-21T09:00:00", "data_fmt": "quinta, 21/05/2026", "hora": "09h"},
    {"datetime": "2026-05-22T10:00:00", "data_fmt": "sexta, 22/05/2026", "hora": "10h"},
    {"datetime": "2026-05-25T16:00:00", "data_fmt": "segunda, 25/05/2026", "hora": "16h"},
    {"datetime": "2026-05-26T19:00:00", "data_fmt": "terça, 26/05/2026", "hora": "19h"},
    {"datetime": "2026-05-27T08:00:00", "data_fmt": "quarta, 27/05/2026", "hora": "08h"},
    {"datetime": "2026-05-28T17:00:00", "data_fmt": "quinta, 28/05/2026", "hora": "17h"},
    {"datetime": "2026-05-29T15:00:00", "data_fmt": "sexta, 29/05/2026", "hora": "15h"},
]


async def _fake_call_tool(name: str, input: dict) -> ToolResult:  # noqa: A002
    if name == "consultar_slots":
        rejeitados = input.get("excluir_slots") or []
        slots = [s for s in SLOTS_MOCK if s not in rejeitados]
        return ToolResult(sucesso=True, dados={"slots": slots[:3], "match_exato": True, "slots_count": len(slots[:3])})
    if name == "gerar_link_pagamento":
        return ToolResult(sucesso=True, dados={"url": "https://pagamento.test/stress", "parcelas": 10})
    if name == "escalar_breno_silencioso":
        return ToolResult(sucesso=True, dados={"mock_escalado": True})
    return ToolResult(sucesso=True, dados={})


@dataclass
class TurnoStress:
    turno: int
    paciente: str
    respostas: list[str]
    estado: str | None
    latencia_ms: float
    erro: str | None = None


@dataclass
class CenarioStress:
    nome: str
    turnos: list[TurnoStress]
    erros: int
    latencia_media_ms: float
    latencia_p95_ms: float
    escalou: bool
    slots_invalidos: list[str]
    slots_repetidos: list[str]
    passou: bool


def _percentil(valores: list[float], pct: float) -> float:
    if not valores:
        return 0.0
    ordered = sorted(valores)
    idx = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[idx]


def _slot_lines(texto: str) -> list[str]:
    lines = []
    for line in texto.splitlines():
        low = line.lower()
        if not (re.match(r"^\s*(?:\d+[\.)]|📅)", line) or re.search(r"\b\d{1,2}/\d{1,2}/\d{4}\b", low)):
            continue
        if any(d in low for d in ("segunda", "terça", "terca", "quarta", "quinta", "sexta", "sábado", "sabado", "domingo")):
            if re.search(r"\b\d{1,2}(?::\d{2}|h)\b", low):
                lines.append(line.strip())
    return lines


def _slot_invalido(slot: str) -> bool:
    low = slot.lower()
    if "sábado" in low or "sabado" in low or "domingo" in low:
        return True
    if "sexta" in low and re.search(r"\b(18|19|20|21|22|23)(?::00|h)\b", low):
        return True
    return bool(re.search(r"\b(11|12|13|14|20|21|22|23)(?::00|h)\b", low))


async def executa_cenario(cenario: dict[str, Any], phone_suffix: str = "") -> CenarioStress:
    phone = f"5599999{abs(hash(cenario['nome'] + phone_suffix)) % 100000:05d}"
    turnos: list[TurnoStress] = []
    slots_vistos: set[str] = set()
    slots_invalidos: list[str] = []
    slots_repetidos: list[str] = []

    for i, msg in enumerate(cenario["mensagens"], start=1):
        inicio = time.perf_counter()
        try:
            resultado = await orchestrator.processar_turno(
                phone=phone,
                mensagem={"type": "text", "text": msg, "from": phone, "id": f"stress_{i}"},
            )
            latencia = (time.perf_counter() - inicio) * 1000
            respostas = [m.conteudo for m in resultado.mensagens_enviadas if m.conteudo]
            for resposta in respostas:
                for slot in _slot_lines(resposta):
                    if _slot_invalido(slot):
                        slots_invalidos.append(slot)
                    if slot in slots_vistos:
                        slots_repetidos.append(slot)
                    slots_vistos.add(slot)
            turnos.append(TurnoStress(i, msg, respostas, resultado.novo_estado, latencia, resultado.erro))
        except Exception as exc:  # noqa: BLE001
            turnos.append(TurnoStress(i, msg, [], None, (time.perf_counter() - inicio) * 1000, f"{type(exc).__name__}: {exc}"))

    phone_hash = orchestrator._phone_hash(phone)
    try:
        state = await load_state(phone_hash, phone)
    except Exception:
        state = {}
    all_text = " ".join(r for t in turnos for r in t.respostas)
    escalou = (state.get("estado") == "concluido_escalado") or ("equipe" in all_text.lower())
    latencias = [t.latencia_ms for t in turnos if not t.erro]
    erros = sum(1 for t in turnos if t.erro)
    passou = (
        erros == 0
        and not slots_invalidos
        and not slots_repetidos
        and _percentil(latencias, 95) < 3000
        and (not cenario.get("espera_escalacao") or escalou)
    )
    return CenarioStress(
        nome=cenario["nome"],
        turnos=turnos,
        erros=erros,
        latencia_media_ms=statistics.mean(latencias) if latencias else 0.0,
        latencia_p95_ms=_percentil(latencias, 95),
        escalou=escalou,
        slots_invalidos=slots_invalidos,
        slots_repetidos=slots_repetidos,
        passou=passou,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock-tools", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("resultado_stress_agendamento.json"))
    parser.add_argument("--cenario", default="", help="Filtra por trecho do nome do cenário.")
    args = parser.parse_args()

    selecionados = [c for c in CENARIOS if not args.cenario or args.cenario.lower() in c["nome"].lower()]
    print(f"GEMINI_API_KEY presente: {bool(os.getenv('GEMINI_API_KEY'))}")
    print(f"Mock tools: {args.mock_tools}")

    async def run_all() -> list[CenarioStress]:
        resultados = []
        for cenario in selecionados:
            print(f"\n=== {cenario['nome']} ===")
            resultado = await executa_cenario(cenario)
            resultados.append(resultado)
            for turno in resultado.turnos:
                print(f"T{turno.turno:02d} {turno.latencia_ms:.0f}ms | {turno.paciente[:60]}")
                if turno.erro:
                    print(f"  ERRO: {turno.erro}")
                elif turno.respostas:
                    print(f"  {turno.respostas[0][:140]}")
            print(f"PASSOU={resultado.passou} p95={resultado.latencia_p95_ms:.0f}ms escalou={resultado.escalou}")
        return resultados

    if args.mock_tools:
        with patch.object(orchestrator, "call_tool", _fake_call_tool):
            resultados = await run_all()
    else:
        resultados = await run_all()

    payload = {
        "gemini_api_key_presente": bool(os.getenv("GEMINI_API_KEY")),
        "mock_tools": args.mock_tools,
        "cenarios": [asdict(r) for r in resultados],
        "resumo": {
            "total": len(resultados),
            "passando": sum(1 for r in resultados if r.passou),
            "p95_global_ms": _percentil([t.latencia_ms for r in resultados for t in r.turnos if not t.erro], 95),
            "erros": sum(r.erros for r in resultados),
            "escalacoes": sum(1 for r in resultados if r.escalou),
        },
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n=== RESUMO ===")
    print(json.dumps(payload["resumo"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
