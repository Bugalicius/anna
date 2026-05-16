from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func

from app.database import SessionLocal
from app.models import Message
from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import guarded_check, in_active_hours, percentile, read_recent_jsonl, utcnow

CATEGORY = "Comportamento"


async def check_turn_error_rate() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=10)
    turns = [r for r in rows if "estado_antes" in r or "duracao_ms" in r]
    errors = [r for r in turns if r.get("erro")]
    rate = (len(errors) / len(turns)) if turns else 0.0
    return CheckResult(
        check_id="behavior.turn_error_rate",
        category=CATEGORY,
        status=rate <= 0.05,
        severity=Severity.ALERT,
        description="Taxa de erro em processar_turno abaixo de 5%",
        detail=f"erros={len(errors)} turnos={len(turns)} taxa={rate:.1%}",
        suggested_action="Verificar logs do app e ultimos deploys.",
        metadata={"error_rate": rate, "turns": len(turns)},
    )


async def check_turn_latency_p95() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=10)
    values = [float(r.get("duracao_ms")) for r in rows if isinstance(r.get("duracao_ms"), (int, float))]
    p95 = percentile(values, 0.95)
    return CheckResult(
        check_id="behavior.turn_latency_p95",
        category=CATEGORY,
        status=p95 <= 5000,
        severity=Severity.WARNING,  # latência alta não indica sistema parado
        description="Latencia p95 de turno abaixo de 5s",
        detail=f"p95={p95:.0f}ms amostras={len(values)}",
        suggested_action="Verificar Gemini/Dietbox e carga do app.",
        metadata={"p95_ms": p95},
    )


async def check_state_loop() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=10)
    longest = 0
    offender = ""
    streaks: dict[str, tuple[str, int]] = {}
    for row in rows:
        phone_hash = str(row.get("phone_hash") or "")
        state = str(row.get("estado_depois") or "")
        if not phone_hash or not state:
            continue
        last_state, count = streaks.get(phone_hash, ("", 0))
        count = count + 1 if last_state == state else 1
        streaks[phone_hash] = (state, count)
        if count > longest:
            longest = count
            offender = f"{phone_hash[-8:]}:{state}"
    return CheckResult(
        check_id="behavior.state_loop",
        category=CATEGORY,
        status=longest <= 5,
        severity=Severity.ALERT,
        description="Nenhum estado com mais de 5 turnos consecutivos sem avancar",
        detail=f"maior_streak={longest} offender={offender or '-'}",
        suggested_action="Inspecionar historico do contato e regras do estado.",
        metadata={"longest_streak": longest},
    )


async def check_message_volume_active_hours() -> CheckResult:
    if not in_active_hours():
        return CheckResult(
            check_id="behavior.message_volume_zero",
            category=CATEGORY,
            status=True,
            severity=Severity.ALERT,
            description="Volume de mensagens nao zerou em horario ativo",
            detail="fora do horario ativo configurado",
        )

    def _count() -> int:
        since = utcnow() - timedelta(minutes=30)
        with SessionLocal() as db:
            return (
                db.query(func.count(Message.id))
                .filter(Message.direction == "inbound", Message.sent_at >= since)
                .scalar()
                or 0
            )

    count = await asyncio.to_thread(_count)
    return CheckResult(
        check_id="behavior.message_volume_zero",
        category=CATEGORY,
        status=count > 0,
        severity=Severity.ALERT,
        description="Volume de mensagens nao zerou em horario ativo",
        detail=f"inbound_30min={count}",
        suggested_action="Verificar webhook Meta, nginx e eventos recentes.",
        metadata={"inbound_30min": count},
    )


async def check_fallback_loop_events() -> CheckResult:
    rows = read_recent_jsonl(get_settings().metrics_path, minutes=10)
    count = sum(1 for r in rows if r.get("evento") == "fallback_loop_escalado")
    return CheckResult(
        check_id="behavior.fallback_loop_events",
        category=CATEGORY,
        status=count <= 3,
        severity=Severity.ALERT,
        description="Poucas escalacoes por loop de fallback em 10min",
        detail=f"fallback_loop_escalado={count}",
        suggested_action="Auditar intents/estados que estao caindo em fallback.",
        metadata={"count": count},
    )


async def _guard(check, check_id: str, description: str) -> CheckResult:
    return await guarded_check(check_id, CATEGORY, Severity.WARNING, description, check)


CHECKS = [
    lambda: _guard(check_turn_error_rate, "behavior.turn_error_rate", "Taxa de erro em processar_turno abaixo de 5%"),
    lambda: _guard(check_turn_latency_p95, "behavior.turn_latency_p95", "Latencia p95 de turno abaixo de 5s"),
    lambda: _guard(check_state_loop, "behavior.state_loop", "Nenhum estado com mais de 5 turnos consecutivos sem avancar"),
    lambda: _guard(check_message_volume_active_hours, "behavior.message_volume_zero", "Volume de mensagens nao zerou em horario ativo"),
    lambda: _guard(check_fallback_loop_events, "behavior.fallback_loop_events", "Poucas escalacoes por loop de fallback em 10min"),
]

