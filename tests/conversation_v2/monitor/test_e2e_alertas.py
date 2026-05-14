from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.monitor.analyzer import aggregate
from app.monitor.models import CheckResult, Severity


@pytest.mark.asyncio
async def test_e2e_falha_gera_alerta_e_dedup(monkeypatch):
    from app.monitor.alerter import Alerter
    from tests.conversation_v2.monitor.test_alerter import FakeRedis

    FakeRedis.store = {}
    monkeypatch.setenv("MONITOR_DRY_RUN", "true")
    monkeypatch.setattr("app.monitor.alerter.aioredis.Redis", FakeRedis)

    result = CheckResult(
        check_id="infra.app_container",
        category="Infraestrutura",
        status=False,
        severity=Severity.CRITICAL,
        description="Container app rodando",
        detail="exited",
        measured_at=datetime.now(UTC),
    )
    alert = aggregate([result])[0]
    alerter = Alerter()

    assert await alerter.send(alert) is True
    assert await alerter.send(alert) is False


def test_e2e_varios_alertas_ordenados_por_severidade():
    results = [
        CheckResult(check_id="z.alert", category="App", status=False, severity=Severity.ALERT, description="alert"),
        CheckResult(check_id="a.critical", category="Infra", status=False, severity=Severity.CRITICAL, description="critical"),
    ]

    alerts = aggregate(results)

    assert [a.check_id for a in alerts] == ["a.critical", "z.alert"]

