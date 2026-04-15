import hashlib
import hmac
import json
import os
import pytest
import respx
import httpx
from unittest.mock import patch
from app.meta_api import MetaAPIClient, verify_signature

PHONE_ID = "123456789"
TOKEN = "test-token"
APP_SECRET = "my-secret"


@pytest.fixture
def client():
    return MetaAPIClient(phone_number_id=PHONE_ID, access_token=TOKEN)


def test_verify_signature_valid():
    body = b'{"test": "data"}'
    sig = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, APP_SECRET) is True


def test_verify_signature_invalid():
    body = b'{"test": "data"}'
    assert verify_signature(body, "sha256=invalido", APP_SECRET) is False


def test_verify_signature_missing_prefix():
    body = b'{"test": "data"}'
    assert verify_signature(body, "sem-prefixo", APP_SECRET) is False


@pytest.mark.asyncio
@respx.mock
async def test_send_text_calls_meta_api(client):
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.abc"}]}))

    result = await client.send_text(to="5531999999999", text="Olá!")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["to"] == "5531999999999"
    assert payload["text"]["body"] == "Olá!"


@pytest.mark.asyncio
@respx.mock
async def test_send_template_calls_meta_api(client):
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.xyz"}]}))

    await client.send_template(to="5531999999999", template_name="follow_up_geral", language="pt_BR")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "follow_up_geral"


# ── Teste MetaAPIClient sem args ──────────────────────────────────────────────

def test_client_no_args_reads_env():
    """MetaAPIClient() sem argumentos deve ler env vars WHATSAPP_PHONE_NUMBER_ID e WHATSAPP_TOKEN."""
    with patch.dict(os.environ, {
        "WHATSAPP_PHONE_NUMBER_ID": "env_phone_id",
        "WHATSAPP_TOKEN": "env_token",
    }):
        client_no_args = MetaAPIClient()

    assert client_no_args._phone_id == "env_phone_id"
    assert "Bearer env_token" in client_no_args._headers["Authorization"]
