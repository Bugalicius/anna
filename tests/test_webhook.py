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
