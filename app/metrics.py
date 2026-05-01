from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LOG_PATH = Path(os.environ.get("METRICS_JSONL_PATH", "logs/metrics.jsonl"))


def write_turn_metric(event: dict) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat(),
        **event,
    }
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.warning("Falha ao gravar metricas JSONL: %s", e)


async def reset_error_count(phone_hash: str) -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        await r.delete(f"errors:turn:{phone_hash}")
        await r.aclose()
    except Exception:
        pass


async def record_turn_error(phone_hash: str, reason: str) -> int:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        key = f"errors:turn:{phone_hash}"
        count = await r.incr(key)
        await r.expire(key, 86400)
        await r.aclose()
    except Exception as e:
        logger.warning("Falha ao registrar erro consecutivo: %s", e)
        return 0

    if count > 3:
        await alert_critical_error(phone_hash, reason)
    return int(count)


async def alert_critical_error(phone_hash: str, reason: str) -> None:
    numero_breno = os.environ.get("NUMERO_INTERNO", "5531992059211")
    try:
        from app.meta_api import MetaAPIClient

        meta = MetaAPIClient()
        await meta.send_text(
            numero_breno,
            f"Ana: erro crítico no atendimento de {phone_hash[-12:]}. Verificar logs.",
        )
        logger.warning("Alerta critico enviado para Breno hash=%s reason=%s", phone_hash[-8:], reason)
    except Exception as e:
        logger.error("Falha ao enviar alerta critico hash=%s: %s", phone_hash[-8:], e)


def read_recent_errors(limit: int = 20) -> list[dict]:
    if not _LOG_PATH.exists():
        return []
    rows: list[dict] = []
    try:
        lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()[-500:]
        for line in reversed(lines):
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("error"):
                rows.append(item)
                if len(rows) >= limit:
                    break
    except Exception as e:
        logger.warning("Falha ao ler erros recentes: %s", e)
    return rows
