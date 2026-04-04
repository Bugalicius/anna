import json
import logging
import os
from pathlib import Path

import google.generativeai as genai
import anthropic

logger = logging.getLogger(__name__)

VALID_SIGNALS = ["pediu_preco", "mencionou_concorrente", "pediu_parcelamento", "disse_vou_pensar"]
CONFIDENCE_THRESHOLD = 0.6

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "knowledge_base" / "system_prompt.md"

FALLBACK_RESPONSE = {
    "message": "Desculpe, tive um probleminha técnico. Pode repetir sua mensagem?",
    "confidence": 0.0,
    "fallback_to_claude": True,
    "suggested_stage": None,
    "behavioral_signals": [],
    "source": "fallback",
}


def parse_gemini_response(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, Exception):
        logger.warning("Gemini retornou JSON inválido, forçando fallback Claude")
        return {**FALLBACK_RESPONSE}

    # Forçar fallback se confiança baixa
    if float(data.get("confidence", 0)) < CONFIDENCE_THRESHOLD:
        data["fallback_to_claude"] = True

    # Filtrar sinais inválidos
    data["behavioral_signals"] = [
        s for s in data.get("behavioral_signals", []) if s in VALID_SIGNALS
    ]
    data.setdefault("source", "gemini")
    return data


class AIEngine:
    def __init__(self, gemini_model=None, claude_client=None):
        if gemini_model is None:
            genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
            self._gemini = genai.GenerativeModel(
                "gemini-2.0-flash",
                generation_config={"response_mime_type": "application/json"},
            )
        else:
            self._gemini = gemini_model

        if claude_client is None:
            self._claude = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY", ""))
        else:
            self._claude = claude_client

        self._system_prompt = (
            SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
            if SYSTEM_PROMPT_PATH.exists()
            else "Você é Ana, assistente de agendamento da nutricionista Thaynara."
        )

    def generate_response(
        self,
        stage: str,
        recent_messages: list[dict],
        contact_data: dict,
        system_prompt: str | None = None,
    ) -> dict:
        sys = system_prompt or self._system_prompt
        conversation_text = "\n".join(
            f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content']}"
            for m in recent_messages[-10:]
        )
        prompt = (
            f"{sys}\n\n"
            f"Stage atual: {stage}\n"
            f"Dados coletados: {contact_data}\n\n"
            f"Conversa recente:\n{conversation_text}\n\n"
            f"Responda em JSON com os campos: message, confidence (0.0-1.0), "
            f"fallback_to_claude (bool), suggested_stage, behavioral_signals "
            f"(lista de: {', '.join(VALID_SIGNALS)})"
        )

        try:
            response = self._gemini.generate_content(prompt)
            result = parse_gemini_response(response.text)
        except Exception as e:
            logger.error(f"Gemini falhou: {e}")
            result = {**FALLBACK_RESPONSE}

        if result.get("fallback_to_claude"):
            return self._call_claude(sys, recent_messages, result)

        return result

    def _call_claude(self, system_prompt: str, messages: list[dict], gemini_result: dict) -> dict:
        try:
            response = self._claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages[-10:]],
            )
            text = response.content[0].text
            return {
                "message": text,
                "confidence": 0.9,
                "fallback_to_claude": False,
                "suggested_stage": gemini_result.get("suggested_stage"),
                "behavioral_signals": gemini_result.get("behavioral_signals", []),
                "source": "claude",
            }
        except Exception as e:
            logger.error(f"Claude também falhou: {e}")
            return {**FALLBACK_RESPONSE, "source": "fallback"}


async def handle_ai(phone: str, phone_hash: str, stage: str, text: str):
    """Chama AI engine, envia resposta e atualiza estado do contato."""
    from app.meta_api import MetaAPIClient
    from app.database import SessionLocal
    from app.models import Contact, Conversation
    from app.remarketing import schedule_behavioral_remarketing
    import os

    engine = AIEngine()

    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        conversation = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id, outcome="em_aberto")
            .order_by(Conversation.opened_at.desc())
            .first()
        )
        recent = [
            {"role": "user" if m.direction == "inbound" else "assistant", "content": m.content}
            for m in conversation.messages[-10:]
        ] if conversation else []
        contact_data = {
            "name": contact.collected_name,
            "patient_type": contact.patient_type,
        }
        contact_id = contact.id

    result = engine.generate_response(stage=stage, recent_messages=recent, contact_data=contact_data)

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("META_ACCESS_TOKEN", ""),
    )
    meta.send_text(to=phone, text=result["message"])

    # Atualizar stage sugerido e disparar remarketing comportamental
    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if result.get("suggested_stage") and result["suggested_stage"] != contact.stage:
            contact.stage = result["suggested_stage"]
        db.commit()

    if result.get("behavioral_signals"):
        with SessionLocal() as db:
            schedule_behavioral_remarketing(db, contact_id, result["behavioral_signals"])
