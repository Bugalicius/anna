"""
Router — integra o ConversationEngine com a Meta API.

Toda a inteligência conversacional está no ConversationEngine (app/conversation/).
O router é responsável apenas por:
  1. Carregar contato do banco e cancelar remarketing
  2. Reconhecer paciente de retorno (pré-popula estado)
  3. Chamar o ConversationEngine
  4. Enviar respostas ao paciente (texto, mídia, escalação)
  5. Atualizar tags/stage do contato
"""
from __future__ import annotations

import hashlib as _hashlib
import logging
from datetime import datetime, UTC

from app.conversation.engine import engine
from app.database import SessionLocal
from app.models import Contact
from app.remarketing import cancel_pending_remarketing
from app.tags import Tag, set_tag

logger = logging.getLogger(__name__)

_MEDIA_CACHE_TTL = 82800  # 23h em segundos

MSG_ENCERRAMENTO_REMARKETING = (
    "Tudo bem! Posso perguntar o que pesou na decisão? "
    "Só pra melhorar nosso atendimento 😊"
)


# ── Inicialização ─────────────────────────────────────────────────────────────


def init_state_manager(redis_url: str) -> None:
    """
    Inicializa Redis para o ConversationEngine.
    Chamado no lifespan do FastAPI (main.py) — interface preservada para
    compatibilidade com o código existente.
    """
    from app.conversation.state import init_state_manager as _init
    _init(redis_url)
    logger.info("ConversationEngine Redis inicializado: %s", redis_url)


# ── Ponto de entrada ──────────────────────────────────────────────────────────


async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str) -> None:
    """
    Processa uma mensagem recebida do WhatsApp.

    Fluxo:
      1. Carrega contato do banco
      2. Pré-popula estado para paciente de retorno
      3. Chama ConversationEngine
      4. Envia respostas (texto, mídia ou escalação)
      5. Atualiza tags/stage do contato
    """
    from app.meta_api import MetaAPIClient
    meta = MetaAPIClient()

    # 1. Carrega contato do banco
    contact = _carregar_contato(phone_hash)
    if not contact:
        logger.error("Contato não encontrado para hash %s", phone_hash[-4:])
        return

    logger.info(
        "route phone=%s stage=%s primeiro_contato=%s",
        phone[-4:], contact["stage"], contact["primeiro_contato"],
    )

    # 2. Pré-popula estado para paciente de retorno
    await _reconhecer_paciente_retorno(phone_hash, phone, contact)

    # 3. Chama o ConversationEngine
    respostas = await engine.handle_message(phone_hash, text, phone=phone)

    # 4. Envia respostas
    await _enviar_respostas(meta, phone, phone_hash, respostas, contact)

    # 5. Atualiza tags/stage do contato
    await _atualizar_contact(phone_hash)


# ── Carregar contato ──────────────────────────────────────────────────────────


def _carregar_contato(phone_hash: str) -> dict | None:
    """Carrega contato do banco e cancela remarketing pendente."""
    try:
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if not contact:
                return None

            stage = contact.stage or "new"

            # Cancela remarketing pendente ao receber mensagem
            if stage in ("cold_lead", "remarketing_sequence", "remarketing"):
                cancel_pending_remarketing(db, contact.id)
                contact.stage = "new"
                stage = "new"

            contact.last_message_at = datetime.now(UTC)
            db.commit()

            return {
                "id": str(contact.id),
                "stage": stage,
                "nome": contact.collected_name or contact.push_name,
                "first_name": contact.first_name,
                "primeiro_contato": stage in ("new", "cold_lead", None),
            }
    except Exception as e:
        logger.error("Erro ao carregar contato %s: %s", phone_hash[-4:], e)
        return None


# ── Reconhecer paciente de retorno ────────────────────────────────────────────


async def _reconhecer_paciente_retorno(
    phone_hash: str, phone: str, contact: dict
) -> None:
    """
    Paciente já cadastrado e com nome no banco: pré-popula o estado com
    nome e status_paciente='retorno' para que o engine não pergunte o nome
    novamente nem trate como novo lead.

    Executa apenas uma vez — se collected_data.nome já estiver preenchido
    (estado carregado do Redis), não sobrescreve.
    """
    from app.conversation.state import load_state, save_state

    nome = contact.get("nome") or contact.get("first_name")
    if not nome or contact.get("primeiro_contato"):
        return

    state = await load_state(phone_hash, phone)
    if state["collected_data"].get("nome"):
        return  # Estado já tem nome — não sobrescreve

    state["collected_data"]["nome"] = nome
    state["collected_data"]["status_paciente"] = "retorno"
    await save_state(phone_hash, state)


# ── Envio de respostas ────────────────────────────────────────────────────────


async def _enviar_respostas(
    meta,
    phone: str,
    phone_hash: str,
    respostas: list,
    contact: dict,
) -> None:
    """
    Itera sobre as respostas do engine e envia ao paciente.

    Tipos de item na lista:
      str  → send_text
      dict com "media_type"   → envio de documento ou imagem
      dict com "_meta_action" → ação especial (ex: escalação)
    """
    for msg in respostas:
        if not msg:
            continue
        try:
            if isinstance(msg, dict):
                if msg.get("_meta_action") == "escalate":
                    await _handle_escalation(meta, phone, phone_hash, contact)
                elif "media_type" in msg:
                    await _enviar_midia(meta, phone, msg)
                elif msg.get("_interactive") == "button":
                    await meta.send_interactive_buttons(phone, msg["body"], msg["buttons"])
                elif msg.get("_interactive") == "list":
                    await meta.send_interactive_list(
                        phone, msg["body"], msg.get("button_label", "Escolher"), msg["rows"]
                    )
                else:
                    logger.warning("Tipo de mensagem desconhecido: %s", msg)
            elif isinstance(msg, str):
                await meta.send_text(phone, msg)
        except Exception as e:
            logger.error("Falha ao enviar para %s: %s", phone[-4:], e)


async def _handle_escalation(
    meta, phone: str, phone_hash: str, contact: dict
) -> None:
    """
    Encaminha dúvida clínica para a nutricionista.
    Usa o histórico do estado do engine para montar o contexto.
    """
    from app.escalation import escalar_para_humano
    from app.conversation.state import load_state

    state = await load_state(phone_hash)
    historico = state.get("history", [])
    resumo = "\n".join(
        f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content'][:120]}"
        for m in historico[-6:]
    )
    await escalar_para_humano(
        meta_client=meta,
        telefone_paciente=phone,
        nome_paciente=state["collected_data"].get("nome") or contact.get("nome"),
        historico_resumido=resumo,
        motivo="Dúvida clínica — requer nutricionista",
    )


# ── Envio de mídia ────────────────────────────────────────────────────────────


async def _enviar_midia(meta, phone: str, media_msg: dict) -> None:
    """Resolve media_key → upload (com cache Redis) → send_document / send_image."""
    from app.media_store import MEDIA_STATIC

    key = media_msg["media_key"]
    info = MEDIA_STATIC.get(key)
    if not info:
        logger.error("media_key '%s' não encontrada em MEDIA_STATIC", key)
        return

    media_id = await _get_or_upload_media(meta, key, info)
    if not media_id:
        logger.error("Falha ao obter media_id para '%s'", key)
        return

    caption = media_msg.get("caption", "")
    if media_msg["media_type"] == "document":
        await meta.send_document(to=phone, media_id=media_id,
                                  filename=info["filename"], caption=caption)
    elif media_msg["media_type"] == "image":
        await meta.send_image(to=phone, media_id=media_id, caption=caption)


async def _get_or_upload_media(meta, media_key: str, info: dict) -> str | None:
    """Retorna media_id do cache Redis ou faz upload e cacheia por 23h."""
    import os
    import redis.asyncio as _aioredis

    cache_key = f"media_id:{_hashlib.sha256(media_key.encode()).hexdigest()[:16]}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    r = None
    try:
        r = _aioredis.Redis.from_url(redis_url, decode_responses=True)
        cached = await r.get(cache_key)
        if cached:
            await r.aclose()
            return cached
    except Exception:
        r = None  # Redis indisponível — faz upload direto

    try:
        file_bytes = open(info["path"], "rb").read()
        media_id = await meta.upload_media(file_bytes, info["mime"], info["filename"])
    except Exception as e:
        logger.error("Falha upload mídia '%s': %s", media_key, e)
        return None

    try:
        if r is None:
            r = _aioredis.Redis.from_url(redis_url, decode_responses=True)
        await r.set(cache_key, media_id, ex=_MEDIA_CACHE_TTL)
        await r.aclose()
    except Exception:
        pass  # Falha no cache — próximo envio fará upload novamente

    return media_id


# ── Atualizar contato ─────────────────────────────────────────────────────────


async def _atualizar_contact(phone_hash: str) -> None:
    """
    Atualiza stage e tags do contato no banco com base no estado atual do engine.

    Mapeamento:
      status=concluido + id_agenda  → Tag.OK, stage=agendado
      status=aguardando_pagamento   → Tag.AGUARDANDO_PAGAMENTO, stage=aguardando_pagamento
      status=coletando + nome       → stage=presenting
      status=coletando              → stage=collecting_info
    """
    from app.conversation.state import load_state, delete_state

    _recusou = False
    try:
        state = await load_state(phone_hash)
        status = state.get("status", "coletando")
        goal = state.get("goal", "desconhecido")
        nome = state["collected_data"].get("nome")
        appt = state.get("appointment", {})

        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if not contact:
                return

            # Persiste nome coletado pelo engine
            if nome and not contact.collected_name:
                contact.collected_name = nome
                if not contact.first_name:
                    contact.first_name = nome.split()[0]

            # Atualiza stage/tags conforme status do engine
            if status == "concluido":
                if goal == "agendar_consulta" and appt.get("id_agenda"):
                    set_tag(db, contact, Tag.OK, force=True)
                    contact.stage = "agendado"
                elif goal == "remarcar":
                    contact.stage = "agendado"
                elif goal == "cancelar":
                    contact.stage = "new"
                elif goal == "recusou_remarketing":
                    set_tag(db, contact, Tag.LEAD_PERDIDO, force=True)
                    cancel_pending_remarketing(db, contact.id)
                    contact.stage = "lead_perdido"
                    _recusou = True
            elif status == "recusou_remarketing":
                set_tag(db, contact, Tag.LEAD_PERDIDO, force=True)
                cancel_pending_remarketing(db, contact.id)
                contact.stage = "lead_perdido"
                _recusou = True
            elif status == "aguardando_pagamento":
                set_tag(db, contact, Tag.AGUARDANDO_PAGAMENTO)
                contact.stage = "aguardando_pagamento"
            elif status == "coletando" and goal == "agendar_consulta":
                contact.stage = "presenting" if nome else "collecting_info"

            db.commit()

    except Exception as e:
        logger.warning("Falha ao atualizar contato %s: %s", phone_hash[-4:], e)

    # Limpa estado Redis quando paciente recusou remarketing
    if _recusou:
        await delete_state(phone_hash)
