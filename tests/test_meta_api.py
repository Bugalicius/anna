import hashlib
import hmac
import json
import os
from pathlib import Path
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


@pytest.mark.asyncio
@respx.mock
async def test_send_typing_indicator_payload(client):
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"success": True}))

    await client.send_typing_indicator(to="5531999999999", message_id="wamid.typing")

    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.typing",
        "typing_indicator": {"type": "text"},
    }


@pytest.mark.asyncio
@respx.mock
async def test_send_typing_indicator_ignora_message_id_invalido(client):
    route = respx.post(f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages")

    await client.send_typing_indicator(to="5531999999999", message_id="batch:abc")

    assert not route.called


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


def test_client_no_args_reads_meta_aliases_without_whatsapp_env():
    """MetaAPIClient() deve funcionar quando apenas META_* estiver configurado."""
    env = {
        "META_PHONE_NUMBER_ID": "meta_phone_id",
        "META_ACCESS_TOKEN": "meta_token",
        "WHATSAPP_PHONE_NUMBER_ID": "",
        "WHATSAPP_TOKEN": "",
    }
    with patch.dict(os.environ, env, clear=False):
        client_no_args = MetaAPIClient()

    assert client_no_args._phone_id == "meta_phone_id"
    assert "Bearer meta_token" in client_no_args._headers["Authorization"]


# ── Testes de upload de midia e envio de documento/imagem ─────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_upload_media_returns_media_id(client):
    """upload_media faz POST /media e retorna o media_id da resposta."""
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/media"
    ).mock(return_value=httpx.Response(200, json={"id": "4490709327384033"}))

    result = await client.upload_media(b"fake_pdf_bytes", "application/pdf", "test.pdf")
    assert route.called
    assert result == "4490709327384033"


@pytest.mark.asyncio
@respx.mock
async def test_send_document_payload(client):
    """send_document envia payload correto com type=document, id, filename e caption."""
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.doc"}]}))

    await client.send_document(
        to="5531999999999",
        media_id="4490709327384033",
        filename="test.pdf",
        caption="Teste",
    )
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["type"] == "document"
    assert payload["document"]["id"] == "4490709327384033"
    assert payload["document"]["filename"] == "test.pdf"
    assert payload["document"]["caption"] == "Teste"


@pytest.mark.asyncio
@respx.mock
async def test_send_image_payload(client):
    """send_image envia payload correto com type=image, id e caption."""
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.img"}]}))

    await client.send_image(
        to="5531999999999",
        media_id="4490709327384033",
        caption="Preparo",
    )
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["type"] == "image"
    assert payload["image"]["id"] == "4490709327384033"
    assert payload["image"]["caption"] == "Preparo"


def test_media_store_has_all_keys():
    """MEDIA_STATIC deve ter as 5 chaves com path, mime e filename."""
    from app.media_store import MEDIA_STATIC

    expected_keys = [
        "pdf_thaynara",
        "img_preparo_online",
        "img_preparo_presencial",
        "pdf_guia_circunf_mulher",
        "pdf_guia_circunf_homem",
    ]
    for key in expected_keys:
        assert key in MEDIA_STATIC, f"Chave '{key}' ausente em MEDIA_STATIC"
        entry = MEDIA_STATIC[key]
        assert "path" in entry, f"Entrada '{key}' sem 'path'"
        assert "mime" in entry, f"Entrada '{key}' sem 'mime'"
        assert "filename" in entry, f"Entrada '{key}' sem 'filename'"


def test_media_store_paths_exist():
    """Todos os arquivos declarados no catalogo de midia devem existir."""
    from app.media_store import MEDIA_STATIC

    root = Path(__file__).resolve().parents[1]
    missing = [
        (key, entry["path"])
        for key, entry in MEDIA_STATIC.items()
        if not (root / entry["path"]).exists()
    ]
    assert missing == []
