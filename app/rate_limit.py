from __future__ import annotations

import logging
import os
import time

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def is_whatsapp_rate_limited(phone_hash: str) -> bool:
    max_messages = int(os.environ.get("WHATSAPP_RATE_LIMIT_MAX_PER_HOUR", "30"))
    window_seconds = int(os.environ.get("WHATSAPP_RATE_LIMIT_WINDOW_SECONDS", "3600"))
    bucket = int(time.time() // window_seconds)
    key = f"rate:whatsapp:{phone_hash}:{bucket}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    try:
        r = aioredis.Redis.from_url(redis_url, decode_responses=True)
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, window_seconds + 60)
        await r.aclose()
    except Exception as e:
        logger.warning("Redis rate limit indisponivel para %s: %s", phone_hash[-4:], e)
        return False

    if count > max_messages:
        logger.warning(
            "Rate limit WhatsApp excedido para hash=%s count=%s limit=%s window=%ss",
            phone_hash[-8:],
            count,
            max_messages,
            window_seconds,
        )
        return True
    return False
