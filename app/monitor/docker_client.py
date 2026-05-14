from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

import httpx

from app.monitor.settings import get_settings


def _client() -> httpx.AsyncClient:
    socket_path = get_settings().docker_socket
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    return httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=5.0)


async def list_containers() -> list[dict[str, Any]]:
    if not os.path.exists(get_settings().docker_socket):
        raise RuntimeError("Docker socket indisponivel")
    async with _client() as client:
        resp = await client.get("/containers/json", params={"all": "true"})
        resp.raise_for_status()
        return resp.json()


async def container_by_service(service: str) -> dict[str, Any] | None:
    for container in await list_containers():
        labels = container.get("Labels") or {}
        if labels.get("com.docker.compose.service") == service:
            return container
    return None


async def container_running(service: str) -> tuple[bool, str]:
    container = await container_by_service(service)
    if not container:
        return False, "container nao encontrado"
    state = str(container.get("State") or "")
    status = str(container.get("Status") or "")
    return state == "running", f"state={state} status={status}"


async def container_stats(service: str) -> dict[str, Any]:
    container = await container_by_service(service)
    if not container:
        raise RuntimeError("container nao encontrado")
    cid = container["Id"]
    async with _client() as client:
        resp = await client.get(f"/containers/{cid}/stats", params={"stream": "false"})
        resp.raise_for_status()
        return resp.json()


def cpu_percent(stats: dict[str, Any]) -> float:
    cpu_delta = float(stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)) - float(
        stats.get("precpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0)
    )
    system_delta = float(stats.get("cpu_stats", {}).get("system_cpu_usage", 0)) - float(
        stats.get("precpu_stats", {}).get("system_cpu_usage", 0)
    )
    online_cpus = stats.get("cpu_stats", {}).get("online_cpus") or len(
        stats.get("cpu_stats", {}).get("cpu_usage", {}).get("percpu_usage") or []
    ) or 1
    if system_delta <= 0:
        return 0.0
    return max(0.0, (cpu_delta / system_delta) * float(online_cpus) * 100.0)


def memory_percent(stats: dict[str, Any]) -> float:
    mem = float(stats.get("memory_stats", {}).get("usage", 0))
    limit = float(stats.get("memory_stats", {}).get("limit", 0))
    if limit <= 0:
        return 0.0
    return max(0.0, (mem / limit) * 100.0)


async def container_logs(service: str, minutes: int = 5, tail: int = 300) -> str:
    container = await container_by_service(service)
    if not container:
        raise RuntimeError("container nao encontrado")
    cid = container["Id"]
    since = int((datetime.utcnow() - timedelta(minutes=minutes)).timestamp())
    async with _client() as client:
        resp = await client.get(
            f"/containers/{cid}/logs",
            params={"stdout": "1", "stderr": "1", "since": str(since), "tail": str(tail)},
        )
        resp.raise_for_status()
        raw = resp.content
    # Docker multiplexa logs quando TTY=false; remover header binario de 8 bytes por frame.
    chunks: list[bytes] = []
    i = 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i + 4 : i + 8], "big")
        if size <= 0 or i + 8 + size > len(raw):
            break
        chunks.append(raw[i + 8 : i + 8 + size])
        i += 8 + size
    if not chunks:
        chunks = [raw]
    return b"".join(chunks).decode("utf-8", errors="ignore")


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)

