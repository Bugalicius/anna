from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Contact, PendingEscalation
from app.monitor.models import CheckResult, Severity
from app.monitor.utils import guarded_check, utcnow

CATEGORY = "Negocio"


async def check_conversions_vs_history() -> CheckResult:
    def _query() -> tuple[int, float]:
        now = utcnow()
        day_ago = now - timedelta(hours=24)
        week_start = now - timedelta(days=8)
        with SessionLocal() as db:
            last_24h = (
                db.query(func.count(Contact.id))
                .filter(Contact.stage.in_(["agendado", "concluido"]), Contact.last_message_at >= day_ago)
                .scalar()
                or 0
            )
            previous_7d = (
                db.query(func.count(Contact.id))
                .filter(
                    Contact.stage.in_(["agendado", "concluido"]),
                    Contact.last_message_at >= week_start,
                    Contact.last_message_at < day_ago,
                )
                .scalar()
                or 0
            )
        return int(last_24h), float(previous_7d) / 7.0

    last_24h, avg = await asyncio.to_thread(_query)
    ok = True if avg < 2 else last_24h >= avg * 0.5
    return CheckResult(
        check_id="business.conversions_24h",
        category=CATEGORY,
        status=ok,
        severity=Severity.WARNING,
        description="Conversoes 24h dentro da media historica",
        detail=f"conversoes_24h={last_24h} media_7d={avg:.1f}",
        metadata={"conversions_24h": last_24h, "avg_7d": avg},
    )


async def check_payment_abandonment_rate() -> CheckResult:
    def _query() -> tuple[int, int]:
        since = utcnow() - timedelta(hours=24)
        with SessionLocal() as db:
            waiting = (
                db.query(func.count(Contact.id))
                .filter(Contact.stage == "aguardando_pagamento", Contact.last_message_at >= since)
                .scalar()
                or 0
            )
            scheduled = (
                db.query(func.count(Contact.id))
                .filter(Contact.stage.in_(["agendado", "concluido"]), Contact.last_message_at >= since)
                .scalar()
                or 0
            )
        return int(waiting), int(scheduled)

    waiting, scheduled = await asyncio.to_thread(_query)
    total = waiting + scheduled
    rate = (waiting / total) if total else 0.0
    return CheckResult(
        check_id="business.payment_abandonment",
        category=CATEGORY,
        status=rate <= 0.50,
        severity=Severity.WARNING,
        description="Abandono no pagamento abaixo de 50%",
        detail=f"aguardando={waiting} agendados={scheduled} taxa={rate:.1%}",
        metadata={"rate": rate},
    )


async def check_cancellation_rate() -> CheckResult:
    def _query() -> tuple[int, int]:
        since = utcnow() - timedelta(hours=24)
        with SessionLocal() as db:
            canceled = (
                db.query(func.count(Contact.id))
                .filter(Contact.stage == "cancelado", Contact.last_message_at >= since)
                .scalar()
                or 0
            )
            scheduled = (
                db.query(func.count(Contact.id))
                .filter(Contact.stage.in_(["agendado", "concluido"]), Contact.last_message_at >= since)
                .scalar()
                or 0
            )
        return int(canceled), int(scheduled)

    canceled, scheduled = await asyncio.to_thread(_query)
    total = canceled + scheduled
    rate = (canceled / total) if total else 0.0
    return CheckResult(
        check_id="business.cancellation_rate",
        category=CATEGORY,
        status=rate <= 0.30,
        severity=Severity.WARNING,
        description="Cancelamentos abaixo de 30% dos agendamentos do dia",
        detail=f"cancelados={canceled} agendados={scheduled} taxa={rate:.1%}",
        metadata={"rate": rate},
    )


async def check_escalations_volume() -> CheckResult:
    def _query() -> int:
        since = utcnow() - timedelta(hours=1)
        with SessionLocal() as db:
            return (
                db.query(func.count(PendingEscalation.id))
                .filter(PendingEscalation.created_at >= since)
                .scalar()
                or 0
            )

    count = await asyncio.to_thread(_query)
    return CheckResult(
        check_id="business.escalations_1h",
        category=CATEGORY,
        status=count <= 10,
        severity=Severity.ALERT,
        description="Menos de 10 escalacoes pro Breno em 1h",
        detail=f"escalacoes_1h={count}",
        suggested_action="Verificar se ha loop de fallback ou problema operacional.",
        metadata={"count": count},
    )


async def check_open_payment_contacts() -> CheckResult:
    def _query() -> int:
        since = utcnow() - timedelta(hours=4)
        with SessionLocal() as db:
            return (
                db.query(func.count(Contact.id))
                .filter(Contact.stage == "aguardando_pagamento", Contact.last_message_at >= since)
                .scalar()
                or 0
            )

    count = await asyncio.to_thread(_query)
    return CheckResult(
        check_id="business.open_payments_4h",
        category=CATEGORY,
        status=count <= 20,
        severity=Severity.WARNING,
        description="Fila recente de pagamentos pendentes em volume normal",
        detail=f"aguardando_pagamento_4h={count}",
        metadata={"count": count},
    )


async def _guard(check, check_id: str, description: str, severity: Severity) -> CheckResult:
    return await guarded_check(check_id, CATEGORY, severity, description, check)


CHECKS = [
    lambda: _guard(check_conversions_vs_history, "business.conversions_24h", "Conversoes 24h dentro da media historica", Severity.WARNING),
    lambda: _guard(check_payment_abandonment_rate, "business.payment_abandonment", "Abandono no pagamento abaixo de 50%", Severity.WARNING),
    lambda: _guard(check_cancellation_rate, "business.cancellation_rate", "Cancelamentos abaixo de 30% dos agendamentos do dia", Severity.WARNING),
    lambda: _guard(check_escalations_volume, "business.escalations_1h", "Menos de 10 escalacoes pro Breno em 1h", Severity.ALERT),
    lambda: _guard(check_open_payment_contacts, "business.open_payments_4h", "Fila recente de pagamentos pendentes em volume normal", Severity.WARNING),
]

