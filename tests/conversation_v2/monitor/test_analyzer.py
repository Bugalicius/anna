from __future__ import annotations

from datetime import UTC, datetime

from app.monitor.analyzer import aggregate, all_checks
from app.monitor.models import CheckResult, Severity


def test_monitor_tem_25_ou_mais_checks() -> None:
    assert len(all_checks()) >= 25


def test_aggregate_somente_alertas_enviaveis() -> None:
    results = [
        CheckResult(
            check_id="critical.fail",
            category="Infra",
            status=False,
            severity=Severity.CRITICAL,
            description="critico",
            measured_at=datetime.now(UTC),
        ),
        CheckResult(
            check_id="warning.fail",
            category="Negocio",
            status=False,
            severity=Severity.WARNING,
            description="warning",
            measured_at=datetime.now(UTC),
        ),
        CheckResult(
            check_id="ok",
            category="Infra",
            status=True,
            severity=Severity.CRITICAL,
            description="ok",
            measured_at=datetime.now(UTC),
        ),
    ]

    alerts = aggregate(results)

    assert [a.check_id for a in alerts] == ["critical.fail"]

