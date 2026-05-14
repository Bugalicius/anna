from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.monitor.alerter import Alerter
from app.monitor.models import Alert, CheckResult, Severity


class FakeRedis:
    store: dict[str, str] = {}

    @classmethod
    def from_url(cls, *_args, **_kwargs):
        return cls()

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1

    async def aclose(self):
        return None


def _alert() -> Alert:
    return Alert(
        check_id="infra.redis_ping",
        category="Infra",
        severity=Severity.CRITICAL,
        name="Redis responde PING",
        detail="ping falhou",
        detected_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_alerter_dedup_segunda_falha_nao_envia(monkeypatch):
    FakeRedis.store = {}
    monkeypatch.setenv("MONITOR_DRY_RUN", "true")
    monkeypatch.setattr("app.monitor.alerter.aioredis.Redis", FakeRedis)

    alerter = Alerter()

    assert await alerter.send(_alert()) is True
    assert await alerter.send(_alert()) is False


@pytest.mark.asyncio
async def test_alerter_envia_resolucao(monkeypatch):
    FakeRedis.store = {
        "monitor:state:infra.redis_ping": json.dumps(
            {
                "status": "failing",
                "since": (datetime.now(UTC) - timedelta(minutes=12)).isoformat(),
                "last_sent": datetime.now(UTC).isoformat(),
                "severity": "critical",
                "name": "Redis responde PING",
            }
        )
    }
    monkeypatch.setenv("MONITOR_DRY_RUN", "true")
    monkeypatch.setattr("app.monitor.alerter.aioredis.Redis", FakeRedis)
    alerter = Alerter()
    alerter.send_resolution = AsyncMock()

    resolved = await alerter.check_resolutions(
        [
            CheckResult(
                check_id="infra.redis_ping",
                category="Infra",
                status=True,
                severity=Severity.CRITICAL,
                description="Redis responde PING",
            )
        ]
    )

    assert resolved == ["infra.redis_ping"]
    alerter.send_resolution.assert_awaited_once()

