"""
Router — integra o Orquestrador com os Agentes 1 e 2.

Estado dos agentes é persistido no Redis via RedisStateManager (D-12, D-15).
O Orquestrador classifica a intenção em TODA mensagem, mesmo com agente ativo (D-01).
Interrupcoes (remarcar, cancelar, duvida_clinica) trocam de agente (D-02).
Intencoes inline (tirar_duvida, fora_de_contexto) respondem sem sair do fluxo (D-03).
Paciente de retorno é cumprimentado pelo nome (D-14).
Numero interno NUNCA exposto ao paciente (INTL-04).
"""
from __future__ import annotations

import hashlib as _hashlib
import logging
from datetime import datetime, UTC

from app.agents.atendimento import AgenteAtendimento
from app.agents.orchestrator import rotear
from app.agents.retencao import AgenteRetencao
from app.database import SessionLocal
from app.models import Contact
from app.remarketing import cancel_pending_remarketing
from app.tags import Tag, set_tag

logger = logging.getLogger(__name__)

# ── Estado de conversa via Redis (substituiu _AGENT_STATE dict in-memory) ─────
# Inicializado no lifespan do app via init_state_manager()
_state_mgr = None


def init_state_manager(redis_url: str) -> None:
    """Inicializa o RedisStateManager global. Chamado no lifespan do FastAPI."""
    global _state_mgr
    from app.state_manager import RedisStateManager
    _state_mgr = RedisStateManager(redis_url)
    logger.info("RedisStateManager inicializado: %s", redis_url)


# ── Intenções que interrompem o fluxo atual e trocam de agente (D-02) ─────────
_INTENCOES_INTERRUPT: frozenset[str] = frozenset({"remarcar", "cancelar", "duvida_clinica"})

# ── Intenções respondidas inline sem sair do fluxo (D-03) ────────────────────
_INTENCOES_INLINE: frozenset[str] = frozenset({"tirar_duvida", "fora_de_contexto"})

# ── Mensagem padrão para respostas inline ─────────────────────────────────────
_MSG_INLINE_PADRAO = (
    "Posso te ajudar com agendamentos e informações sobre as consultas 💚"
)

# ── Mensagem de encerramento ao detectar recusa de remarketing (D-09) ─────────
MSG_ENCERRAMENTO_REMARKETING = (
    "Tudo bem! Posso perguntar o que pesou na decisão? "
    "Só pra melhorar nosso atendimento 😊"
)


async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str):
    """
    Ponto de entrada do roteamento.

    1. Carrega contato do banco para obter stage, nome e modalidade
    2. Carrega estado do agente ativo no Redis
    3. SEMPRE classifica a intenção via Orquestrador (D-01)
    4. Detecta interrupções (D-02) e respostas inline (D-03)
    5. Despacha para o agente correto
    6. Salva estado atualizado no Redis; deleta em finalização
    """
    from app.escalation import escalar_para_humano
    from app.meta_api import MetaAPIClient

    meta = MetaAPIClient()

    # ── 1. Carrega contato do banco ───────────────────────────────────────────
    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            logger.error("Contato não encontrado para hash %s", phone_hash[:12])
            return

        stage = contact.stage or "new"
        nome = contact.collected_name or contact.push_name
        primeiro_contato = stage in ("new", "cold_lead", None)
        first_name = contact.first_name

        # Cancela remarketing pendente ao receber mensagem
        if stage in ("cold_lead", "remarketing_sequence", "remarketing"):
            cancel_pending_remarketing(db, contact.id)
            contact.stage = "new"
            stage = "new"

        contact.last_message_at = datetime.now(UTC)
        db.commit()

    # ── 2. Carrega estado do Redis (D-15: falha retorna None sem crash) ───────
    agente_ativo = await _state_mgr.load(phone_hash) if _state_mgr else None

    # ── 3. Determina tipo do agente ativo para contexto do orquestrador ───────
    tipo_agente: str | None = None
    if agente_ativo is not None:
        _tnome = _tipo_agente(agente_ativo)
        if _tnome == "AgenteAtendimento":
            tipo_agente = "atendimento"
        elif _tnome == "AgenteRetencao":
            tipo_agente = "retencao"

    # ── 4. SEMPRE classifica intenção (D-01) ──────────────────────────────────
    # Fast-path: etapas de intake sem paciente de retorno identificado não precisam
    # de LLM — o FSM do agente trata tudo deterministicamente.
    # Exceção: mensagem contém hint de interrupt (remarcar, cancelar) → chama LLM.
    _INTERRUPT_HINTS = frozenset({"remarcar", "remarc", "cancelar", "cancel", "desmarcar"})
    _has_interrupt_hint = any(w in text.lower() for w in _INTERRUPT_HINTS)
    _agent_type_str = _tipo_agente(agente_ativo) if agente_ativo else None
    _etapa_atual = getattr(agente_ativo, "etapa", None) if agente_ativo else None
    _skip_llm = not _has_interrupt_hint and agente_ativo is not None and (
        # Atendimento: etapas de intake sem paciente de retorno
        (
            _agent_type_str == "AgenteAtendimento"
            and _etapa_atual in ("boas_vindas", "qualificacao")
            and getattr(agente_ativo, "status_paciente", None) != "retorno"
        )
        or
        # Retencao: etapas de coleta de nome — não há interrupt possível
        (
            _agent_type_str == "AgenteRetencao"
            and _etapa_atual in ("coletando_nome", "coletando_nome_cancel")
        )
    )
    if _skip_llm:
        rota = {"agente": "atendimento", "intencao": "novo_lead", "confianca": 1.0, "resposta_padrao": None}
    else:
        rota = rotear(
            mensagem=text,
            stage_atual=stage,
            primeiro_contato=primeiro_contato,
            agente_ativo=tipo_agente,
        )
    intencao = rota["intencao"]
    agente_destino = rota["agente"]

    if _deve_manter_atendimento_sem_estado(agente_ativo, stage, text, intencao):
        intencao = "agendar"
        agente_destino = "atendimento"

    if _deve_ignorar_interrupt_falso_positivo(agente_ativo, text, intencao):
        intencao = "agendar"
        agente_destino = "atendimento"

    logger.info(
        "route phone=%s stage=%s intencao=%s agente_destino=%s agente_ativo=%s",
        phone[-4:], stage, intencao, agente_destino, tipo_agente,
    )

    # ── 5. Reconhecimento por nome — sessão nova, paciente de retorno (D-14) ──
    nome_saudacao = first_name or nome
    if agente_ativo is None and nome_saudacao and not primeiro_contato:
        saudacao = f"Eiii {nome_saudacao}, lembro que já nos falamos! Como posso te ajudar? 💚"
        await _enviar(meta, phone, [saudacao])

    # ── 6. Com agente ativo: interrupt detection + inline response ────────────
    if agente_ativo is not None:

        # D-02: intencoes que interrompem o fluxo — troca de agente
        if intencao in _INTENCOES_INTERRUPT:
            # Preserva nome no Contact antes de destruir o agente atual
            agente_nome = getattr(agente_ativo, "nome", None)
            if agente_nome:
                _salvar_nome_contact(phone_hash, agente_nome)

            # Deleta estado antigo — cai no bloco de roteamento normal abaixo
            if _state_mgr:
                await _state_mgr.delete(phone_hash)
            agente_ativo = None
            tipo_agente = None
            # Continua para o bloco de roteamento abaixo

        # D-03: intencoes inline — responde sem sair do fluxo
        # Exceção: etapas de intake (boas_vindas, qualificacao) não usam inline —
        # mensagens ambíguas como "já sou paciente" devem ser tratadas pelo FSM do agente
        elif (
            intencao in _INTENCOES_INLINE
            and not _is_intake_etapa(agente_ativo)
            and not _deve_deixar_agente_responder_duvida(agente_ativo, intencao)
        ):
            resposta_inline = (
                rota.get("resposta_padrao") or _MSG_INLINE_PADRAO
            )
            await _enviar(meta, phone, [resposta_inline])
            # Salva estado (agente não mudou)
            if _state_mgr:
                await _state_mgr.save(phone_hash, agente_ativo)
            return

        # Intencao compatível com agente atual — continua no fluxo
        else:
            _tnome = _tipo_agente(agente_ativo)
            if _tnome == "AgenteAtendimento":
                respostas = agente_ativo.processar(text)
                _atualizar_contact_por_estado(phone_hash, agente_ativo)
            elif _tnome == "AgenteRetencao":
                if agente_ativo.etapa in ("aguardando_motivo", "coletando_nome_cancel"):
                    respostas = agente_ativo.processar_cancelamento(text)
                else:
                    respostas = agente_ativo.processar_remarcacao(text)
            else:
                respostas = []

            await _enviar(meta, phone, respostas)

            # Salva ou deleta conforme etapa
            if _state_mgr:
                if _fluxo_finalizado(agente_ativo):
                    await _state_mgr.delete(phone_hash)
                else:
                    await _state_mgr.save(phone_hash, agente_ativo)
            return

    # ── 7. Roteamento para agente (sem agente ativo ou após interrupt) ─────────

    # ── Recusa de remarketing — lead perdido (D-09, D-10) ────────────────────
    if agente_destino == "remarketing_recusa":
        await _enviar(meta, phone, [MSG_ENCERRAMENTO_REMARKETING])

        # Cancela fila pendente e move para lead_perdido (D-10)
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                cancel_pending_remarketing(db, contact.id)
                set_tag(db, contact, Tag.LEAD_PERDIDO, force=True)
                db.commit()

        # Deleta estado Redis se existir (D-10)
        if _state_mgr:
            await _state_mgr.delete(phone_hash)
        return

    # Resposta padrão (fora de contexto sem agente ativo)
    if agente_destino == "padrao":
        await _enviar(meta, phone, [rota["resposta_padrao"]])
        return

    # Escalação para humano (dúvida clínica)
    if agente_destino == "escalacao":
        historico_txt = _resumir_historico(agente_ativo)
        await escalar_para_humano(
            meta_client=meta,
            telefone_paciente=phone,
            nome_paciente=nome,
            historico_resumido=historico_txt,
            motivo="Dúvida clínica — requer nutricionista",
        )
        return

    # ── Agente 1 — Atendimento ────────────────────────────────────────────────
    if agente_destino == "atendimento":
        agente = AgenteAtendimento(telefone=phone, phone_hash=phone_hash)
        respostas = agente.processar(text)
        _atualizar_contact_por_estado(phone_hash, agente)

        await _enviar(meta, phone, respostas)

        # Salva ou deleta no Redis
        if _state_mgr:
            if _fluxo_finalizado(agente):
                await _state_mgr.delete(phone_hash)
            else:
                await _state_mgr.save(phone_hash, agente)
        return

    # ── Agente 2 — Retenção ───────────────────────────────────────────────────
    if agente_destino == "retencao":
        modalidade = _inferir_modalidade_de_contato(phone_hash)
        agente = AgenteRetencao(telefone=phone, nome=nome, modalidade=modalidade)

        if intencao == "cancelar":
            respostas = agente.processar_cancelamento(text)
        else:
            respostas = agente.processar_remarcacao(text)

        await _enviar(meta, phone, respostas)

        # Salva ou deleta no Redis
        if _state_mgr:
            if _fluxo_finalizado(agente):
                await _state_mgr.delete(phone_hash)
            else:
                await _state_mgr.save(phone_hash, agente)
        return


# ── helpers ───────────────────────────────────────────────────────────────────

_MEDIA_CACHE_TTL = 82800  # 23h em segundos


async def _enviar(meta, phone: str, mensagens: list):
    """Envia lista de mensagens via Meta API. Detecta dicts de midia e envia como documento/imagem."""
    for msg in mensagens:
        if not msg:
            continue
        try:
            if isinstance(msg, dict) and "media_type" in msg:
                await _enviar_midia(meta, phone, msg)
            else:
                await meta.send_text(phone, msg)
        except Exception as e:
            logger.error("Falha ao enviar mensagem para %s: %s", phone[-4:], e)


async def _enviar_midia(meta, phone: str, media_msg: dict):
    """Resolve media_key -> upload (com cache Redis) -> send_document/send_image."""
    from app.media_store import MEDIA_STATIC

    key = media_msg["media_key"]
    info = MEDIA_STATIC.get(key)
    if not info:
        logger.error("media_key '%s' nao encontrada em MEDIA_STATIC", key)
        return

    media_id = await _get_or_upload_media(meta, key, info)
    if not media_id:
        logger.error("Falha ao obter media_id para '%s'", key)
        return

    caption = media_msg.get("caption", "")
    if media_msg["media_type"] == "document":
        await meta.send_document(to=phone, media_id=media_id, filename=info["filename"], caption=caption)
    elif media_msg["media_type"] == "image":
        await meta.send_image(to=phone, media_id=media_id, caption=caption)


async def _get_or_upload_media(meta, media_key: str, info: dict) -> str | None:
    """Retorna media_id do cache Redis ou faz upload e cacheia."""
    import os
    import redis.asyncio as _aioredis

    cache_key = f"media_id:{_hashlib.sha256(media_key.encode()).hexdigest()[:16]}"
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Tentar cache Redis
    r = None
    try:
        r = _aioredis.Redis.from_url(redis_url, decode_responses=True)
        cached = await r.get(cache_key)
        if cached:
            await r.aclose()
            return cached
    except Exception:
        r = None  # Redis indisponivel — prosseguir com upload direto

    # Upload para Meta
    try:
        file_bytes = open(info["path"], "rb").read()
        media_id = await meta.upload_media(file_bytes, info["mime"], info["filename"])
    except Exception as e:
        logger.error("Falha upload midia '%s': %s", media_key, e)
        return None

    # Cachear no Redis (falha nao e critica)
    try:
        if r is None:
            r = _aioredis.Redis.from_url(redis_url, decode_responses=True)
        await r.set(cache_key, media_id, ex=_MEDIA_CACHE_TTL)
        await r.aclose()
    except Exception:
        pass  # Cache falhou — proximo envio fara upload de novo

    return media_id


def _tipo_agente(agent) -> str | None:
    """
    Retorna o tipo do agente como string.

    Usa type.__name__ primeiro; cai para atributo _tipo como fallback
    (útil em testes onde o agente é um mock).
    """
    nome = type(agent).__name__
    if nome in ("AgenteAtendimento", "AgenteRetencao"):
        return nome
    # Fallback: atributo _tipo definido em to_dict() — compatível com mocks
    return getattr(agent, "_tipo", None)


def _fluxo_finalizado(agent) -> bool:
    """Retorna True se o agente chegou à etapa terminal do seu fluxo."""
    _tnome = _tipo_agente(agent)
    if _tnome == "AgenteAtendimento":
        return agent.etapa == "finalizacao"
    if _tnome == "AgenteRetencao":
        return agent.etapa == "concluido"
    return False


def _resumir_historico(agent) -> str:
    """Extrai as últimas 6 mensagens do histórico para contexto de escalação."""
    if not agent or not hasattr(agent, "historico"):
        return "(sem histórico)"
    ultimas = agent.historico[-6:]
    return "\n".join(
        f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content'][:120]}"
        for m in ultimas
    )


def _inferir_modalidade_de_contato(phone_hash: str) -> str:
    """
    Tenta recuperar modalidade do Contact no banco.
    Retorna 'presencial' como padrão.
    """
    try:
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact and contact.patient_type:
                return contact.patient_type
    except Exception as e:
        logger.warning("Falha ao inferir modalidade para %s: %s", phone_hash[-4:], e)
    return "presencial"


def _is_intake_etapa(agent) -> bool:
    """Retorna True se o agente está numa etapa de coleta de dados (intake).

    Nessas etapas, respostas inline (fora_de_contexto, tirar_duvida) não devem
    interceptar a mensagem — o FSM do agente precisa processar para capturar
    contexto como 'já sou paciente' ou o nome do paciente.
    """
    tipo = _tipo_agente(agent)
    etapa = getattr(agent, "etapa", None)
    if tipo == "AgenteAtendimento":
        return etapa in ("boas_vindas", "qualificacao", "apresentacao_planos", "escolha_plano")
    if tipo == "AgenteRetencao":
        return etapa in ("coletando_nome", "coletando_nome_cancel")
    return False


def _deve_deixar_agente_responder_duvida(agent, intencao: str) -> bool:
    """
    Permite que o próprio agente trate mensagens em etapas sensíveis.

    Cobre dois casos:
    - tirar_duvida: perguntas contextuais (parcelamento, planos, pagamento)
    - fora_de_contexto: respostas curtas/numéricas ("1", "pix", "sim") que o
      LLM classifica erroneamente mas que são input válido para o FSM do agente
    """
    if intencao not in ("tirar_duvida", "fora_de_contexto"):
        return False

    tipo = _tipo_agente(agent)
    etapa = getattr(agent, "etapa", None)
    if tipo == "AgenteAtendimento":
        return etapa in (
            "apresentacao_planos",
            "escolha_plano",
            "agendamento",
            "forma_pagamento",
            "pagamento",
            "cadastro_dietbox",
            "confirmacao",
            "finalizacao",
        )
    if tipo == "AgenteRetencao":
        return etapa in ("coletando_preferencia", "oferecendo_slots", "aguardando_confirmacao_dietbox")
    return False


def _deve_ignorar_interrupt_falso_positivo(agent, text: str, intencao: str) -> bool:
    """Evita trocar para retenção quando o paciente ainda está escolhendo um novo agendamento."""
    if intencao not in {"remarcar", "cancelar"}:
        return False
    if _tipo_agente(agent) != "AgenteAtendimento":
        return False
    if getattr(agent, "pagamento_confirmado", False):
        return False

    etapa = getattr(agent, "etapa", None)
    if etapa not in {"preferencia_horario", "agendamento", "forma_pagamento", "pagamento"}:
        return False

    texto = text.lower()
    marcadores_consulta_existente = (
        "minha consulta",
        "consulta marcada",
        "consulta agendada",
        "já tenho consulta",
        "ja tenho consulta",
        "já marquei",
        "ja marquei",
        "remarcar minha consulta",
        "cancelar minha consulta",
    )
    return not any(marcador in texto for marcador in marcadores_consulta_existente)


def _deve_manter_atendimento_sem_estado(agent, stage: str | None, text: str, intencao: str) -> bool:
    """Mantém o fluxo de atendimento mesmo sem agente ativo se o contato ainda está no pipeline comercial."""
    if agent is not None:
        return False
    if intencao not in {"remarcar", "cancelar"}:
        return False
    if stage not in {"collecting_info", "presenting", "scheduling", "aguardando_pagamento"}:
        return False

    texto = text.lower()
    marcadores_consulta_existente = (
        "minha consulta",
        "consulta marcada",
        "consulta agendada",
        "já tenho consulta",
        "ja tenho consulta",
        "já marquei",
        "ja marquei",
    )
    return not any(marcador in texto for marcador in marcadores_consulta_existente)


def _salvar_nome_contact(phone_hash: str, nome: str) -> None:
    """Persiste nome coletado no Contact para reconhecimento futuro (D-13, D-14)."""
    try:
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                if not contact.collected_name:
                    contact.collected_name = nome
                if not contact.first_name:
                    contact.first_name = nome.split()[0]
                db.commit()
    except Exception as e:
        logger.warning("Falha ao salvar nome no Contact %s: %s", phone_hash[-4:], e)


def _atualizar_contact_por_estado(phone_hash: str, agent) -> None:
    """Atualiza tag e nome do contato conforme a etapa atual do agente."""
    if _tipo_agente(agent) != "AgenteAtendimento":
        return

    try:
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if not contact:
                return

            if agent.etapa == "finalizacao" and agent.pagamento_confirmado:
                set_tag(db, contact, Tag.OK, force=True)
                contact.stage = "agendado"
            elif agent.etapa in ("boas_vindas", "qualificacao"):
                contact.stage = "collecting_info"
            elif agent.etapa in ("agendamento", "forma_pagamento"):
                set_tag(db, contact, Tag.AGUARDANDO_PAGAMENTO)
                contact.stage = "aguardando_pagamento"
            elif agent.etapa in ("apresentacao_planos", "escolha_plano", "preferencia_horario"):
                contact.stage = "presenting"
            elif agent.etapa in ("cadastro_dietbox", "confirmacao", "finalizacao"):
                set_tag(db, contact, Tag.AGENDADO)
                contact.stage = "agendado"

            if agent.nome:
                contact.collected_name = agent.nome
                if not contact.first_name:
                    contact.first_name = agent.nome.split()[0]

            db.commit()
    except Exception as e:
        logger.warning("Falha ao atualizar contato %s pelo estado do agente: %s", phone_hash[-4:], e)
