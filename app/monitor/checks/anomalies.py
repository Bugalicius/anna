from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Message
from app.monitor import docker_client
from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import guarded_check, read_recent_jsonl, utcnow

CATEGORY = "Seguranca"


async def check_b2b_attempts() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=60)
    count = sum(1 for r in rows if "b2b" in str(r).lower())
    return CheckResult(
        check_id="security.b2b_attempts",
        category=CATEGORY,
        status=count == 0,
        severity=Severity.INFO,
        description="Tentativas B2B detectadas",
        detail=f"tentativas_b2b_1h={count}",
        metadata={"count": count},
    )


async def check_restrictions_today() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=24 * 60, max_lines=20000)
    count = sum(1 for r in rows if r.get("evento") == "restricao_atendimento")
    return CheckResult(
        check_id="security.restrictions_today",
        category=CATEGORY,
        status=count == 0,
        severity=Severity.INFO,
        description="Menor de 16 ou gestante detectado hoje",
        detail=f"restricoes_24h={count}",
        metadata={"count": count},
    )


async def check_spam_same_phone() -> CheckResult:
    def _query() -> tuple[int, str]:
        since = utcnow() - timedelta(minutes=5)
        with SessionLocal() as db:
            rows = (
                db.query(Message.conversation_id, func.count(Message.id))
                .filter(Message.direction == "inbound", Message.sent_at >= since)
                .group_by(Message.conversation_id)
                .all()
            )
        if not rows:
            return 0, ""
        conv_id, count = max(rows, key=lambda x: int(x[1]))
        return int(count), str(conv_id)

    max_count, conv_id = await asyncio.to_thread(_query)
    return CheckResult(
        check_id="security.spam_same_phone",
        category=CATEGORY,
        status=max_count <= 50,
        severity=Severity.ALERT,
        description="Menos de 50 mensagens do mesmo phone em 5min",
        detail=f"max_msgs_5min={max_count} conversation_id={conv_id}",
        suggested_action="Verificar bug de loop, ataque ou webhook duplicado.",
        metadata={"max_count": max_count},
    )


async def check_app_error_words() -> CheckResult:
    logs = await docker_client.container_logs("app", minutes=5, tail=600)
    needles = ("ERROR", "CRITICAL", "Exception", "Traceback")
    hits = [line for line in logs.splitlines() if any(n in line for n in needles)]
    return CheckResult(
        check_id="security.app_error_logs",
        category=CATEGORY,
        status=len(hits) == 0,
        severity=Severity.ALERT,
        description="Sem ERROR/CRITICAL/Exception nos logs do app em 5min",
        detail=(hits[-1][:700] if hits else "0 linhas com erro"),
        suggested_action="Abrir docker compose logs app --tail=200.",
        metadata={"count": len(hits)},
    )


async def check_retrying_messages() -> CheckResult:
    def _query() -> int:
        since = utcnow() - timedelta(minutes=30)
        with SessionLocal() as db:
            return (
                db.query(func.count(Message.id))
                .filter(Message.processing_status.in_(["retrying", "failed"]), Message.sent_at >= since)
                .scalar()
                or 0
            )

    count = await asyncio.to_thread(_query)
    return CheckResult(
        check_id="security.retrying_messages",
        category=CATEGORY,
        status=count <= 10,
        severity=Severity.ALERT,
        description="Poucas mensagens em retry/failed nos ultimos 30min",
        detail=f"retrying_failed_30min={count}",
        suggested_action="Verificar fila de retry e logs do webhook.",
        metadata={"count": count},
    )


async def _guard(check, check_id: str, description: str, severity: Severity) -> CheckResult:
    return await guarded_check(check_id, CATEGORY, severity, description, check)


CHECKS = [
    lambda: _guard(check_b2b_attempts, "security.b2b_attempts", "Tentativas B2B detectadas", Severity.INFO),
    lambda: _guard(check_restrictions_today, "security.restrictions_today", "Menor de 16 ou gestante detectado hoje", Severity.INFO),
    lambda: _guard(check_spam_same_phone, "security.spam_same_phone", "Menos de 50 mensagens do mesmo phone em 5min", Severity.ALERT),
    lambda: _guard(check_app_error_words, "security.app_error_logs", "Sem ERROR/CRITICAL/Exception nos logs do app em 5min", Severity.ALERT),
    lambda: _guard(check_retrying_messages, "security.retrying_messages", "Poucas mensagens em retry/failed nos ultimos 30min", Severity.ALERT),
]

