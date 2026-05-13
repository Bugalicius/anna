"""Simula POST assinado de webhook da Meta WhatsApp Cloud API."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:
    pass


def _app_secret() -> str:
    return os.getenv("WHATSAPP_APP_SECRET") or os.getenv("META_APP_SECRET") or ""


def _payload(phone: str, text: str, message_id: str | None = None) -> dict:
    mid = message_id or f"wamid.test_diag_{uuid4().hex}"
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "test_entry",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "5531991394759"},
                            "contacts": [{"profile": {"name": "Tester"}, "wa_id": phone}],
                            "messages": [
                                {
                                    "from": phone,
                                    "id": mid,
                                    "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _post_once(url: str, secret: str, phone: str, text: str, message_id: str | None = None) -> dict:
    payload = _payload(phone, text, message_id)
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    started = time.perf_counter()
    response = requests.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
        },
        timeout=15,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    return {
        "url": url,
        "status": response.status_code,
        "latency_ms": latency_ms,
        "message_id": message["id"],
        "body": response.text[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("WEBHOOK_URL", "https://anna.vps-kinghost.net/webhook"))
    parser.add_argument("--phone", default=os.getenv("WEBHOOK_TEST_PHONE", "5511999990123"))
    parser.add_argument("--text", default="oi")
    parser.add_argument("--message-id")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0.0)
    args = parser.parse_args()

    secret = _app_secret()
    if not secret:
        print("Erro: defina WHATSAPP_APP_SECRET ou META_APP_SECRET no ambiente/.env", file=sys.stderr)
        return 2

    resultados: list[dict] = []
    for i in range(args.count):
        message_id = args.message_id if args.count == 1 else None
        result = _post_once(args.url, secret, args.phone, args.text, message_id)
        resultados.append(result)
        print(
            f"{i + 1}/{args.count} status={result['status']} "
            f"latency_ms={result['latency_ms']:.0f} message_id={result['message_id']} body={result['body']}"
        )
        if i < args.count - 1 and args.interval > 0:
            time.sleep(args.interval)

    latencies = [r["latency_ms"] for r in resultados]
    ok = sum(1 for r in resultados if r["status"] in (200, 204))
    resumo = {
        "total": len(resultados),
        "ok": ok,
        "latency_avg_ms": round(statistics.mean(latencies), 2) if latencies else 0,
        "latency_max_ms": round(max(latencies), 2) if latencies else 0,
    }
    print(json.dumps(resumo, ensure_ascii=False))
    return 0 if ok == len(resultados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
