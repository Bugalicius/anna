# scripts/analyzer.py
import copy
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
{{conversation}}
""".format(
    intents="|".join(VALID_INTENTS),
    signals="|".join(VALID_SIGNALS),
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
        prompt = ANALYSIS_PROMPT.replace("{conversation}", text)

        try:
            response = self._model.generate_content(prompt)
            data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.warning(f"Gemini retornou JSON inválido para {conversation.get('contact_id', 'unknown')}: {e}")
            return copy.deepcopy(DEFAULT_RESULT)
        except Exception as e:
            logger.error(f"Erro inesperado ao analisar {conversation.get('contact_id', 'unknown')}: {e}")
            return copy.deepcopy(DEFAULT_RESULT)

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
        if not isinstance(data.get("questions"), list):
            data["questions"] = []
        if not isinstance(data.get("objections"), list):
            data["objections"] = []
        if not isinstance(data.get("language_notes"), str):
            data["language_notes"] = ""

        return data
