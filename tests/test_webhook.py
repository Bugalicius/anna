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

    with patch("app.webhook.APP_SECRET", APP_SECRET):
        response = client.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert response.status_code == 200


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
         patch("app.webhook.route_message", new_callable=AsyncMock) as mock_route:
        await process_message(MESSAGE_FIXTURE, METADATA_FIXTURE)

    mock_dedup.assert_awaited_once_with("wamid.test123")
    mock_route.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_redis_allows_first():
    """Primeira mensagem e processada normalmente quando _is_duplicate_message retorna False."""
    from app.webhook import process_message

    with patch("app.webhook._is_duplicate_message", new_callable=AsyncMock, return_value=False), \
         patch("app.webhook.SessionLocal") as mock_session_cls, \
         patch("app.webhook.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.webhook.processar_resposta_breno", new_callable=AsyncMock), \
         patch("app.webhook._NUMERO_INTERNO", "outro_numero"):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        mock_session_cls.return_value = mock_db
        await process_message(MESSAGE_FIXTURE, METADATA_FIXTURE)

    mock_route.assert_awaited_once()


@pytest.mark.asyncio
async def test_dedup_graceful_degradation():
    """Redis indisponivel nao bloqueia o processamento (fail open — route_message e chamado)."""
    from app.webhook import process_message

    async def mock_dedup_raises(meta_id: str) -> bool:
        raise Exception("Redis down")

    with patch("app.webhook._is_duplicate_message", new=mock_dedup_raises), \
         patch("app.webhook.SessionLocal") as mock_session_cls, \
         patch("app.webhook.route_message", new_callable=AsyncMock) as mock_route, \
         patch("app.webhook.processar_resposta_breno", new_callable=AsyncMock), \
         patch("app.webhook._NUMERO_INTERNO", "outro_numero"):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None
        mock_session_cls.return_value = mock_db
        await process_message(MESSAGE_FIXTURE, METADATA_FIXTURE)

    mock_route.assert_awaited_once()
