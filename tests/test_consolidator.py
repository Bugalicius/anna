# tests/test_consolidator.py
import json
import pytest
from pathlib import Path
from scripts.consolidator import Consolidator

SAMPLE_RESULTS = [
    {"intent": "preco", "questions": ["Qual o preço?"], "objections": ["Caro"],
     "outcome": "nao_fechou", "interest_score": 4, "language_notes": "usa 'tô'",
     "behavioral_signals": ["pediu_preco"]},
    {"intent": "agendar", "questions": ["Tem vaga na quinta?"], "objections": [],
     "outcome": "fechou", "interest_score": 5, "language_notes": "formal",
     "behavioral_signals": []},
    {"intent": "preco", "questions": ["Aceita cartão?"], "objections": ["Vou pensar"],
     "outcome": "nao_fechou", "interest_score": 3, "language_notes": "usa 'né'",
     "behavioral_signals": ["pediu_preco", "disse_vou_pensar"]},
]

def test_faq_contains_most_common_questions(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(SAMPLE_RESULTS)

    faq = json.loads((tmp_path / "faq.json").read_text())
    assert len(faq) > 0
    assert all("question" in item and "frequency" in item for item in faq)

def test_objections_extracted(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(SAMPLE_RESULTS)

    objections = json.loads((tmp_path / "objections.json").read_text())
    assert any("Caro" in str(o) or "Vou pensar" in str(o) for o in objections)

def test_remarketing_profiles_cold_leads_only(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(SAMPLE_RESULTS)

    remarketing = json.loads((tmp_path / "remarketing.json").read_text())
    # A estrutura retornada é uma lista de perfis agrupados por behavioral_signals
    assert isinstance(remarketing, list)
    # Cada perfil deve ter os campos esperados
    for profile in remarketing:
        assert "count" in profile
        assert "avg_interest" in profile
        assert "common_objections" in profile
    # Total de leads não-fechados = 2 (os dois com outcome nao_fechou)
    total_leads = sum(p["count"] for p in remarketing)
    assert total_leads == 2

def test_tone_guide_created(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(SAMPLE_RESULTS)

    tone = (tmp_path / "tone_guide.md").read_text()
    assert len(tone) > 50  # Arquivo não vazio

def test_system_prompt_created(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(SAMPLE_RESULTS)

    prompt = (tmp_path / "system_prompt.md").read_text()
    assert "Ana" in prompt  # Nome do agente
    assert len(prompt) > 200

def test_consolidate_handles_empty_results(tmp_path):
    c = Consolidator(output_dir=tmp_path)
    c.consolidate([])  # must not raise

    faq = json.loads((tmp_path / "faq.json").read_text(encoding="utf-8"))
    assert faq == []
    remarketing = json.loads((tmp_path / "remarketing.json").read_text(encoding="utf-8"))
    assert remarketing == []

def test_remarketing_avg_interest_calculated_correctly(tmp_path):
    results = [
        {"intent": "preco", "questions": [], "objections": [],
         "outcome": "nao_fechou", "interest_score": 4, "language_notes": "",
         "behavioral_signals": ["pediu_preco"]},
        {"intent": "preco", "questions": [], "objections": [],
         "outcome": "nao_fechou", "interest_score": 2, "language_notes": "",
         "behavioral_signals": ["pediu_preco"]},
    ]
    c = Consolidator(output_dir=tmp_path)
    c.consolidate(results)

    remarketing = json.loads((tmp_path / "remarketing.json").read_text(encoding="utf-8"))
    assert len(remarketing) == 1
    assert remarketing[0]["count"] == 2
    assert remarketing[0]["avg_interest"] == 3.0
