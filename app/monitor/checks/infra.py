from __future__ import annotations

import asyncio

import httpx
import redis.asyncio as aioredis
from sqlalchemy import text

from app.database import SessionLocal
from app.monitor import docker_client
from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import guarded_check

CATEGORY = "Infraestrutura"


async def _container_check(service: str, severity: Severity = Severity.CRITICAL) -> CheckResult:
    ok, detail = await docker_client.container_running(service)
    return CheckResult(
        check_id=f"infra.{service}_container",
        category=CATEGORY,
        status=ok,
        severity=severity,
        description=f"Container {service} rodando",
        detail=detail,
        suggested_action=f"docker compose up -d {service}",
    )


async def check_app_container() -> CheckResult:
    return await _container_check("app")


async def check_redis_container() -> CheckResult:
    return await _container_check("redis")


async def check_postgres_container() -> CheckResult:
    return await _container_check("postgres")


async def check_nginx_container() -> CheckResult:
    return await _container_check("nginx")


async def check_health_endpoint() -> CheckResult:
    started = asyncio.get_running_loop().time()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(get_settings().app_health_url)
    latency = asyncio.get_running_loop().time() - started
    ok = resp.status_code == 200
    return CheckResult(
        check_id="infra.health_endpoint",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="/health responde 200",
        detail=f"status={resp.status_code} latency={latency:.3f}s",
        suggested_action="Verificar container app e nginx.",
        metadata={"latency_seconds": latency},
    )


async def check_postgres_alive() -> CheckResult:
    def _query() -> bool:
        with SessionLocal() as db:
            return db.execute(text("SELECT 1")).scalar() == 1

    ok = await asyncio.to_thread(_query)
    return CheckResult(
        check_id="infra.postgres_ping",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="Postgres aceita SELECT 1",
        detail="SELECT 1 ok" if ok else "SELECT 1 falhou",
        suggested_action="Verificar container postgres e DATABASE_URL.",
    )


async def check_redis_alive() -> CheckResult:
    r = aioredis.Redis.from_url(get_settings_from_env_redis_url(), decode_responses=True)
    try:
        pong = await r.ping()
    finally:
        await r.aclose()
    return CheckResult(
        check_id="infra.redis_ping",
        category=CATEGORY,
        status=bool(pong),
        severity=Severity.CRITICAL,
        description="Redis responde PING",
        detail=f"ping={pong}",
        suggested_action="Verificar container redis e REDIS_URL.",
    )


def get_settings_from_env_redis_url() -> str:
    import os

    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


async def _guard(check):
    return await guarded_check(
        check_id=check._monitor_id,  # type: ignore[attr-defined]
        category=CATEGORY,
        severity=Severity.CRITICAL,
        description=check._monitor_description,  # type: ignore[attr-defined]
        func=check,
    )


def _meta(check_id: str, description: str):
    def _decorator(fn):
        fn._monitor_id = check_id
        fn._monitor_description = description
        return fn

    return _decorator


check_app_container = _meta("infra.app_container", "Container app rodando")(check_app_container)
check_redis_container = _meta("infra.redis_container", "Container redis rodando")(check_redis_container)
check_postgres_container = _meta("infra.postgres_container", "Container postgres rodando")(check_postgres_container)
check_nginx_container = _meta("infra.nginx_container", "Container nginx rodando")(check_nginx_container)
check_health_endpoint = _meta("infra.health_endpoint", "/health responde 200")(check_health_endpoint)
check_postgres_alive = _meta("infra.postgres_ping", "Postgres aceita SELECT 1")(check_postgres_alive)
check_redis_alive = _meta("infra.redis_ping", "Redis responde PING")(check_redis_alive)


CHECKS = [
    lambda: _guard(check_app_container),
    lambda: _guard(check_redis_container),
    lambda: _guard(check_postgres_container),
    lambda: _guard(check_nginx_container),
    lambda: _guard(check_health_endpoint),
    lambda: _guard(check_postgres_alive),
    lambda: _guard(check_redis_alive),
]

