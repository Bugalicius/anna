import pytest
import respx
import httpx
from scripts.evolution_client import EvolutionClient

BASE_URL = "http://localhost:8080"
API_KEY = "test-key"
INSTANCE = "thay"

@pytest.fixture
def client():
    return EvolutionClient(BASE_URL, API_KEY, INSTANCE)

@respx.mock
def test_fetch_chats_returns_sorted_list(client):
    respx.post(f"{BASE_URL}/chat/findChats/{INSTANCE}").mock(
        return_value=httpx.Response(200, json=[
            {"id": "1", "remoteJid": "111@s.whatsapp.net", "updatedAt": "2026-03-20T10:00:00Z"},
            {"id": "2", "remoteJid": "222@s.whatsapp.net", "updatedAt": "2026-03-29T10:00:00Z"},
            {"id": "3", "remoteJid": "333@s.whatsapp.net", "updatedAt": "2026-03-15T10:00:00Z"},
        ])
    )
    chats = client.fetch_chats(limit=2)
    assert len(chats) == 2
    assert chats[0]["id"] == "2"  # most recent first

@respx.mock
def test_fetch_messages_returns_list(client):
    respx.post(f"{BASE_URL}/chat/findMessages/{INSTANCE}").mock(
        return_value=httpx.Response(200, json={
            "messages": {
                "records": [
                    {"key": {"id": "msg1", "fromMe": False}, "message": {"conversation": "Oi"}, "messageTimestamp": 1710000000},
                    {"key": {"id": "msg2", "fromMe": True}, "message": {"conversation": "Olá!"}, "messageTimestamp": 1710000060},
                ]
            }
        })
    )
    messages = client.fetch_messages("111@s.whatsapp.net")
    assert len(messages) == 2
    assert messages[0]["text"] == "Oi"
    assert messages[0]["from_me"] is False

@respx.mock
def test_fetch_chats_filters_groups(client):
    respx.post(f"{BASE_URL}/chat/findChats/{INSTANCE}").mock(
        return_value=httpx.Response(200, json=[
            {"id": "1", "remoteJid": "111@s.whatsapp.net", "updatedAt": "2026-03-29T10:00:00Z"},
            {"id": "2", "remoteJid": "456789@g.us", "updatedAt": "2026-03-29T11:00:00Z"},  # group - exclude
        ])
    )
    chats = client.fetch_chats(limit=10)
    assert len(chats) == 1
    assert chats[0]["id"] == "1"
