import logging
from app.database import SessionLocal
from app.models import Contact

logger = logging.getLogger(__name__)

FIXED_FLOW_STAGES = {"new", "awaiting_payment", "scheduling", "confirmed", "archived"}


def decide_route(stage: str) -> str:
    """Retorna 'flow' ou 'ai' baseado no stage do contato."""
    return "flow" if stage in FIXED_FLOW_STAGES else "ai"


async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str):
    """Busca o contato, decide o roteamento e despacha para flow ou AI engine."""
    from app.flows import handle_flow
    from app.ai_engine import handle_ai
    from app.remarketing import cancel_pending_remarketing
    from datetime import datetime, UTC

    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            logger.error(f"Contato não encontrado para hash {phone_hash}")
            return

        stage = contact.stage
        contact_id = contact.id

        # Se estava em cold_lead ou remarketing_sequence, retoma presenting
        if stage in ("cold_lead", "remarketing_sequence"):
            contact.stage = "presenting"
            stage = "presenting"
            db.commit()
            cancel_pending_remarketing(db, contact_id)

        contact.last_message_at = datetime.now(UTC)
        db.commit()

    route = decide_route(stage)

    if route == "flow":
        await handle_flow(phone=phone, phone_hash=phone_hash, stage=stage, text=text)
    else:
        await handle_ai(phone=phone, phone_hash=phone_hash, stage=stage, text=text)
