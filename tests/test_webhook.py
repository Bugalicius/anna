import hashlib
import hmac
import json
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock

APP_SECRET = "test-secret"
VERIFY_TOKEN = "test-verify-token"

# Montar app mínima para testes
from fastapi import FastAPI
app = FastAPI()

from app.webhook import router as webhook_router
app.include_router(webhook_router)

client = TestClient(app)


def make_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_webhook_verification_challenge():
    with patch("app.webhook.VERIFY_TOKEN", VERIFY_TOKEN):
        response = client.get("/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "CHALLENGE_CODE",
        })
    assert response.status_code == 200
    assert response.text == "CHALLENGE_CODE"


def test_invalid_signature_returns_403():
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    response = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=assinatura_invalida",
        },
    )
    assert response.status_code == 403


def test_valid_empty_payload_returns_200():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": []
    }).encode()
    sig = make_signature(body, APP_SECRET)

    with patch("app.webhook.APP_SECRET", APP_SECRET), \
         patch("app.chatwoot_bridge.relay_meta_webhook_to_chatwoot", new_callable=AsyncMock):
        response = client.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert response.status_code == 200


def test_valid_empty_payload_chatwoot_path_returns_200():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": []
    }).encode()
    sig = make_signature(body, APP_SECRET)

    with patch("app.webhook.APP_SECRET", APP_SECRET), \
         patch("app.chatwoot_bridge.relay_meta_webhook_to_chatwoot", new_callable=AsyncMock):
        response = client.post(
            "/webhooks/whatsapp/+553171893255",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert response.status_code == 200


def test_chatwoot_incoming_message_routes_to_debounce():
    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "private": False,
        "id": 123,
        "content": "oi",
        "contact": {"phone_number": "+55 31 99999-0000", "name": "Maria"},
        "conversation": {"id": 77},
    }

    with patch.dict("os.environ", {"CHATWOOT_WEBHOOK_VERIFY_TOKEN": ""}), \
         patch("app.webhook.process_message_debounced", new_callable=AsyncMock) as mock_process, \
         patch("app.chatwoot_bridge.bind_chatwoot_conversation", new_callable=AsyncMock) as mock_bind:
        response = client.post("/webhook/chatwoot", json=payload)

    assert response.status_code == 200
    mock_process.assert_awaited_once()
    mock_bind.assert_awaited_once_with("77", "5531999990000")
    message = mock_process.await_args.args[0]
    assert message["id"] == "chatwoot:123"
    assert message["from"] == "5531999990000"
    assert message["text"]["body"] == "oi"


def test_chatwoot_incoming_attachment_preserves_media_url():
    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "private": False,
        "id": 124,
        "content": None,
        "contact": {"phone_number": "+55 31 99999-0000", "name": "Maria"},
        "attachments": [{
            "file_type": "image",
            "content_type": "image/jpeg",
            "data_url": "https://chat.example.test/rails/active_storage/file.jpg",
        }],
    }

    with patch.dict("os.environ", {"CHATWOOT_WEBHOOK_VERIFY_TOKEN": ""}), \
         patch("app.webhook.process_message_debounced", new_callable=AsyncMock) as mock_process:
        response = client.post("/webhook/chatwoot", json=payload)

    assert response.status_code == 200
    message = mock_process.await_args.args[0]
    assert message["id"] == "chatwoot:124"
    assert message["type"] == "image"
    assert message["image"]["chatwoot_url"] == "https://chat.example.test/rails/active_storage/file.jpg"
    assert message["image"]["mime_type"] == "image/jpeg"


def test_merge_debounced_messages_combina_textos_em_ordem():
    from app.webhook import _merge_debounced_messages

    message, metadata = _merge_debounced_messages([
        {
            "message": {
                "id": "chatwoot:1",
                "from": "5531999990000",
                "type": "text",
                "text": {"body": "oi"},
            },
            "metadata": {"phone_number_id": "123"},
        },
        {
            "message": {
                "id": "chatwoot:2",
                "from": "5531999990000",
                "type": "text",
                "text": {"body": "quero remarcar"},
            },
            "metadata": {"phone_number_id": "123"},
        },
    ])

    assert message["id"].startswith("batch:")
    assert message["from"] == "5531999990000"
    assert message["text"]["body"] == "oi\nquero remarcar"
    assert metadata == {"phone_number_id": "123"}


def test_chatwoot_webhook_outgoing_message_pauses_ana():
    payload = {
        "event": "message_created",
        "message_type": "outgoing",
        "private": False,
        "contact": {"phone_number": "+55 31 7189-3255"},
        "sender": {"type": "user", "phone_number": "+55 31 7189-3255"},
    }

    with patch.dict("os.environ", {"CHATWOOT_WEBHOOK_VERIFY_TOKEN": ""}), \
         patch("app.chatwoot_bridge.set_human_handoff", new_callable=AsyncMock) as mock_set:
        response = client.post("/webhook/chatwoot", json=payload)

    assert response.status_code == 200
    mock_set.assert_awaited_once_with("553171893255", True, reason="chatwoot:message_created")


def test_chatwoot_resolved_uses_conversation_mapping_when_phone_missing():
    payload = {
        "event": "conversation_updated",
        "conversation": {"id": 99, "status": "resolved"},
    }

    with patch.dict("os.environ", {"CHATWOOT_WEBHOOK_VERIFY_TOKEN": ""}), \
         patch("app.chatwoot_bridge.resolve_phone_from_chatwoot_conversation", new_callable=AsyncMock, return_value="553171893255") as mock_resolve, \
         patch("app.chatwoot_bridge.set_human_handoff", new_callable=AsyncMock) as mock_set:
        response = client.post("/webhook/chatwoot", json=payload)

    assert response.status_code == 200
    mock_resolve.assert_awaited_once_with("99")
    mock_set.assert_awaited_once_with("553171893255", False, reason="chatwoot:conversation_updated")


# ── Testes de dedup Redis ─────────────────────────────────────────────────────

MESSAGE_FIXTURE = {
    "id": "wamid.test123",
    "from": "5531999990000",
    "type": "text",
    "text": {"body": "Olá"},
}
METADATA_FIXTURE = {"phone_number_id": "123456"}


@pytest.mark.asyncio
async def test_dedup_redis_blocks_duplicate():
    """Mensagem duplicada nao chama route_message quando _is_duplicate_message retorna True."""
    from app.webhook import process_message

    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=True) as mock_dedup, \
         patch("app.router.route_message", new_callable=AsyncMock) as mock_route:
        await process_message(MESSAGE_FIXTURE, METADATA_FIXTURE)

    mock_dedup.assert_awaited_once_with("wamid.test123")
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_redis_allows_first():
    """Primeira mensagem e processada normalmente quando _is_duplicate_message retorna False."""
    from app.webhook import process_message

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.query.return_value.filter_by.return_value.first.return_value = None
    mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=False), \
         patch("app.database.SessionLocal", return_value=mock_db), \
         patch("app.router.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.escalation._NUMERO_INTERNO", "outro_numero"), \
         patch("app.escalation.processar_resposta_breno", new_callable=AsyncMock):
        await process_message(MESSAGE_FIXTURE, METADATA_FIXTURE)

    mock_route.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_message_ignores_when_human_handoff_active():
    from app.router import route_message

    with patch("app.chatwoot_bridge.is_human_handoff_active", new_callable=AsyncMock, return_value=True), \
         patch("app.router._carregar_contato") as mock_load:
        await route_message(
            phone="5531999990000",
            phone_hash="hash",
            text="ola",
            meta_message_id="wamid.pause",
        )

    mock_load.assert_not_called()


@pytest.mark.asyncio
async def test_dedup_graceful_degradation():
    """Redis indisponivel nao bloqueia o processamento: _is_duplicate_message retorna False (fail open)."""
    import app.webhook as wh

    # Simular Redis com erro: from_url retorna cliente que levanta ConnectionError no set()
    mock_redis = AsyncMock()
    mock_redis.set.side_effect = Exception("Connection refused")
    mock_redis.aclose = AsyncMock()
    mock_redis_cls = MagicMock(return_value=mock_redis)

    with patch("app.webhook.aioredis") as mock_aioredis:
        mock_aioredis.Redis.from_url.return_value = mock_redis
        result = await wh._is_duplicate_message("wamid.redis-down")

    # fail open: deve retornar False mesmo com Redis down
    assert result is False


@pytest.mark.asyncio
async def test_audio_responde_pedindo_texto():
    from app.webhook import MSG_AUDIO_FALHOU, process_message

    message = {"id": "audio-1", "from": "5531999990000", "type": "audio", "audio": {"id": "mid"}}
    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=False), \
         patch("app.rate_limit.is_whatsapp_rate_limited", new_callable=AsyncMock, return_value=False), \
         patch("app.media_handler.processar_midia", new_callable=AsyncMock, return_value={"tipo": "audio", "bytes": b"", "mime_type": "audio/ogg", "transcricao": ""}), \
         patch("app.webhook._send_text_direct", new_callable=AsyncMock) as mock_send, \
         patch("app.router.route_message", new_callable=AsyncMock) as mock_route:
        await process_message(message, {})

    mock_send.assert_awaited_once_with("5531999990000", MSG_AUDIO_FALHOU, "audio-1")
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_responde_pedindo_texto():
    from app.webhook import MSG_LOCATION_NAO_SUPORTADO, process_message

    message = {"id": "loc-1", "from": "5531999990000", "type": "location", "location": {}}
    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=False), \
         patch("app.rate_limit.is_whatsapp_rate_limited", new_callable=AsyncMock, return_value=False), \
         patch("app.webhook._send_text_direct", new_callable=AsyncMock) as mock_send, \
         patch("app.router.route_message", new_callable=AsyncMock) as mock_route:
        await process_message(message, {})

    mock_send.assert_awaited_once_with("5531999990000", MSG_LOCATION_NAO_SUPORTADO, "loc-1")
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_sticker_responde_midia_nao_comprovante():
    from app.webhook import MSG_MIDIA_NAO_COMPROVANTE, process_message

    message = {"id": "sticker-1", "from": "5531999990000", "type": "sticker", "sticker": {}}
    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=False), \
         patch("app.rate_limit.is_whatsapp_rate_limited", new_callable=AsyncMock, return_value=False), \
         patch("app.webhook._send_text_direct", new_callable=AsyncMock) as mock_send, \
         patch("app.router.route_message", new_callable=AsyncMock) as mock_route:
        await process_message(message, {})

    mock_send.assert_awaited_once_with("5531999990000", MSG_MIDIA_NAO_COMPROVANTE, "sticker-1")
    mock_route.assert_not_awaited()
