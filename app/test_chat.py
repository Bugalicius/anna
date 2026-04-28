"""
Endpoint /test/chat — simula uma conversa com o bot sem WhatsApp.
Usar apenas para testes locais; não expor em produção.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from unittest.mock import patch

from app.router import route_message
from app import router as _router

router = APIRouter()
logger = logging.getLogger(__name__)

# Número fictício fixo para manter estado de conversa entre chamadas
TEST_PHONE = "5500000000001"
TEST_PHONE_HASH = hashlib.sha256(TEST_PHONE.encode()).hexdigest()[:64]


class ChatRequest(BaseModel):
    message: str
    phone: str = TEST_PHONE  # permite simular diferentes usuários


class ChatResponse(BaseModel):
    responses: list[str]


class _MockMeta:
    """MetaAPIClient fake que captura mensagens em vez de enviá-las."""

    def __init__(self, *args, **kwargs):
        pass

    async def send_text(self, to: str, text: str) -> dict:
        return {}

    async def send_interactive_buttons(self, to: str, body: str, buttons: list[dict]) -> dict:
        return {}

    async def send_interactive_list(
        self, to: str, body: str, button_label: str, rows: list[dict]
    ) -> dict:
        return {}

    async def send_contact(self, to: str, nome: str, telefone: str) -> dict:
        return {}

    async def send_template(self, *args, **kwargs) -> dict:
        return {}

    async def upload_media(self, file_bytes: bytes, mime_type: str, filename: str) -> str:
        return f"fake_media_{filename}"

    async def send_document(self, to: str, media_id: str, filename: str, caption: str = "") -> dict:
        return {}

    async def send_image(self, to: str, media_id: str, caption: str = "") -> dict:
        return {}


@router.get("/test/chat", response_class=HTMLResponse)
async def test_chat_ui():
    html = (Path(__file__).parent / "static" / "chat.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


class ResetRequest(BaseModel):
    phone: str = TEST_PHONE


@router.post("/test/reset")
async def test_reset(body: ResetRequest):
    phone_hash = hashlib.sha256(body.phone.encode()).hexdigest()[:64]
    from app.conversation.state import delete_state
    await delete_state(phone_hash)
    from app.database import SessionLocal
    from app.models import Contact
    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if contact:
            contact.stage = "new"
            contact.collected_name = None
            contact.first_name = None
            db.commit()
    return {"reset": True}


@router.post("/test/chat", response_model=ChatResponse)
async def test_chat(body: ChatRequest):
    """
    Simula um turno de conversa com o agente Ana.

    Exemplo:
        curl -X POST http://localhost:8000/test/chat \\
             -H 'Content-Type: application/json' \\
             -d '{"message": "Oi, quero agendar uma consulta"}'
    """
    captured: list[str] = []
    phone_hash = hashlib.sha256(body.phone.encode()).hexdigest()[:64]

    # Garante que o contato existe no banco
    from app.database import SessionLocal
    from app.models import Contact
    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            contact = Contact(phone_hash=phone_hash, phone_e164=body.phone, stage="new")
            db.add(contact)
            db.commit()

    class CapturingMeta(_MockMeta):
        async def send_text(self, to: str, text: str) -> dict:
            captured.append(text)
            return {}

        async def send_interactive_buttons(self, to: str, body: str, buttons: list[dict]) -> dict:
            labels = " | ".join(b.get("title", "") for b in buttons)
            captured.append(f"{body}\n[Botões: {labels}]")
            return {}

        async def send_interactive_list(
            self, to: str, body: str, button_label: str, rows: list[dict]
        ) -> dict:
            labels = " | ".join(r.get("title", "") for r in rows)
            captured.append(f"{body}\n[Lista: {labels}]")
            return {}

        async def send_contact(self, to: str, nome: str, telefone: str) -> dict:
            captured.append(f"[👤 Contato: {nome} {telefone}]")
            return {}

        async def send_document(self, to: str, media_id: str, filename: str, caption: str = "") -> dict:
            captured.append(f"[📄 {filename}]")
            return {}

        async def send_image(self, to: str, media_id: str, caption: str = "") -> dict:
            label = caption or "Imagem"
            captured.append(f"[🖼️ {label}]")
            return {}

    with patch("app.meta_api.MetaAPIClient", CapturingMeta):
        await route_message(
            phone=body.phone,
            phone_hash=phone_hash,
            text=body.message,
            meta_message_id=f"test_{uuid4().hex}",
        )

    return ChatResponse(responses=captured)
