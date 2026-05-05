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

import asyncio
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _typing_delay(msg) -> float:
    if isinstance(msg, str):
        n = len(msg)
    elif isinstance(msg, dict):
        n = len(msg.get("body", "") or msg.get("caption", "") or "")
    else:
        n = 0
    if n <= 50:
        return 1.0
    elif n <= 150:
        return 2.0
    elif n <= 300:
        return 3.0
    return 4.0


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
    from app.chatwoot_bridge import is_human_handoff_active
    meta = MetaAPIClient()

    if await is_human_handoff_active(phone_hash):
        logger.info("Ana pausada por handoff humano para telefone %s", phone[-4:])
        return

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
    await _enviar_respostas(meta, phone, phone_hash, respostas, contact, meta_message_id)

    # 5. Atualiza tags/stage do contato
    await _atualizar_contact(phone_hash)

    # 6. Agenda remarketing situacional e verifica loop de remarcação
    await _pos_turn_remarketing(phone_hash, contact)


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
                "collected_name": contact.collected_name,  # distingue push_name de nome real
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

    # Só pré-popula quando o contato forneceu o nome em conversa anterior
    # (collected_name). Push_name do WhatsApp não indica paciente de retorno.
    nome = contact.get("collected_name")
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
    meta_message_id: str = "",
) -> None:
    """
    Itera sobre as respostas do engine e envia ao paciente.

    Tipos de item na lista:
      str  → send_text
      dict com "media_type"   → envio de documento ou imagem
      dict com "_meta_action" → ação especial (ex: escalação)
    """
    first = True
    for msg in respostas:
        if not msg:
            continue
        try:
            if first:
                if meta_message_id:
                    try:
                        await meta.mark_as_read(meta_message_id)
                    except Exception:
                        pass
                first = False
            else:
                await asyncio.sleep(1.0)
            try:
                await meta.send_typing_indicator(phone)
            except Exception:
                pass
            await asyncio.sleep(_typing_delay(msg))
            if isinstance(msg, dict):
                if msg.get("_meta_action") == "escalate":
                    await _handle_escalation(
                        meta,
                        phone,
                        phone_hash,
                        contact,
                        motivo=msg.get("motivo") or "duvida_clinica",
                    )
                elif "media_type" in msg:
                    await _enviar_midia(meta, phone, msg)
                    await _log_bot_message_safe(
                        phone,
                        msg.get("caption") or f"[{msg.get('media_type', 'mídia')}]",
                    )
                elif msg.get("_interactive") == "button":
                    await meta.send_interactive_buttons(phone, msg["body"], msg["buttons"])
                    await _log_bot_message_safe(phone, msg["body"])
                elif msg.get("_interactive") == "list":
                    await meta.send_interactive_list(
                        phone, msg["body"], msg.get("button_label", "Escolher"), msg["rows"]
                    )
                    await _log_bot_message_safe(phone, msg["body"])
                else:
                    logger.warning("Tipo de mensagem desconhecido: %s", msg)
            elif isinstance(msg, str):
                await meta.send_text(phone, msg)
                await _log_bot_message_safe(phone, msg)
        except Exception as e:
            logger.error("Falha ao enviar para %s: %s", phone[-4:], e)


async def _log_bot_message_safe(phone: str, text: str) -> None:
    if not text:
        return
    try:
        from app.chatwoot_bridge import log_bot_message
        await log_bot_message(phone, text)
    except Exception as e:
        logger.debug("log_bot_message falhou: %s", e)


async def _handle_escalation(
    meta, phone: str, phone_hash: str, contact: dict, motivo: str = "duvida_clinica"
) -> None:
    """
    Encaminha dúvida clínica para a nutricionista.
    Cria PendingEscalation no banco para habilitar relay bidirecional (D-06/D-07).
    """
    from app.escalation import escalar_duvida
    from app.conversation.state import load_state

    state = await load_state(phone_hash)
    historico = state.get("history", [])
    resumo = "\n".join(
        f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content'][:120]}"
        for m in historico[-6:]
    )
    # Apenas pacientes com status_paciente="retorno" (pré-populado pelo _reconhecer_paciente_retorno)
    # são considerados cadastrados no Dietbox → D-05 (VCard Thaynara).
    # Leads em qualquer estágio do funil vão para D-06/D-07 (relay Breno com PendingEscalation).
    is_paciente_cadastrado = (
        motivo == "duvida_clinica"
        and state.get("collected_data", {}).get("status_paciente") == "retorno"
    )
    await escalar_duvida(
        meta_client=meta,
        telefone_paciente=phone,
        phone_hash=phone_hash,
        nome_paciente=state["collected_data"].get("nome") or contact.get("nome"),
        historico_resumido=resumo,
        motivo=motivo,
        is_paciente_cadastrado=is_paciente_cadastrado,
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
    try:
        if media_msg["media_type"] == "document":
            await meta.send_document(
                to=phone, media_id=media_id, filename=info["filename"], caption=caption,
            )
        elif media_msg["media_type"] == "image":
            await meta.send_image(to=phone, media_id=media_id, caption=caption)
    except Exception as e:
        logger.warning("Falha ao enviar mídia '%s' com cache atual: %s. Tentando novo upload.", key, e)
        media_id = await _get_or_upload_media(meta, key, info, force_refresh=True)
        if not media_id:
            raise
        if media_msg["media_type"] == "document":
            await meta.send_document(
                to=phone, media_id=media_id, filename=info["filename"], caption=caption,
            )
        elif media_msg["media_type"] == "image":
            await meta.send_image(to=phone, media_id=media_id, caption=caption)


async def _get_or_upload_media(
    meta,
    media_key: str,
    info: dict,
    force_refresh: bool = False,
) -> str | None:
    """Retorna media_id do cache Redis ou faz upload e cacheia por 23h."""
    import os
    import redis.asyncio as _aioredis

    cache_key = f"media_id:{_hashlib.sha256(media_key.encode()).hexdigest()[:16]}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    r = None
    try:
        r = _aioredis.Redis.from_url(redis_url, decode_responses=True)
        if not force_refresh:
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
    status = None
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
                    contact.stage = "cancelado"
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

    # Limpa estado Redis depois que o snapshot final ja foi persistido no Contact.
    if _recusou or status == "concluido":
        await delete_state(phone_hash)


# ── Remarketing situacional pós-turno ─────────────────────────────────────────


async def _pos_turn_remarketing(phone_hash: str, contact: dict) -> None:
    """
    Agenda remarketing situacional com base no last_action do estado atual.
    Evita re-agendamento usando flags no estado.
    Verifica loop de remarcação (remarcacoes_count >= 3) e notifica Breno.
    """
    from app.conversation.state import load_state, save_state
    from app.database import SessionLocal
    from app.models import Contact as ContactModel
    from app.remarketing import schedule_situacao_remarketing

    try:
        state = await load_state(phone_hash)
        last_action = state.get("last_action")
        flags = state.get("flags", {})
        flags_updated = False

        with SessionLocal() as db:
            db_contact = db.query(ContactModel).filter_by(phone_hash=phone_hash).first()
            if not db_contact:
                return
            contact_id = db_contact.id

            # Após ver preços → sumiu_apos_ver_preco (24h)
            if last_action == "ask_forma_pagamento" and not flags.get("rmkt_preco_scheduled"):
                nome = (state["collected_data"].get("nome") or "").split()[0]
                schedule_situacao_remarketing(db, contact_id, "sumiu_apos_ver_preco", 0)
                flags["rmkt_preco_scheduled"] = True
                flags_updated = True

            # Após link de cartão ou aguardar pagamento → sumiu_apos_link_pagamento (4h)
            elif last_action in ("await_payment", "gerar_link_cartao") and not flags.get("rmkt_link_scheduled"):
                schedule_situacao_remarketing(db, contact_id, "sumiu_apos_link_pagamento", 0, delay_horas=4)
                flags["rmkt_link_scheduled"] = True
                flags_updated = True

            # Após enviar planos → sumiu_apos_receber_info (48h)
            elif last_action == "send_planos" and not flags.get("rmkt_info_scheduled"):
                schedule_situacao_remarketing(db, contact_id, "sumiu_apos_receber_info", 0)
                flags["rmkt_info_scheduled"] = True
                flags_updated = True

            # Após cancelar com sucesso → cancelou_sem_remarcar (7 dias)
            elif last_action == "cancelar" and state.get("last_tool_success") and not flags.get("rmkt_cancel_scheduled"):
                schedule_situacao_remarketing(db, contact_id, "cancelou_sem_remarcar", 0)
                flags["rmkt_cancel_scheduled"] = True
                flags_updated = True

            # D.3 — Loop de remarcação: notifica Breno após 3ª remarcação
            remarcacoes = state.get("remarcacoes_count", 0)
            if remarcacoes >= 3 and not flags.get("loop_remarcacao_notificado"):
                nome = state["collected_data"].get("nome") or "Paciente"
                await _notificar_breno_loop_remarcacao(nome, remarcacoes)
                flags["loop_remarcacao_notificado"] = True
                flags_updated = True

        if flags_updated:
            state["flags"] = flags
            await save_state(phone_hash, state)

    except Exception as e:
        logger.warning("_pos_turn_remarketing falhou: %s", e)


async def _notificar_breno_loop_remarcacao(nome: str, n: int) -> None:
    """Envia notificação ao número interno quando paciente remarca 3+ vezes."""
    import os
    from app.meta_api import MetaAPIClient
    numero_interno = os.environ.get("NUMERO_INTERNO", "5531992059211")
    try:
        meta = MetaAPIClient()
        ordinal = {3: "3ª", 4: "4ª", 5: "5ª"}.get(n, f"{n}ª")
        msg = f"Ana: {nome} está tentando remarcar pela {ordinal} vez. Pode dar uma atenção especial? 💚"
        await meta.send_text(numero_interno, msg)
    except Exception as e:
        logger.warning("Falha ao notificar Breno sobre loop remarcação: %s", e)
