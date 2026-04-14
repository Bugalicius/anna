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

import logging
from datetime import datetime, UTC

from app.agents.atendimento import AgenteAtendimento
from app.agents.orchestrator import rotear
from app.agents.retencao import AgenteRetencao
from app.database import SessionLocal
from app.models import Contact
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
    from app.remarketing import cancel_pending_remarketing

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
    rota = rotear(
        mensagem=text,
        stage_atual=stage,
        primeiro_contato=primeiro_contato,
        agente_ativo=tipo_agente,
    )
    intencao = rota["intencao"]
    agente_destino = rota["agente"]

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
        elif intencao in _INTENCOES_INLINE:
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

        # Atualiza tag ao avançar para etapas-chave
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                if agente.etapa in ("agendamento", "forma_pagamento"):
                    set_tag(db, contact, Tag.AGUARDANDO_PAGAMENTO)
                elif agente.etapa in ("cadastro_dietbox", "confirmacao", "finalizacao"):
                    set_tag(db, contact, Tag.AGENDADO)
                    if agente.nome:
                        contact.collected_name = agente.nome
                        # Persiste first_name para reconhecimento futuro (D-13)
                        if not contact.first_name and agente.nome:
                            contact.first_name = agente.nome.split()[0]
                elif agente.etapa == "finalizacao" and agente.pagamento_confirmado:
                    set_tag(db, contact, Tag.OK, force=True)
                db.commit()

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

async def _enviar(meta, phone: str, mensagens: list[str | None]):
    """Envia lista de mensagens via Meta API, absorvendo falhas individuais."""
    for msg in mensagens:
        if msg:
            try:
                await meta.send_text(phone, msg)
            except Exception as e:
                logger.error("Falha ao enviar mensagem para %s: %s", phone[-4:], e)


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
