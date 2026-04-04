import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.flows import get_flow_response, FLOWS


def test_new_stage_returns_welcome_message():
    response = get_flow_response("new", "oi")
    assert response is not None
    assert "Ana" in response or "Thaynara" in response


def test_awaiting_payment_returns_pix_info():
    response = get_flow_response("awaiting_payment", "")
    assert response is not None
    assert "PIX" in response or "pix" in response.lower() or "comprovante" in response.lower()


def test_scheduling_returns_available_times():
    response = get_flow_response("scheduling", "")
    assert response is not None
    # Deve conter horários
    assert any(h in response for h in ["08h", "9h", "10h", "15h", "16h", "17h", "18h", "19h"])


def test_confirmed_returns_confirmation():
    response = get_flow_response("confirmed", "")
    assert response is not None
    assert len(response) > 20


def test_archived_returns_none():
    response = get_flow_response("archived", "")
    assert response is None
