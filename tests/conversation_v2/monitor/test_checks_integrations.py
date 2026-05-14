from __future__ import annotations

import httpx
import pytest
import respx


@pytest.mark.asyncio
@respx.mock
async def test_check_meta_api_alive(monkeypatch):
    from app.monitor.checks.integrations import check_meta_api_alive

    monkeypatch.setenv("META_ACCESS_TOKEN", "token")
    monkeypatch.setenv("META_PHONE_NUMBER_ID", "123")
    respx.get("https://graph.facebook.com/v19.0/123").mock(return_value=httpx.Response(200, json={}))

    result = await check_meta_api_alive()

    assert result.status is True
    assert result.check_id == "integrations.meta_api"


@pytest.mark.asyncio
async def test_check_gemini_env_configured(monkeypatch):
    from app.monitor.checks.integrations import check_gemini_env_configured

    monkeypatch.setenv("GEMINI_API_KEY", "fake")

    result = await check_gemini_env_configured()

    assert result.status is True

