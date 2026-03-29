# tests/test_analyzer.py
import json
import pytest
from unittest.mock import MagicMock, patch
from scripts.analyzer import ConversationAnalyzer, VALID_INTENTS, VALID_SIGNALS

SAMPLE_CONV = {
    "contact_id": "contact_abc123",
    "messages": [
        {"role": "agent", "text": "Olá! Sou a Ana..."},
        {"role": "patient", "text": "Oi, quero saber o preço"},
        {"role": "agent", "text": "O investimento é R$350"},
        {"role": "patient", "text": "Vou pensar e te aviso"},
    ]
}

SAMPLE_RESPONSE = {
    "intent": "preco",
    "questions": ["Qual o preço da consulta?"],
    "objections": ["Precisa pensar antes de decidir"],
    "outcome": "nao_fechou",
    "interest_score": 3,
    "language_notes": "Linguagem informal, usa 'te aviso'",
    "behavioral_signals": ["pediu_preco", "disse_vou_pensar"]
}

def test_analyze_returns_structured_dict():
    mock_model = MagicMock()
    mock_model.generate_content.return_value.text = json.dumps(SAMPLE_RESPONSE)

    analyzer = ConversationAnalyzer(model=mock_model)
    result = analyzer.analyze(SAMPLE_CONV)

    assert result["intent"] in VALID_INTENTS
    assert isinstance(result["questions"], list)
    assert isinstance(result["objections"], list)
    assert result["outcome"] in ["fechou", "nao_fechou", "em_aberto"]
    assert 1 <= result["interest_score"] <= 5
    assert all(s in VALID_SIGNALS for s in result["behavioral_signals"])

def test_analyze_validates_behavioral_signals():
    invalid_response = {**SAMPLE_RESPONSE, "behavioral_signals": ["sinal_invalido"]}
    mock_model = MagicMock()
    mock_model.generate_content.return_value.text = json.dumps(invalid_response)

    analyzer = ConversationAnalyzer(model=mock_model)
    result = analyzer.analyze(SAMPLE_CONV)

    # Sinais inválidos devem ser filtrados
    assert "sinal_invalido" not in result["behavioral_signals"]

def test_analyze_handles_json_error_gracefully():
    mock_model = MagicMock()
    mock_model.generate_content.return_value.text = "resposta inválida que não é JSON"

    analyzer = ConversationAnalyzer(model=mock_model)
    result = analyzer.analyze(SAMPLE_CONV)

    # Deve retornar estrutura default, não levantar exceção
    assert result["intent"] == "tirar_duvida"
    assert result["outcome"] == "em_aberto"
