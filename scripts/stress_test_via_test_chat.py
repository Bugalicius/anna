"""Stress HTTP via /test/chat contra localhost ou VPS."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx


CENARIOS = {
    "agendamento_dificil": [
        "oi",
        "Maria Silva",
        "primeira consulta",
        "emagrecer",
        "plano ouro",
        "presencial",
        "segunda às 8h",
        "nenhum serve, quero outra opção",
        "manhã não serve, tem outro horário?",
        "nenhum desses também",
        "essa primeira eu aceito",
    ]
}


def _percentil(valores: list[float], pct: float) -> float:
    if not valores:
        return 0.0
    ordered = sorted(valores)
    idx = min(len(ordered) - 1, max(0, round((pct / 100) * (len(ordered) - 1))))
    return ordered[idx]


async def _run_conversa(client: httpx.AsyncClient, target: str, idx: int, mensagens: list[str]) -> dict[str, Any]:
    phone = f"5599988{idx:06d}"
    latencias: list[float] = []
    erros: list[str] = []
    respostas_vazias = 0
    for msg in mensagens:
        started = time.perf_counter()
        try:
            resp = await client.post(f"{target}/test/chat", json={"phone": phone, "message": msg})
            latencias.append((time.perf_counter() - started) * 1000)
            if resp.status_code >= 500:
                erros.append(f"http_{resp.status_code}")
                continue
            data = resp.json()
            if not data.get("responses"):
                respostas_vazias += 1
        except Exception as exc:  # noqa: BLE001
            latencias.append((time.perf_counter() - started) * 1000)
            erros.append(f"{type(exc).__name__}:{exc}")
    return {"phone": phone, "latencias_ms": latencias, "erros": erros, "respostas_vazias": respostas_vazias}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="http://localhost:8000")
    parser.add_argument("--conversas", type=int, default=30)
    parser.add_argument("--paralelo", type=int, default=5)
    parser.add_argument("--cenario", default="agendamento_dificil")
    parser.add_argument("--output", type=Path, default=Path("resultado_stress_via_test_chat.json"))
    args = parser.parse_args()

    mensagens = CENARIOS[args.cenario]
    sem = asyncio.Semaphore(args.paralelo)

    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        async def guarded(i: int):
            async with sem:
                return await _run_conversa(client, args.target.rstrip("/"), i, mensagens)

        resultados = await asyncio.gather(*(guarded(i) for i in range(args.conversas)))

    latencias = [lat for r in resultados for lat in r["latencias_ms"]]
    erros = [e for r in resultados for e in r["erros"]]
    vazias = sum(r["respostas_vazias"] for r in resultados)
    resumo = {
        "target": args.target,
        "conversas": args.conversas,
        "paralelo": args.paralelo,
        "turnos": len(latencias),
        "erros": len(erros),
        "respostas_vazias": vazias,
        "taxa_sucesso": round((len(latencias) - len(erros) - vazias) / len(latencias), 4) if latencias else 0,
        "latencia_media_ms": round(statistics.mean(latencias), 2) if latencias else 0,
        "latencia_p50_ms": round(_percentil(latencias, 50), 2),
        "latencia_p95_ms": round(_percentil(latencias, 95), 2),
        "latencia_p99_ms": round(_percentil(latencias, 99), 2),
        "erros_amostra": erros[:20],
    }
    args.output.write_text(json.dumps({"resumo": resumo, "resultados": resultados}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

