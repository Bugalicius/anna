from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_check_app_container_ok(monkeypatch):
    from app.monitor.checks import infra

    monkeypatch.setattr(infra.docker_client, "container_running", AsyncMock(return_value=(True, "running")))

    result = await infra.check_app_container()

    assert result.status is True
    assert result.check_id == "infra.app_container"


@pytest.mark.asyncio
async def test_check_redis_container_falha(monkeypatch):
    from app.monitor.checks import infra

    monkeypatch.setattr(infra.docker_client, "container_running", AsyncMock(return_value=(False, "exited")))

    result = await infra.check_redis_container()

    assert result.status is False
    assert result.severity == "critical"
    assert "exited" in (result.detail or "")

