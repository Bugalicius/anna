from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx

from app.config import get_meta_access_token, get_meta_phone_number_id
from app.monitor.models import CheckResult, Severity
from app.monitor.settings import get_settings
from app.monitor.utils import guarded_check

CATEGORY = "Integracoes"


async def check_gemini_alive() -> CheckResult:
    if not get_settings().enable_external_checks:
        return CheckResult(
            check_id="integrations.gemini",
            category=CATEGORY,
            status=True,
            severity=Severity.CRITICAL,
            description="Gemini API responde",
            detail="check externo desativado",
        )
    from app.llm_client import complete_text_async

    text = await asyncio.wait_for(
        complete_text_async(system="Responda apenas OK.", user="ok", max_tokens=2, temperature=0.0),
        timeout=10,
    )
    return CheckResult(
        check_id="integrations.gemini",
        category=CATEGORY,
        status=bool(text.strip()),
        severity=Severity.CRITICAL,
        description="Gemini API responde",
        detail=f"resposta={text[:20]!r}",
        suggested_action="Verificar GEMINI_API_KEY/quota.",
    )


async def check_dietbox_alive() -> CheckResult:
    if not get_settings().enable_external_checks:
        return CheckResult(
            check_id="integrations.dietbox",
            category=CATEGORY,
            status=True,
            severity=Severity.CRITICAL,
            description="Dietbox API responde",
            detail="check externo desativado",
        )
    from app.agents import dietbox_worker

    token_cache = Path(dietbox_worker.TOKEN_CACHE_PATH)
    token_data = dietbox_worker._token_valido()
    if not token_cache.exists() or not token_data:
        raise RuntimeError("cache de token Dietbox ausente/expirado; evitando login pesado no monitor")

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{dietbox_worker.DIETBOX_API}/local-atendimento",
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Accept": "application/json",
                "Origin": "https://dietbox.me",
            },
        )
    ok = resp.status_code in {200, 204}
    return CheckResult(
        check_id="integrations.dietbox",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="Dietbox API responde",
        detail=f"status={resp.status_code}",
        suggested_action="Verificar token/cache Dietbox e conectividade externa.",
    )


async def check_meta_api_alive() -> CheckResult:
    token = get_meta_access_token()
    phone_id = get_meta_phone_number_id()
    if not token or not phone_id:
        raise RuntimeError("token ou phone_number_id Meta ausente")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"https://graph.facebook.com/v19.0/{phone_id}",
            params={"fields": "display_phone_number,verified_name"},
            headers={"Authorization": f"Bearer {token}"},
        )
    ok = resp.status_code == 200
    return CheckResult(
        check_id="integrations.meta_api",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="Meta API token valido",
        detail=f"status={resp.status_code}",
        suggested_action="Verificar WHATSAPP_TOKEN/META_ACCESS_TOKEN.",
    )


async def check_meta_env_configured() -> CheckResult:
    ok = bool(get_meta_access_token() and get_meta_phone_number_id())
    return CheckResult(
        check_id="integrations.meta_env",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="Credenciais Meta configuradas",
        detail="ok" if ok else "token ou phone_number_id ausente",
        suggested_action="Corrigir .env do app/monitor.",
    )


async def check_gemini_env_configured() -> CheckResult:
    ok = bool(os.environ.get("GEMINI_API_KEY"))
    return CheckResult(
        check_id="integrations.gemini_env",
        category=CATEGORY,
        status=ok,
        severity=Severity.CRITICAL,
        description="GEMINI_API_KEY configurada",
        detail="ok" if ok else "GEMINI_API_KEY ausente",
        suggested_action="Corrigir GEMINI_API_KEY no .env.",
    )


async def _guard(check, check_id: str, description: str) -> CheckResult:
    return await guarded_check(check_id, CATEGORY, Severity.CRITICAL, description, check)


CHECKS = [
    lambda: _guard(check_gemini_env_configured, "integrations.gemini_env", "GEMINI_API_KEY configurada"),
    lambda: _guard(check_meta_env_configured, "integrations.meta_env", "Credenciais Meta configuradas"),
    lambda: _guard(check_gemini_alive, "integrations.gemini", "Gemini API responde"),
    lambda: _guard(check_dietbox_alive, "integrations.dietbox", "Dietbox API responde"),
    lambda: _guard(check_meta_api_alive, "integrations.meta_api", "Meta API token valido"),
]
