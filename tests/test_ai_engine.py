import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.ai_engine import AIEngine, parse_gemini_response, VALID_SIGNALS

VALID_RESPONSE = {
    "message": "Entendo sua preocupação! O investimento cabe bem no orçamento de quem...",
    "confidence": 0.85,
    "fallback_to_claude": False,
    "suggested_stage": "presenting",
    "behavioral_signals": ["pediu_preco"]
}


def test_parse_valid_json_response():
    result = parse_gemini_response(json.dumps(VALID_RESPONSE))
    assert result["message"] == VALID_RESPONSE["message"]
    assert result["confidence"] == 0.85
    assert result["fallback_to_claude"] is False


def test_parse_invalid_json_returns_fallback():
    result = parse_gemini_response("não é JSON válido")
    assert result["fallback_to_claude"] is True
    assert result["confidence"] == 0.0
    assert "message" in result


def test_parse_filters_invalid_signals():
    response = {**VALID_RESPONSE, "behavioral_signals": ["pediu_preco", "sinal_invalido"]}
    result = parse_gemini_response(json.dumps(response))
    assert "sinal_invalido" not in result["behavioral_signals"]
    assert "pediu_preco" in result["behavioral_signals"]


def test_low_confidence_triggers_fallback():
    response = {**VALID_RESPONSE, "confidence": 0.4, "fallback_to_claude": False}
    result = parse_gemini_response(json.dumps(response))
    # confidence < 0.6 deve forçar fallback
    assert result["fallback_to_claude"] is True


def test_engine_uses_claude_when_fallback_requested():
    mock_gemini = MagicMock()
    mock_gemini.generate_content.return_value.text = json.dumps(
        {**VALID_RESPONSE, "fallback_to_claude": True, "confidence": 0.3}
    )
    mock_claude = MagicMock()
    mock_claude.messages.create.return_value.content = [MagicMock(text="Resposta do Claude com empatia")]

    engine = AIEngine(gemini_model=mock_gemini, claude_client=mock_claude)
    result = engine.generate_response(
        stage="presenting",
        recent_messages=[{"role": "user", "content": "Tô com medo de não conseguir"}],
        contact_data={},
        system_prompt="Você é Ana...",
    )
    assert mock_claude.messages.create.called
    assert "Claude" in result["source"] or len(result["message"]) > 0
