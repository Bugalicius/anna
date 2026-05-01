#!/usr/bin/env python3
"""
Script E2E: 50 conversas simuladas com agente Ana via /test/chat.

Usa endpoint HTTP /test/chat que simula conversas com mocks de WhatsApp.
"""

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s — %(name)s — %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Carregado .env de {env_path}")

try:
    from google import genai
    GEMINI_CLIENT = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    logger.info("Gemini client ok")
except Exception as e:
    logger.error(f"Gemini: {e}")
    sys.exit(1)

import httpx

@dataclass
class TurnoResult:
    turno: int
    paciente: str
    agente: list[str]

@dataclass
class CenarioResult:
    tipo: str
    idx: int
    phone: str
    sucesso: bool
    turnos: int
    tempo: float
    resultado: str
    transcrição: list[TurnoResult]
    erro: str = None

CENARIOS = [
    *[{"tipo": "fluxo_feliz", "idx": i, "msg1": "Oi, quero marcar consulta"} for i in range(10)],
    *[{"tipo": "desistencia", "idx": i, "msg1": "Quero agendar"} for i in range(5)],
    *[{"tipo": "troca_plano", "idx": i, "msg1": "Olá, agendar"} for i in range(5)],
    *[{"tipo": "resistencia_horarios", "idx": i, "msg1": "Preciso agendar urgente"} for i in range(5)],
    *[{"tipo": "comprovante_errado", "idx": i, "msg1": "Oi, agendar"} for i in range(5)],
    *[{"tipo": "remarcacao", "idx": i, "msg1": "Remarcar consulta"} for i in range(5)],
    *[{"tipo": "cancelamento", "idx": i, "msg1": "Cancelar agendamento"} for i in range(5)],
    *[{"tipo": "duvidas_clinicas", "idx": i, "msg1": "Dúvida sobre alimentação"} for i in range(5)],
    *[{"tipo": "fora_contexto", "idx": i, "msg1": "😂😂😂"} for i in range(5)],
]

def gerar_telefone(idx: int):
    return f"5511999990{idx+1:03d}"

async def gemini_proximo(historico, ultima_msg, tipo):
    try:
        hist = "\n".join(f"P: {h.paciente}\nA: {' | '.join(h.agente)}" for h in historico[-2:])
        resp = GEMINI_CLIENT.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Paciente em conversa com bot de agendamento. Histórico: {hist}\n\nÚltima resposta bot: {ultima_msg}\n\nSua próxima mensagem (sem explicações, informal, max 100 chars)? Se termina: [FIM]",
            config={"max_output_tokens": 100, "temperature": 0.8},
        )
        return resp.text.strip() or "[FIM]"
    except:
        return "[FIM]"

SEM = asyncio.Semaphore(2)

async def executar(cfg, app_url):
    tipo, idx = cfg["tipo"], cfg["idx"]
    phone = gerar_telefone(idx)

    t0 = time.time()
    trans = []
    resultado = "pendente"

    logger.info(f"[{tipo}#{idx}] {phone}")

    try:
        async with httpx.AsyncClient() as client:
            # reset
            try:
                await client.post(f"{app_url}/test/reset", json={"phone": phone}, timeout=5)
            except:
                pass

            turno = 0
            msg = cfg["msg1"]

            while turno < 20:
                resp = await client.post(
                    f"{app_url}/test/chat",
                    json={"phone": phone, "message": msg},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                respostas = data.get("responses", [])

                if not respostas:
                    break

                trans.append(TurnoResult(turno, msg, respostas))

                ultima = " ".join(respostas)
                if any(word in ultima.lower() for word in ["agendado", "confirmado", "pronto"]):
                    resultado = "concluido"
                    break

                proxima = await gemini_proximo(trans, ultima, tipo)
                if "[FIM]" in proxima.upper():
                    resultado = "abandonado"
                    break

                msg = proxima
                turno += 1
                await asyncio.sleep(0.2)

        sucesso = True
        erro = None
    except Exception as e:
        sucesso = False
        erro = str(e)[:100]
        resultado = "erro"
        trans = []

    tempo = time.time() - t0

    return CenarioResult(tipo, idx, phone, sucesso, len(trans), tempo, resultado, trans, erro)

async def main():
    app_url = "http://localhost:8000"

    logger.info("=" * 80)
    logger.info("TESTE E2E: 50 CONVERSAS")
    logger.info("=" * 80)

    t0 = time.time()

    tarefas = [asyncio.create_task(executar(cfg, app_url)) for cfg in CENARIOS]

    resultados = []
    for tarefa in asyncio.as_completed(tarefas):
        try:
            async with SEM:
                r = await tarefa
                resultados.append(r)
                logger.info(f"✓ [{r.tipo}#{r.idx}] {r.resultado} ({r.tempo:.1f}s)")
        except Exception as e:
            logger.error(f"Erro: {e}")

    # Relatório
    stats = {}
    for r in resultados:
        if r.tipo not in stats:
            stats[r.tipo] = {"total": 0, "ok": 0, "fail": 0}
        stats[r.tipo]["total"] += 1
        if r.sucesso and r.resultado != "erro":
            stats[r.tipo]["ok"] += 1
        else:
            stats[r.tipo]["fail"] += 1

    tempo_total = time.time() - t0
    total_ok = sum(1 for r in resultados if r.sucesso and r.resultado != "erro")

    relatorio = f"""# Relatório E2E — Agente Ana

**Data:** {datetime.now().isoformat()}
**Cenários:** {len(resultados)}/50
**Sucesso:** {total_ok}/{len(resultados)}
**Tempo:** {tempo_total/60:.1f}min

## Por Tipo

| Tipo | Total | OK | Fail |
|------|-------|----|----|
"""

    for tipo in sorted(stats.keys()):
        s = stats[tipo]
        relatorio += f"| {tipo} | {s['total']} | {s['ok']} | {s['fail']} |\n"

    # Amostra de transcrições
    relatorio += "\n## Amostra\n"
    for r in resultados[:3]:
        relatorio += f"\n### {r.tipo}#{r.idx} ({r.phone})\n"
        relatorio += f"**Resultado:** {r.resultado} | **Turnos:** {r.turnos} | **Tempo:** {r.tempo:.1f}s\n\n"
        if r.transcrição:
            relatorio += "| T | Paciente | Agente |\n|---|----------|--------|\n"
            for t in r.transcrição[:3]:
                p = t.paciente[:40].replace("|", "")
                a = (" | ".join(msg[:30] for msg in t.agente) if t.agente else "")[:80]
                relatorio += f"| {t.turno} | {p} | {a} |\n"

    relatorio += f"\n---\n*Teste E2E executado automaticamente*"

    relatorio_path = Path(__file__).parent / "relatorio_ponta_a_ponta.md"
    relatorio_path.write_text(relatorio)

    print(f"\n{'='*80}")
    print(f"Cenários: {len(resultados)}/50")
    print(f"Sucesso: {total_ok}")
    print(f"Tempo: {tempo_total/60:.1f}min")
    print(f"Relatório: {relatorio_path}")
    print(f"{'='*80}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.error(f"Erro: {e}")
        traceback.print_exc()
        sys.exit(1)
