# Fase 1 — Pipeline de Mineração de Conversas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extrair e analisar as últimas 800 conversas da Evolution API usando Gemini, gerando a knowledge base completa (`faq.json`, `objections.json`, `remarketing.json`, `tone_guide.md`, `system_prompt.md`) que alimentará o agente Ana.

**Architecture:** Script Python standalone que lê conversas da Evolution API local (Docker, porta 8080), pseudonimiza dados antes de enviar ao Gemini 2.0 Flash, salva progresso com checkpoint/resume e consolida resultados em arquivos de knowledge base.

**Tech Stack:** Python 3.12, `httpx` (cliente HTTP async), `google-generativeai` SDK, `pytest` + `respx` (mock HTTP), `python-dotenv`

---

## Mapa de Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `scripts/evolution_client.py` | Fetch de chats e mensagens da Evolution API |
| `scripts/pseudonymizer.py` | Substitui phone/nome por ID interno antes de enviar ao Gemini |
| `scripts/analyzer.py` | Analisa uma conversa com Gemini, retorna JSON estruturado |
| `scripts/consolidator.py` | Agrega todos os resultados e gera os 5 arquivos de knowledge base |
| `scripts/mine_conversations.py` | Orquestrador principal com checkpoint/resume |
| `scripts/.env` | EVOLUTION_API_URL, EVOLUTION_API_KEY, GEMINI_API_KEY |
| `scripts/requirements.txt` | Dependências do script |
| `tests/test_evolution_client.py` | Testes do cliente Evolution |
| `tests/test_pseudonymizer.py` | Testes de pseudonimização |
| `tests/test_analyzer.py` | Testes do analisador Gemini (mock) |
| `tests/test_consolidator.py` | Testes do consolidador |

---

## Task 1: Setup do Projeto

**Files:**
- Create: `scripts/requirements.txt`
- Create: `scripts/.env.example`

- [ ] **Step 1: Criar `requirements.txt`**

```
httpx==0.27.0
google-generativeai==0.8.3
python-dotenv==1.0.1
pytest==8.3.2
respx==0.21.1
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Criar `.env.example`**

```
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_API_KEY=minha-chave-secreta
EVOLUTION_INSTANCE=thay
GEMINI_API_KEY=sua-chave-aqui
```

- [ ] **Step 3: Criar `pytest.ini` na raiz do projeto**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

Isso garante que `from scripts.evolution_client import ...` funciona ao rodar `pytest` da raiz.

- [ ] **Step 4: Instalar dependências**

```bash
cd /c/Users/Breno/Desktop/agente
pip install -r scripts/requirements.txt
```

Esperado: instalação sem erros.

- [ ] **Step 5: Criar `.gitignore` na raiz**

```gitignore
# Credenciais
scripts/.env
.env

# Dados de pacientes — não versionar
knowledge_base/
scripts/mining_progress.json

# Python
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 6: Commit**

```bash
git add scripts/requirements.txt scripts/.env.example pytest.ini .gitignore
git commit -m "chore: setup mining script dependencies + pytest.ini + .gitignore"
```

---

## Task 2: Evolution API Client

**Files:**
- Create: `scripts/evolution_client.py`
- Create: `tests/test_evolution_client.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_evolution_client.py
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
    assert chats[0]["id"] == "2"  # mais recente primeiro

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
            {"id": "2", "remoteJid": "456789@g.us", "updatedAt": "2026-03-29T11:00:00Z"},  # grupo
        ])
    )
    chats = client.fetch_chats(limit=10)
    assert len(chats) == 1
    assert chats[0]["id"] == "1"
```

- [ ] **Step 2: Rodar para verificar falha**

```bash
python -m pytest tests/test_evolution_client.py -v
```
Esperado: `ImportError` ou `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `evolution_client.py`**

```python
# scripts/evolution_client.py
import httpx
from datetime import datetime
from typing import Optional

class EvolutionClient:
    def __init__(self, base_url: str, api_key: str, instance: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"apikey": api_key, "Content-Type": "application/json"}
        self.instance = instance

    def fetch_chats(self, limit: int = 800) -> list[dict]:
        """Retorna os `limit` chats mais recentes, excluindo grupos e broadcasts."""
        with httpx.Client(headers=self.headers, timeout=30) as client:
            resp = client.post(f"{self.base_url}/chat/findChats/{self.instance}", json={})
            resp.raise_for_status()
            chats = resp.json()

        # Filtrar grupos (@g.us) e broadcasts (@broadcast)
        chats = [c for c in chats if "@s.whatsapp.net" in c.get("remoteJid", "")]

        # Ordenar por updatedAt desc
        chats.sort(key=lambda c: c.get("updatedAt", ""), reverse=True)

        return chats[:limit]

    def fetch_messages(self, remote_jid: str) -> list[dict]:
        """Retorna mensagens de uma conversa em ordem cronológica."""
        with httpx.Client(headers=self.headers, timeout=30) as client:
            resp = client.post(
                f"{self.base_url}/chat/findMessages/{self.instance}",
                json={"where": {"key": {"remoteJid": remote_jid}}, "limit": 200}
            )
            resp.raise_for_status()
            data = resp.json()

        records = data.get("messages", {}).get("records", [])
        messages = []
        for r in records:
            text = (
                r.get("message", {}).get("conversation")
                or r.get("message", {}).get("extendedTextMessage", {}).get("text")
                or "[mídia]"
            )
            messages.append({
                "id": r["key"]["id"],
                "from_me": r["key"].get("fromMe", False),
                "text": text,
                "timestamp": r.get("messageTimestamp", 0),
            })

        messages.sort(key=lambda m: m["timestamp"])
        return messages
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest ../tests/test_evolution_client.py -v
```
Esperado: 3 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/evolution_client.py tests/test_evolution_client.py
git commit -m "feat: Evolution API client com filtro de grupos e ordenação"
```

---

## Task 3: Pseudonimizador

**Files:**
- Create: `scripts/pseudonymizer.py`
- Create: `tests/test_pseudonymizer.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_pseudonymizer.py
from scripts.pseudonymizer import Pseudonymizer

def test_same_phone_gets_same_id():
    p = Pseudonymizer()
    id1 = p.get_id("5531999999999@s.whatsapp.net")
    id2 = p.get_id("5531999999999@s.whatsapp.net")
    assert id1 == id2

def test_different_phones_get_different_ids():
    p = Pseudonymizer()
    id1 = p.get_id("5531999999999@s.whatsapp.net")
    id2 = p.get_id("5532888888888@s.whatsapp.net")
    assert id1 != id2

def test_id_does_not_contain_phone():
    p = Pseudonymizer()
    phone = "5531999999999"
    pid = p.get_id(f"{phone}@s.whatsapp.net")
    assert phone not in pid

def test_pseudonymize_conversation_replaces_jid():
    p = Pseudonymizer()
    messages = [
        {"from_me": False, "text": "Oi, sou Maria"},
        {"from_me": True, "text": "Olá Maria!"},
    ]
    result = p.pseudonymize("5531999999999@s.whatsapp.net", messages)
    assert result["contact_id"].startswith("contact_")
    assert "5531999999999" not in result["contact_id"]
    assert len(result["messages"]) == 2
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest ../tests/test_pseudonymizer.py -v
```

- [ ] **Step 3: Implementar `pseudonymizer.py`**

```python
# scripts/pseudonymizer.py
import hashlib

class Pseudonymizer:
    def __init__(self, salt: str = "ana-nutri-2026"):
        self._salt = salt
        self._cache: dict[str, str] = {}

    def get_id(self, jid: str) -> str:
        if jid not in self._cache:
            digest = hashlib.sha256(f"{self._salt}:{jid}".encode()).hexdigest()[:12]
            self._cache[jid] = f"contact_{digest}"
        return self._cache[jid]

    def pseudonymize(self, jid: str, messages: list[dict]) -> dict:
        return {
            "contact_id": self.get_id(jid),
            "messages": [
                {"role": "agent" if m["from_me"] else "patient", "text": m["text"]}
                for m in messages
            ],
        }
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest ../tests/test_pseudonymizer.py -v
```
Esperado: 4 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pseudonymizer.py tests/test_pseudonymizer.py
git commit -m "feat: pseudonimizador de contatos para LGPD"
```

---

## Task 4: Analisador Gemini com Checkpoint

**Files:**
- Create: `scripts/analyzer.py`
- Create: `tests/test_analyzer.py`

- [ ] **Step 1: Escrever testes**

```python
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
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest ../tests/test_analyzer.py -v
```

- [ ] **Step 3: Implementar `analyzer.py`**

```python
# scripts/analyzer.py
import json
import logging

VALID_INTENTS = ["agendar", "tirar_duvida", "preco", "desistir", "remarcar"]
VALID_SIGNALS = ["pediu_preco", "mencionou_concorrente", "pediu_parcelamento", "disse_vou_pensar"]

ANALYSIS_PROMPT = """Analise a conversa de atendimento de uma clínica de nutrição abaixo.
Retorne APENAS JSON válido com esta estrutura exata:

{{
  "intent": "<{intents}>",
  "questions": ["perguntas feitas pela paciente"],
  "objections": ["objeções ou resistências levantadas"],
  "outcome": "<fechou|nao_fechou|em_aberto>",
  "interest_score": <1 a 5>,
  "language_notes": "observações sobre tom, vocabulário, gírias usadas",
  "behavioral_signals": ["lista de: {signals}"]
}}

Conversa:
{conversation}
""".format(
    intents="|".join(VALID_INTENTS),
    signals="|".join(VALID_SIGNALS),
    conversation="{conversation}"
)

DEFAULT_RESULT = {
    "intent": "tirar_duvida",
    "questions": [],
    "objections": [],
    "outcome": "em_aberto",
    "interest_score": 1,
    "language_notes": "",
    "behavioral_signals": [],
}

logger = logging.getLogger(__name__)


class ConversationAnalyzer:
    def __init__(self, model):
        self._model = model

    def analyze(self, conversation: dict) -> dict:
        text = "\n".join(
            f"[{'Agente' if m['role'] == 'agent' else 'Paciente'}]: {m['text']}"
            for m in conversation["messages"]
        )
        prompt = ANALYSIS_PROMPT.format(conversation=text)

        try:
            response = self._model.generate_content(prompt)
            data = json.loads(response.text)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Análise falhou para {conversation['contact_id']}: {e}")
            return {**DEFAULT_RESULT}

        # Validar e sanitizar
        data.setdefault("intent", "tirar_duvida")
        if data["intent"] not in VALID_INTENTS:
            data["intent"] = "tirar_duvida"
        data["behavioral_signals"] = [
            s for s in data.get("behavioral_signals", []) if s in VALID_SIGNALS
        ]
        data["outcome"] = data.get("outcome") if data.get("outcome") in ["fechou", "nao_fechou", "em_aberto"] else "em_aberto"
        score = data.get("interest_score", 1)
        try:
            data["interest_score"] = max(1, min(5, int(round(float(score)))))
        except (ValueError, TypeError):
            data["interest_score"] = 1

        return data
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest ../tests/test_analyzer.py -v
```
Esperado: 3 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/analyzer.py tests/test_analyzer.py
git commit -m "feat: analisador Gemini com validação e fallback para JSON inválido"
```

---

## Task 5: Consolidador de Knowledge Base

**Files:**
- Create: `scripts/consolidator.py`
- Create: `tests/test_consolidator.py`

- [ ] **Step 1: Escrever testes**

```python
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
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest ../tests/test_consolidator.py -v
```

- [ ] **Step 3: Implementar `consolidator.py`**

```python
# scripts/consolidator.py
import json
from collections import Counter
from pathlib import Path


class Consolidator:
    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def consolidate(self, results: list[dict]) -> None:
        self._write_faq(results)
        self._write_objections(results)
        self._write_remarketing(results)
        self._write_tone_guide(results)
        self._write_system_prompt(results)

    def _write_faq(self, results: list[dict]) -> None:
        all_questions = [q for r in results for q in r.get("questions", [])]
        counter = Counter(all_questions)
        faq = [
            {"question": q, "frequency": count, "suggested_answer": ""}
            for q, count in counter.most_common(30)
        ]
        (self.output_dir / "faq.json").write_text(
            json.dumps(faq, ensure_ascii=False, indent=2)
        )

    def _write_objections(self, results: list[dict]) -> None:
        all_objections = [o for r in results for o in r.get("objections", [])]
        counter = Counter(all_objections)
        objections = [
            {"objection": o, "frequency": count, "suggested_response": ""}
            for o, count in counter.most_common(20)
        ]
        (self.output_dir / "objections.json").write_text(
            json.dumps(objections, ensure_ascii=False, indent=2)
        )

    def _write_remarketing(self, results: list[dict]) -> None:
        cold_leads = [
            {
                "outcome": r["outcome"],
                "interest_score": r["interest_score"],
                "intent": r["intent"],
                "objections": r.get("objections", []),
                "behavioral_signals": r.get("behavioral_signals", []),
            }
            for r in results
            if r.get("outcome") in ["nao_fechou", "em_aberto"]
        ]
        # Agrupar por padrão de sinal comportamental
        profiles: dict[str, dict] = {}
        for lead in cold_leads:
            key = "+".join(sorted(lead["behavioral_signals"])) or "sem_sinal"
            if key not in profiles:
                profiles[key] = {"signals": lead["behavioral_signals"], "count": 0, "avg_interest": 0, "common_objections": []}
            profiles[key]["count"] += 1
            profiles[key]["avg_interest"] += lead["interest_score"]
            profiles[key]["common_objections"].extend(lead["objections"])

        for profile in profiles.values():
            if profile["count"] > 0:
                profile["avg_interest"] = round(profile["avg_interest"] / profile["count"], 1)
            counter = Counter(profile["common_objections"])
            profile["common_objections"] = [o for o, _ in counter.most_common(5)]

        (self.output_dir / "remarketing.json").write_text(
            json.dumps(list(profiles.values()), ensure_ascii=False, indent=2)
        )

    def _write_tone_guide(self, results: list[dict]) -> None:
        notes = [r.get("language_notes", "") for r in results if r.get("language_notes")]
        conversion_notes = [
            r.get("language_notes", "") for r in results
            if r.get("outcome") == "fechou" and r.get("language_notes")
        ]
        content = "# Guia de Tom e Linguagem — Agente Ana\n\n"
        content += "## Vocabulário e Expressões das Pacientes\n\n"
        for note in set(notes[:50]):
            if note.strip():
                content += f"- {note}\n"
        content += "\n## Padrões em Conversas que Converteram\n\n"
        for note in set(conversion_notes[:20]):
            if note.strip():
                content += f"- {note}\n"
        (self.output_dir / "tone_guide.md").write_text(content)

    def _write_system_prompt(self, results: list[dict]) -> None:
        total = len(results)
        converted = sum(1 for r in results if r.get("outcome") == "fechou")
        rate = round(converted / total * 100, 1) if total else 0

        top_questions = Counter(
            q for r in results for q in r.get("questions", [])
        ).most_common(5)
        top_objections = Counter(
            o for r in results for o in r.get("objections", [])
        ).most_common(5)

        prompt = f"""# System Prompt — Agente Ana (Nutricionista Thaynara Teixeira)

## Identidade
Você é Ana, assistente virtual responsável pelos agendamentos da nutricionista Thaynara Teixeira.
Seu objetivo é agendar consultas com empatia, clareza e naturalidade em português brasileiro.

## Dados do Histórico Analisado
- Total de conversas analisadas: {total}
- Taxa de conversão observada: {rate}%

## Perguntas Mais Frequentes das Pacientes
{chr(10).join(f'- {q} (aparece {c}x)' for q, c in top_questions)}

## Principais Objeções Enfrentadas
{chr(10).join(f'- {o} (aparece {c}x)' for o, c in top_objections)}

## Regras de Comportamento
1. Sempre responder em português brasileiro informal e acolhedor
2. Nunca prometer resultados clínicos específicos
3. Encaminhar dúvidas médicas para a Thaynara diretamente
4. Ao detectar resistência, reconhecer a objeção antes de apresentar solução
5. Ao oferecer horários, apresentar no máximo 3 opções
6. Confirmar nome da paciente antes de avançar para pagamento

## Tom
Empático, profissional mas descontraído. Use emojis com moderação (💚 para acolhimento).
"""
        (self.output_dir / "system_prompt.md").write_text(prompt)
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest ../tests/test_consolidator.py -v
```
Esperado: 5 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/consolidator.py tests/test_consolidator.py
git commit -m "feat: consolidador de knowledge base (faq, objections, remarketing, tone, prompt)"
```

---

## Task 6: Orquestrador Principal com Checkpoint/Resume

**Files:**
- Create: `scripts/mine_conversations.py`
- Create: `tests/test_mine_conversations.py`

- [ ] **Step 1: Escrever teste de checkpoint**

```python
# tests/test_mine_conversations.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from scripts.mine_conversations import CheckpointManager

def test_checkpoint_saves_and_loads(tmp_path):
    cp = CheckpointManager(tmp_path / "progress.json")
    cp.mark_done("chat_001", {"intent": "preco"})
    cp.mark_done("chat_002", {"intent": "agendar"})

    # Simula nova instância (novo run)
    cp2 = CheckpointManager(tmp_path / "progress.json")
    assert cp2.is_done("chat_001")
    assert cp2.is_done("chat_002")
    assert not cp2.is_done("chat_003")

def test_checkpoint_returns_accumulated_results(tmp_path):
    cp = CheckpointManager(tmp_path / "progress.json")
    cp.mark_done("chat_001", {"intent": "preco", "outcome": "nao_fechou"})
    cp.mark_done("chat_002", {"intent": "agendar", "outcome": "fechou"})

    cp2 = CheckpointManager(tmp_path / "progress.json")
    results = cp2.get_results()
    assert len(results) == 2
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_mine_conversations.py -v
```

- [ ] **Step 3: Implementar `mine_conversations.py`**

```python
# scripts/mine_conversations.py
import json
import logging
import os
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from scripts.evolution_client import EvolutionClient
from scripts.pseudonymizer import Pseudonymizer
from scripts.analyzer import ConversationAnalyzer
from scripts.consolidator import Consolidator

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        if self._path.exists():
            self._data = json.loads(self._path.read_text())

    def is_done(self, chat_id: str) -> bool:
        return chat_id in self._data

    def mark_done(self, chat_id: str, result: dict) -> None:
        self._data[chat_id] = result
        self._path.write_text(json.dumps(self._data, ensure_ascii=False))

    def get_results(self) -> list[dict]:
        return list(self._data.values())


def main():
    base_dir = Path(__file__).parent.parent
    checkpoint_path = Path(__file__).parent / "mining_progress.json"
    output_dir = base_dir / "knowledge_base"

    evolution = EvolutionClient(
        base_url=os.environ["EVOLUTION_API_URL"],
        api_key=os.environ["EVOLUTION_API_KEY"],
        instance=os.environ.get("EVOLUTION_INSTANCE", "thay"),
    )
    pseudonymizer = Pseudonymizer()

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
    )
    analyzer = ConversationAnalyzer(model=model)

    checkpoint = CheckpointManager(checkpoint_path)

    logger.info("Buscando chats da Evolution API...")
    chats = evolution.fetch_chats(limit=800)
    logger.info(f"Total de chats para processar: {len(chats)}")

    already_done = sum(1 for c in chats if checkpoint.is_done(c["id"]))
    logger.info(f"Já processados (checkpoint): {already_done}")

    for i, chat in enumerate(chats):
        if checkpoint.is_done(chat["id"]):
            continue

        logger.info(f"[{i+1}/{len(chats)}] Processando {chat['id']}...")

        try:
            messages = evolution.fetch_messages(chat["remoteJid"])
            if len(messages) < 3:
                checkpoint.mark_done(chat["id"], {"intent": "tirar_duvida", "outcome": "em_aberto",
                    "questions": [], "objections": [], "interest_score": 1,
                    "language_notes": "", "behavioral_signals": [], "_skipped": True})
                continue

            pseudonymized = pseudonymizer.pseudonymize(chat["remoteJid"], messages)
            result = analyzer.analyze(pseudonymized)
            checkpoint.mark_done(chat["id"], result)

            # Rate limit gentil para a API do Gemini
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Erro no chat {chat['id']}: {e}")
            time.sleep(2)  # Espera maior em caso de erro

    logger.info("Consolidando knowledge base...")
    results = [r for r in checkpoint.get_results() if not r.get("_skipped")]
    consolidator = Consolidator(output_dir=output_dir)
    consolidator.consolidate(results)

    logger.info(f"Knowledge base gerada em: {output_dir}")
    logger.info(f"Total de conversas analisadas: {len(results)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_mine_conversations.py -v
```
Esperado: 2 testes PASS.

- [ ] **Step 5: Rodar todos os testes**

```bash
python -m pytest ../tests/ -v
```
Esperado: todos PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/mine_conversations.py tests/test_mine_conversations.py
git commit -m "feat: orquestrador principal com checkpoint/resume"
```

---

## Task 7: Execução Real e Geração da Knowledge Base

> Esta task é executada manualmente. Requer Evolution API rodando no Docker e chave Gemini configurada.

- [ ] **Step 1: Configurar `.env`**

```bash
cp scripts/.env.example scripts/.env
# Editar scripts/.env com:
# EVOLUTION_API_KEY=minha-chave-secreta
# GEMINI_API_KEY=<sua chave do Google AI Studio>
```

- [ ] **Step 2: Verificar Evolution API acessível**

```bash
curl -s http://localhost:8080/instance/fetchInstances \
  -H "apikey: minha-chave-secreta" | python3 -m json.tool | head -20
```
Esperado: resposta JSON com instância "thay" e `connectionStatus: "open"`.

- [ ] **Step 3: Executar mineração**

```bash
cd /c/Users/Breno/Desktop/agente
python -m scripts.mine_conversations
```

Esperado: logs de progresso, arquivo `scripts/mining_progress.json` crescendo. Em caso de interrupção, rodar novamente retoma do checkpoint.

- [ ] **Step 4: Verificar output**

```bash
ls -la knowledge_base/
cat knowledge_base/faq.json | python3 -m json.tool | head -40
head -50 knowledge_base/system_prompt.md
```

- [ ] **Step 5: Commit da knowledge base gerada**

```bash
git add knowledge_base/
git commit -m "data: knowledge base gerada da análise de 800 conversas"
```

---

*Plano gerado em 2026-03-29. Referência: spec `docs/superpowers/specs/2026-03-29-agente-atendimento-nutricionista-design.md` Seções 2 (Fase 1) e 4 (Schema).*
