from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


async def guarded_check(
    check_id: str,
    category: str,
    severity: Severity,
    description: str,
    func: Callable[[], Awaitable[CheckResult]],
    suggested_action: str | None = None,
) -> CheckResult:
    timeout = get_settings().check_timeout_seconds
    try:
        return await asyncio.wait_for(func(), timeout=timeout)
    except Exception as exc:
        return CheckResult(
            check_id=check_id,
            category=category,
            status=False,
            severity=severity,
            description=description,
            detail=f"{type(exc).__name__}: {exc}",
            suggested_action=suggested_action,
        )


def parse_dt(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def read_recent_jsonl(path: str, minutes: int, max_lines: int = 5000) -> list[dict[str, Any]]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    cutoff = utcnow() - timedelta(minutes=minutes)
    lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lines:]
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = parse_dt(row.get("timestamp") or row.get("ts") or row.get("measured_at"))
        if ts and ts < cutoff:
            continue
        rows.append(row)
    return rows


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * p))))
    return float(ordered[index])


def in_active_hours(now: datetime | None = None) -> bool:
    settings = get_settings()
    current = now or utcnow()
    hour = (current - timedelta(hours=3)).hour
    return settings.active_start_hour <= hour < settings.active_end_hour

