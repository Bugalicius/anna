from __future__ import annotations

import shutil
import time

import httpx

from app.monitor import docker_client
from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import guarded_check

CATEGORY = "Aplicacao"


async def check_app_memory() -> CheckResult:
    stats = await docker_client.container_stats("app")
    pct = docker_client.memory_percent(stats)
    return CheckResult(
        check_id="app.memory_usage",
        category=CATEGORY,
        status=pct < 80.0,
        severity=Severity.CRITICAL,
        description="Memoria do container app abaixo de 80%",
        detail=f"memoria={pct:.1f}%",
        suggested_action="Verificar vazamento ou reiniciar container app.",
        metadata={"memory_percent": pct},
    )


async def check_app_cpu() -> CheckResult:
    stats = await docker_client.container_stats("app")
    pct = docker_client.cpu_percent(stats)
    return CheckResult(
        check_id="app.cpu_usage",
        category=CATEGORY,
        status=pct < 80.0,
        severity=Severity.CRITICAL,
        description="CPU do container app abaixo de 80%",
        detail=f"cpu={pct:.1f}%",
        suggested_action="Verificar loop, carga alta ou reiniciar container app.",
        metadata={"cpu_percent": pct},
    )


async def check_disk_usage() -> CheckResult:
    usage = shutil.disk_usage("/")
    pct = (usage.used / usage.total) * 100.0
    return CheckResult(
        check_id="app.disk_usage",
        category=CATEGORY,
        status=pct < 85.0,
        severity=Severity.CRITICAL,
        description="Disco do VPS abaixo de 85%",
        detail=f"disco={pct:.1f}% livre={usage.free // (1024 ** 3)}GB",
        suggested_action="Limpar logs/imagens antigas ou aumentar disco.",
        metadata={"disk_percent": pct},
    )


async def check_nginx_500_logs() -> CheckResult:
    logs = await docker_client.container_logs("nginx", minutes=5, tail=500)
    hits = [line for line in logs.splitlines() if " 500 " in line or '" 500 ' in line]
    return CheckResult(
        check_id="app.nginx_500_last_5m",
        category=CATEGORY,
        status=len(hits) == 0,
        severity=Severity.CRITICAL,
        description="Sem erros 500 no Nginx nos ultimos 5min",
        detail=(hits[-1][:500] if hits else "0 erros 500"),
        suggested_action="Verificar app e logs do nginx.",
        metadata={"count": len(hits)},
    )


async def check_health_latency() -> CheckResult:
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(get_settings().app_health_url)
    latency = time.perf_counter() - started
    return CheckResult(
        check_id="app.health_latency",
        category=CATEGORY,
        status=resp.status_code == 200 and latency < 2.0,
        severity=Severity.CRITICAL,
        description="Latencia do /health abaixo de 2s",
        detail=f"status={resp.status_code} latency={latency:.3f}s",
        suggested_action="Verificar carga do app ou rede interna Docker.",
        metadata={"latency_seconds": latency},
    )


async def _guard(check, check_id: str, description: str) -> CheckResult:
    return await guarded_check(check_id, CATEGORY, Severity.CRITICAL, description, check)


CHECKS = [
    lambda: _guard(check_app_memory, "app.memory_usage", "Memoria do container app abaixo de 80%"),
    lambda: _guard(check_app_cpu, "app.cpu_usage", "CPU do container app abaixo de 80%"),
    lambda: _guard(check_disk_usage, "app.disk_usage", "Disco do VPS abaixo de 85%"),
    lambda: _guard(check_nginx_500_logs, "app.nginx_500_last_5m", "Sem erros 500 no Nginx nos ultimos 5min"),
    lambda: _guard(check_health_latency, "app.health_latency", "Latencia do /health abaixo de 2s"),
]

