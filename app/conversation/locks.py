"""Locks de processamento por telefone."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_LOCAL_LOCKS: dict[str, asyncio.Lock] = {}
_LOCAL_HELD: set[str] = set()
_REDIS_UNAVAILABLE_UNTIL = 0.0
_REDIS_BACKOFF_SECONDS = 30.0


async def acquire_processing_lock(phone: str, ttl_sec: int = 60) -> bool:
    """
    Tenta adquirir lock por telefone.

    Redis é a garantia entre workers/processos. Se Redis falhar, usa lock local
    para preservar o comportamento dentro do processo atual.
    """
    key = f"agente:lock:processing:{phone}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    global _REDIS_UNAVAILABLE_UNTIL
    try:
        if time.monotonic() >= _REDIS_UNAVAILABLE_UNTIL:
            r = aioredis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=0.2)
            acquired = await r.set(key, "1", ex=ttl_sec, nx=True)
            await r.aclose()
            return bool(acquired)
    except Exception as exc:
        _REDIS_UNAVAILABLE_UNTIL = time.monotonic() + _REDIS_BACKOFF_SECONDS
        logger.warning("Redis lock indisponivel para %s: %s", phone[-4:], exc)

    lock = _LOCAL_LOCKS.setdefault(phone, asyncio.Lock())
    if lock.locked() or phone in _LOCAL_HELD:
        return False
    await lock.acquire()
    _LOCAL_HELD.add(phone)
    return True


async def release_processing_lock(phone: str) -> None:
    key = f"agente:lock:processing:{phone}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        if time.monotonic() >= _REDIS_UNAVAILABLE_UNTIL:
            r = aioredis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=0.2)
            await r.delete(key)
            await r.aclose()
    except Exception as exc:
        logger.debug("Redis lock release falhou para %s: %s", phone[-4:], exc)

    lock = _LOCAL_LOCKS.get(phone)
    if lock and lock.locked() and phone in _LOCAL_HELD:
        _LOCAL_HELD.discard(phone)
        lock.release()
