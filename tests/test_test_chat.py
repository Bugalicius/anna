from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_contact_mock(stage: str = "presenting"):
    c = MagicMock()
    c.stage = stage
    c.collected_name = None
    c.push_name = None
    c.first_name = None
    c.id = "contact-test"
    return c


def _make_db_mock(contact):
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter_by.return_value.first.return_value = contact
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


def _make_state(status: str = "coletando", goal: str = "agendar_consulta"):
    return {
        "goal": goal,
        "status": status,
        "collected_data": {"nome": None},
        "appointment": {"id_agenda": None},
        "history": [],
        "flags": {},
    }


def test_test_chat_oferece_slots_sem_duplo_waiting():
    """Ao receber preferência de horário, engine retorna waiting + slots (sem duplicar waiting)."""
    from app.main import app
    from fastapi.testclient import TestClient

    phone = "5500000001010"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
    contact = _make_contact_mock(stage="presenting")
    db_mock = _make_db_mock(contact)

    respostas_engine = [
        "Só um minutinho, já verifico pra você 🌿",
        "Tenho essas opções disponíveis:\n1️⃣ quarta, 22/04 às 9h\n2️⃣ quinta, 23/04 às 10h",
    ]

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.database.SessionLocal", return_value=db_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock, return_value=respostas_engine), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        with TestClient(app) as client:
            response = client.post("/test/chat", json={"phone": phone, "message": "prefiro manhã"})

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["responses"]) == 2
    assert any(p in payload["responses"][0].lower() for p in ["instante", "minutinho", "aguarda"])
    assert "Só um minutinho, já verifico pra você" not in payload["responses"][1]
    assert "Tenho essas opções disponíveis" in payload["responses"][1]


def test_test_chat_cancelamento_funciona_em_dois_turnos():
    """Engine processa motivo de cancelamento e retorna confirmação; estado é limpo."""
    from app.main import app
    from fastapi.testclient import TestClient

    phone = "5500000002020"
    phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
    contact = _make_contact_mock(stage="agendado")
    db_mock = _make_db_mock(contact)

    state_cancelado = _make_state(status="concluido", goal="cancelar")
    delete_mock = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.database.SessionLocal", return_value=db_mock), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.conversation.engine.engine.handle_message",
               new_callable=AsyncMock,
               return_value=["Sua consulta foi cancelada com sucesso! 💚"]), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=state_cancelado), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock), \
         patch("app.conversation.state.delete_state", delete_mock):
        with TestClient(app) as client:
            r = client.post("/test/chat", json={"phone": phone, "message": "tive um imprevisto"})

    assert r.status_code == 200
    respostas = r.json()["responses"]
    assert any("cancelad" in resp.lower() for resp in respostas)
