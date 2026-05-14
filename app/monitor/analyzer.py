from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.monitor.checks import anomalies, app_health, behavior, business, infra, integrations
from app.monitor.models import Alert, CheckResult, Severity, severity_rank

CheckCallable = Callable[[], Awaitable[CheckResult]]


def all_checks() -> list[CheckCallable]:
    checks: list[CheckCallable] = []
    for module in (infra, integrations, app_health, behavior, business, anomalies):
        checks.extend(module.CHECKS)
    return checks


async def run_all_checks(check_filter: str | None = None) -> list[CheckResult]:
    checks = all_checks()
    results = await asyncio.gather(*(check() for check in checks), return_exceptions=True)
    normalized: list[CheckResult] = []
    for idx, result in enumerate(results):
        if isinstance(result, CheckResult):
            normalized.append(result)
        else:
            normalized.append(
                CheckResult(
                    check_id=f"monitor.internal_check_{idx}",
                    category="Monitor",
                    status=False,
                    severity=Severity.CRITICAL,
                    description="Check do monitor falhou antes de retornar resultado",
                    detail=f"{type(result).__name__}: {result}",
                    suggested_action="Verificar bug no monitor.",
                )
            )
    if check_filter:
        normalized = [result for result in normalized if check_filter in result.check_id]
    return sorted(normalized, key=lambda r: (severity_rank(r.severity), r.check_id))


def aggregate(results: list[CheckResult]) -> list[Alert]:
    alerts = [
        Alert.from_result(result)
        for result in results
        if not result.status and result.severity in {Severity.CRITICAL, Severity.ALERT}
    ]
    return sorted(alerts, key=lambda a: (severity_rank(a.severity), a.check_id))
