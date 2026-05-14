from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    ALERT = "alert"
    WARNING = "warning"
    INFO = "info"


class CheckResult(BaseModel):
    check_id: str
    category: str
    status: bool
    severity: Severity
    description: str
    detail: str | None = None
    suggested_action: str | None = None
    measured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class Alert(BaseModel):
    check_id: str
    category: str
    severity: Severity
    name: str
    detail: str
    suggested_action: str | None = None
    detected_at: datetime
    status_update: bool = False

    @classmethod
    def from_result(cls, result: CheckResult) -> "Alert":
        return cls(
            check_id=result.check_id,
            category=result.category,
            severity=result.severity,
            name=result.description,
            detail=result.detail or "Sem detalhe adicional.",
            suggested_action=result.suggested_action,
            detected_at=result.measured_at,
        )


def severity_rank(severity: Severity) -> int:
    return {
        Severity.CRITICAL: 0,
        Severity.ALERT: 1,
        Severity.WARNING: 2,
        Severity.INFO: 3,
    }[severity]

