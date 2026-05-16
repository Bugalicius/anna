from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MonitorSettings:
    enabled: bool
    dry_run: bool
    interval_seconds: int
    alerts_to: str
    critical_dedup_minutes: int
    alert_dedup_minutes: int
    persistent_status_minutes: int
    check_timeout_seconds: float
    app_health_url: str
    metrics_path: str
    log_dir: str
    docker_socket: str
    active_start_hour: int
    active_end_hour: int
    enable_external_checks: bool
    alert_template_name: str
    alert_template_language: str


def get_settings() -> MonitorSettings:
    return MonitorSettings(
        enabled=_bool_env("MONITOR_ENABLED", True),
        dry_run=_bool_env("MONITOR_DRY_RUN", False),
        interval_seconds=int(os.environ.get("MONITOR_INTERVAL_SECONDS", "60")),
        alerts_to=os.environ.get("MONITOR_ALERTS_TO") or os.environ.get("BRENO_PHONE", "5531992059211"),
        critical_dedup_minutes=int(os.environ.get("MONITOR_CRITICAL_DEDUP_MINUTES", "5")),
        alert_dedup_minutes=int(os.environ.get("MONITOR_ALERT_DEDUP_MINUTES", "30")),
        persistent_status_minutes=int(os.environ.get("MONITOR_STATUS_UPDATE_MINUTES", "60")),
        check_timeout_seconds=float(os.environ.get("MONITOR_CHECK_TIMEOUT_SECONDS", "10")),
        app_health_url=os.environ.get("MONITOR_APP_HEALTH_URL", "http://app:8000/health"),
        metrics_path=os.environ.get("MONITOR_METRICS_PATH", "logs/metrics.jsonl"),
        log_dir=os.environ.get("MONITOR_LOG_DIR", "logs/monitor"),
        docker_socket=os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock"),
        active_start_hour=int(os.environ.get("MONITOR_ACTIVE_START_HOUR", "8")),
        active_end_hour=int(os.environ.get("MONITOR_ACTIVE_END_HOUR", "22")),
        enable_external_checks=_bool_env("MONITOR_EXTERNAL_CHECKS_ENABLED", True),
        alert_template_name=os.environ.get("ESCALATION_TEMPLATE_NAME", ""),
        alert_template_language=os.environ.get("ESCALATION_TEMPLATE_LANGUAGE", "pt_BR"),
    )
