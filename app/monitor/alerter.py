from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import redis.asyncio as aioredis

from app.monitor.models import Alert, CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import parse_dt, utcnow

logger = logging.getLogger(__name__)


def _redis_url() -> str:
    import os

    return os.environ.get("REDIS_URL", "redis://redis:6379/0")


class Alerter:
    _local_state: dict[str, dict] = {}
    _redis_disabled_until: float = 0.0

    def __init__(self) -> None:
        self.settings = get_settings()

    async def _redis(self):
        if time.monotonic() < self._redis_disabled_until:
            return None
        return aioredis.Redis.from_url(_redis_url(), decode_responses=True)

    def _state_key(self, check_id: str) -> str:
        return f"monitor:state:{check_id}"

    def _history_path(self) -> Path:
        path = Path(self.settings.log_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{utcnow().date().isoformat()}.jsonl"

    async def record_result(self, result: CheckResult) -> None:
        payload = result.model_dump(mode="json")
        payload["timestamp"] = utcnow().isoformat()
        try:
            with self._history_path().open("a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            logger.warning("Falha ao gravar historico monitor: %s", exc)

    async def record_results(self, results: list[CheckResult]) -> None:
        for result in results:
            await self.record_result(result)

    def _dedup_minutes(self, severity: Severity) -> int:
        if severity == Severity.CRITICAL:
            return self.settings.critical_dedup_minutes
        return self.settings.alert_dedup_minutes

    async def should_send(self, alert: Alert) -> tuple[bool, bool]:
        if alert.severity not in {Severity.CRITICAL, Severity.ALERT}:
            return False, False

        now = utcnow()
        key = self._state_key(alert.check_id)
        r = await self._redis()
        try:
            raw = await r.get(key) if r is not None else None
            state = json.loads(raw) if raw else {}
            if r is None:
                state = self._local_state.get(key, {})
            since = state.get("since") or now.isoformat()
            last_sent = parse_dt(state.get("last_sent"))
            is_update = bool(raw)
            if r is None:
                is_update = bool(state)
            min_gap = self.settings.persistent_status_minutes if is_update else self._dedup_minutes(alert.severity)
            if last_sent and (now - last_sent).total_seconds() < min_gap * 60:
                updated = {**state, "status": "failing", "last_seen": now.isoformat()}
                if r is not None:
                    await r.set(key, json.dumps(updated, ensure_ascii=False), ex=7 * 24 * 3600)
                else:
                    self._local_state[key] = updated
                return False, is_update

            payload = {
                "status": "failing",
                "since": since,
                "last_seen": now.isoformat(),
                "last_sent": now.isoformat(),
                "severity": alert.severity.value,
                "name": alert.name,
            }
            if r is not None:
                await r.set(key, json.dumps(payload, ensure_ascii=False), ex=7 * 24 * 3600)
            else:
                self._local_state[key] = payload
            return True, is_update
        except Exception as exc:
            logger.warning("Redis indisponivel para dedup do monitor, usando memoria local: %s", exc)
            self._redis_disabled_until = time.monotonic() + 60
            state = self._local_state.get(key, {})
            since = state.get("since") or now.isoformat()
            last_sent = parse_dt(state.get("last_sent"))
            is_update = bool(state)
            min_gap = self.settings.persistent_status_minutes if is_update else self._dedup_minutes(alert.severity)
            if last_sent and (now - last_sent).total_seconds() < min_gap * 60:
                self._local_state[key] = {**state, "status": "failing", "last_seen": now.isoformat()}
                return False, is_update
            self._local_state[key] = {
                "status": "failing",
                "since": since,
                "last_seen": now.isoformat(),
                "last_sent": now.isoformat(),
                "severity": alert.severity.value,
                "name": alert.name,
            }
            return True, is_update
        finally:
            if r is not None:
                await r.aclose()

    async def send(self, alert: Alert) -> bool:
        should, is_update = await self.should_send(alert)
        if not should:
            return False
        alert.status_update = is_update
        text = self._format_alert(alert)
        if self.settings.dry_run:
            logger.warning("MONITOR_DRY_RUN alert would be sent: %s", text.replace("\n", " | "))
            return True

        from app.meta_api import MetaAPIClient

        try:
            await MetaAPIClient().send_text(self.settings.alerts_to, text)
            logger.warning("Alerta monitor enviado check_id=%s severity=%s", alert.check_id, alert.severity.value)
            return True
        except Exception as exc:
            logger.exception("Falha ao enviar alerta monitor check_id=%s: %s", alert.check_id, exc)
            return False

    async def check_resolutions(self, results: list[CheckResult]) -> list[str]:
        resolved: list[str] = []
        r = await self._redis()
        if r is None:
            return await self._check_resolutions_local(results)
        try:
            for result in results:
                if not result.status:
                    continue
                key = self._state_key(result.check_id)
                raw = await r.get(key)
                if not raw:
                    continue
                state = json.loads(raw)
                since = parse_dt(state.get("since")) or utcnow()
                duration_min = max(0, int((utcnow() - since).total_seconds() // 60))
                await r.delete(key)
                severity = Severity(state.get("severity", Severity.ALERT.value))
                if severity in {Severity.CRITICAL, Severity.ALERT}:
                    await self.send_resolution(
                        check_id=result.check_id,
                        name=state.get("name") or result.description,
                        duration_min=duration_min,
                    )
                    resolved.append(result.check_id)
            resolved.extend(await self._check_resolutions_local(results))
            return sorted(set(resolved))
        except Exception as exc:
            logger.warning("Redis indisponivel para resolucoes do monitor, usando memoria local: %s", exc)
            self._redis_disabled_until = time.monotonic() + 60
            return await self._check_resolutions_local(results)
        finally:
            await r.aclose()

    async def _check_resolutions_local(self, results: list[CheckResult]) -> list[str]:
        resolved: list[str] = []
        for result in results:
            if not result.status:
                continue
            key = self._state_key(result.check_id)
            state = self._local_state.pop(key, None)
            if not state:
                continue
            since = parse_dt(state.get("since")) or utcnow()
            duration_min = max(0, int((utcnow() - since).total_seconds() // 60))
            severity = Severity(state.get("severity", Severity.ALERT.value))
            if severity in {Severity.CRITICAL, Severity.ALERT}:
                await self.send_resolution(
                    check_id=result.check_id,
                    name=state.get("name") or result.description,
                    duration_min=duration_min,
                )
                resolved.append(result.check_id)
        return resolved

    async def send_resolution(self, check_id: str, name: str, duration_min: int) -> None:
        text = (
            "✅ RESOLVIDO\n\n"
            f"{name} voltou ao normal.\n"
            f"Duração do incidente: {duration_min} minutos\n"
            f"Check: {check_id}"
        )
        if self.settings.dry_run:
            logger.warning("MONITOR_DRY_RUN resolution would be sent: %s", text.replace("\n", " | "))
            return
        from app.meta_api import MetaAPIClient

        try:
            await MetaAPIClient().send_text(self.settings.alerts_to, text)
            logger.warning("Resolucao monitor enviada check_id=%s", check_id)
        except Exception as exc:
            logger.exception("Falha ao enviar resolucao monitor check_id=%s: %s", check_id, exc)

    def _format_alert(self, alert: Alert) -> str:
        title = "🚨 ALERTA CRÍTICO" if alert.severity == Severity.CRITICAL else "⚠️ ALERTA"
        if alert.status_update:
            title = "🚨 STATUS: ainda em alerta" if alert.severity == Severity.CRITICAL else "⚠️ STATUS: ainda em alerta"
        action = alert.suggested_action or "Verificar logs do monitor e do app."
        return (
            f"{title}\n\n"
            f"{alert.name}\n"
            f"Categoria: {alert.category}\n"
            f"Detectado: {alert.detected_at.astimezone(UTC).isoformat()}\n"
            f"Detalhe: {alert.detail}\n\n"
            f"Ação sugerida: {action}"
        )
