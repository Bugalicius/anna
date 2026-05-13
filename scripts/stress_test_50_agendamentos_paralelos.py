"""Executa 50 agendamentos difíceis em paralelo usando o stress de agendamento."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.conversation import orchestrator  # noqa: E402
from scripts.stress_test_agendamento_real import CENARIOS, _fake_call_tool, _percentil, executa_cenario  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversas", type=int, default=50)
    parser.add_argument("--paralelo", type=int, default=10)
    parser.add_argument("--mock-tools", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("resultado_stress_50_agendamentos.json"))
    args = parser.parse_args()

    sem = asyncio.Semaphore(args.paralelo)
    cenario = CENARIOS[0]

    async def run_one(i: int):
        async with sem:
            return await executa_cenario(cenario, phone_suffix=str(i))

    async def run_all():
        return await asyncio.gather(*(run_one(i) for i in range(args.conversas)))

    if args.mock_tools:
        with patch.object(orchestrator, "call_tool", _fake_call_tool):
            resultados = await run_all()
    else:
        resultados = await run_all()

    latencias = [t.latencia_ms for r in resultados for t in r.turnos if not t.erro]
    erros = sum(r.erros for r in resultados)
    resumo = {
        "conversas": args.conversas,
        "paralelo": args.paralelo,
        "mock_tools": args.mock_tools,
        "sucesso": sum(1 for r in resultados if r.passou),
        "taxa_sucesso": round(sum(1 for r in resultados if r.passou) / len(resultados), 4) if resultados else 0,
        "erros": erros,
        "latencia_media_ms": round(statistics.mean(latencias), 2) if latencias else 0,
        "latencia_p50_ms": round(_percentil(latencias, 50), 2),
        "latencia_p95_ms": round(_percentil(latencias, 95), 2),
        "latencia_p99_ms": round(_percentil(latencias, 99), 2),
    }
    args.output.write_text(
        json.dumps({"resumo": resumo, "resultados": [asdict(r) for r in resultados]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

