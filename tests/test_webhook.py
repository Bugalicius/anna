import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

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
