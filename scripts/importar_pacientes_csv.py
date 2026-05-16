"""
Le Pacientes.csv e carrega no Redis.

Chaves criadas:
  agente:paciente:{telefone} -> JSON com nome, email, sexo, primeiro_nome
  agente:pacientes:total     -> numero de registros importados

Telefone normalizado: remove tudo exceto digitos, garante começa com 55.

Uso:
  python scripts/importar_pacientes_csv.py
  REDIS_URL=redis://redis:6379 python scripts/importar_pacientes_csv.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

CSV_PATH = Path(__file__).parent.parent / "Pacientes.csv"


def normalizar_telefone(raw: str) -> str | None:
    """
    Entrada: '="+5538997424165"' ou '="553189869183"' ou '+55 31 9...'
    Saida: '5531999999999' (so digitos, comeca com 55)
    """
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if not digits.startswith("55"):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def primeiro_nome(nome_completo: str) -> str:
    parts = nome_completo.strip().split()
    return parts[0].capitalize() if parts else ""


async def importar(redis_url: str = "redis://localhost:6379") -> None:
    from redis.asyncio import Redis

    if not CSV_PATH.exists():
        print(f"ERRO: arquivo nao encontrado: {CSV_PATH}")
        return

    redis = Redis.from_url(redis_url, decode_responses=True)

    with open(CSV_PATH, encoding="latin-1") as f:
        lines = f.read().splitlines()

    # Pula linha 'sep=|' e header
    data_lines = [l for l in lines[2:] if l.strip()]

    importados = 0
    sem_telefone = 0
    duplicatas = 0

    for line in data_lines:
        cols = line.split("|")
        if len(cols) < 6:
            continue

        nome = cols[0].strip()
        email = cols[1].strip()
        sexo = cols[4].strip()
        celular_raw = cols[5].strip()

        if not nome:
            continue

        telefone = normalizar_telefone(celular_raw)
        if not telefone:
            sem_telefone += 1
            continue

        key = f"agente:paciente:{telefone}"
        existente = await redis.get(key)
        if existente:
            duplicatas += 1

        payload = {
            "nome": nome,
            "primeiro_nome": primeiro_nome(nome),
            "email": email,
            "sexo": sexo,
            "telefone": telefone,
            "origem": "csv_dietbox",
        }

        await redis.set(key, json.dumps(payload, ensure_ascii=False))
        importados += 1

    await redis.set("agente:pacientes:total", importados)
    await redis.aclose()

    print(f"Importados: {importados}")
    print(f"Sem telefone: {sem_telefone}")
    print(f"Atualizados (ja existiam): {duplicatas}")
    print(f"Total linhas processadas: {len(data_lines)}")


if __name__ == "__main__":
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    asyncio.run(importar(redis_url))
