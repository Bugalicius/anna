from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.monitor.alerter import Alerter
from app.monitor.analyzer import aggregate, run_all_checks
from app.monitor.settings import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def run_once(check_filter: str | None = None) -> int:
    alerter = Alerter()
    results = await run_all_checks(check_filter=check_filter)
    await alerter.record_results(results)
    alerts = aggregate(results)
    for alert in alerts:
        await alerter.send(alert)
    await alerter.check_resolutions(results)
    ok_count = sum(1 for r in results if r.status)
    logger.info("Monitor run completo: total=%d ok=%d alerts=%d", len(results), ok_count, len(alerts))
    return 0 if all(r.status or r.severity.value in {"warning", "info"} for r in results) else 1


async def main_loop(check_filter: str | None = None) -> None:
    settings = get_settings()
    if not settings.enabled:
        logger.warning("MONITOR_ENABLED=false; encerrando")
        return
    while True:
        try:
            await run_once(check_filter=check_filter)
        except Exception:
            logger.exception("Monitor loop error")
        await asyncio.sleep(settings.interval_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor de producao do Agente Ana")
    parser.add_argument("--once", action="store_true", help="Executa uma rodada e encerra")
    parser.add_argument("--check", default=None, help="Filtro simples por check_id, ex: infra.redis_container")
    return parser.parse_args()


def cli() -> None:
    args = parse_args()
    if args.once:
        raise SystemExit(asyncio.run(run_once(check_filter=args.check)))
    asyncio.run(main_loop(check_filter=args.check))


if __name__ == "__main__":
    cli()
