"""
Router — integra o Orquestrador com os Agentes 1 e 2.

Estado dos agentes é mantido em memória por phone_hash (adequado para dev local).
Para produção: substituir _AGENT_STATE por Redis com serialização JSON.
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

# ── Estado em memória (substituir por Redis em produção) ──────────────────────
# { phone_hash: AgenteAtendimento | AgenteRetencao }
_AGENT_STATE: dict[str, AgenteAtendimento | AgenteRetencao] = {}


def _get_or_create_atendimento(phone: str, phone_hash: str) -> AgenteAtendimento:
    agent = _AGENT_STATE.get(phone_hash)
    if not isinstance(agent, AgenteAtendimento):
        agent = AgenteAtendimento(telefone=phone, phone_hash=phone_hash)
        _AGENT_STATE[phone_hash] = agent
    return agent


def _get_or_create_retencao(
    phone: str, phone_hash: str, nome: str | None, modalidade: str
) -> AgenteRetencao:
    agent = _AGENT_STATE.get(phone_hash)
    if not isinstance(agent, AgenteRetencao):
        agent = AgenteRetencao(telefone=phone, nome=nome, modalidade=modalidade)
        _AGENT_STATE[phone_hash] = agent
    return agent


async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str):
    """
    Ponto de entrada do roteamento.

    1. Carrega contato do banco para obter stage, nome e modalidade
    2. Chama o Orquestrador para classificar a intenção
    3. Despacha para o agente correto
    4. Envia as respostas via Meta API
    """
    from app.escalation import escalar_para_humano
    from app.meta_api import MetaAPIClient
    from app.remarketing import cancel_pending_remarketing

    meta = MetaAPIClient()

    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            logger.error("Contato não encontrado para hash %s", phone_hash[:12])
            return

        stage = contact.stage or "new"
        nome = contact.collected_name or contact.push_name
        primeiro_contato = stage in ("new", "cold_lead", None)

        # Cancela remarketing pendente ao receber mensagem
        if stage in ("cold_lead", "remarketing_sequence", "remarketing"):
            cancel_pending_remarketing(db, contact.id)
            contact.stage = "new"
            stage = "new"

        contact.last_message_at = datetime.now(UTC)
        db.commit()

    # ── Orquestrador classifica intenção ──────────────────────────────────────
    rota = rotear(
        mensagem=text,
        stage_atual=stage,
        primeiro_contato=primeiro_contato,
    )
    agente_destino = rota["agente"]
    intencao = rota["intencao"]

    logger.info(
        "route phone=%s stage=%s intencao=%s agente=%s",
        phone[-4:], stage, intencao, agente_destino,
    )

    # ── Resposta padrão (fora de contexto) ────────────────────────────────────
    if agente_destino == "padrao":
        await _enviar(meta, phone, [rota["resposta_padrao"]])
        return

    # ── Escalação para humano (dúvida clínica) ────────────────────────────────
    if agente_destino == "escalacao":
        agent = _AGENT_STATE.get(phone_hash)
        historico_txt = _resumir_historico(agent)
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
        agent = _get_or_create_atendimento(phone, phone_hash)
        respostas = agent.processar(text)

        # Atualiza tag ao avançar para etapas-chave
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                if agent.etapa in ("agendamento", "forma_pagamento"):
                    set_tag(db, contact, Tag.AGUARDANDO_PAGAMENTO)
                elif agent.etapa in ("cadastro_dietbox", "confirmacao", "finalizacao"):
                    set_tag(db, contact, Tag.AGENDADO)
                    if agent.nome:
                        contact.collected_name = agent.nome
                elif agent.etapa == "finalizacao" and agent.pagamento_confirmado:
                    set_tag(db, contact, Tag.OK, force=True)
                db.commit()

        await _enviar(meta, phone, respostas)
        return

    # ── Agente 2 — Retenção ───────────────────────────────────────────────────
    if agente_destino == "retencao":
        agent = _get_or_create_retencao(
            phone, phone_hash, nome,
            modalidade=_inferir_modalidade(phone_hash),
        )
        if intencao == "cancelar":
            respostas = agent.processar_cancelamento(text)
        else:
            respostas = agent.processar_remarcacao(text)

        await _enviar(meta, phone, respostas)
        return


# ── helpers ───────────────────────────────────────────────────────────────────

async def _enviar(meta, phone: str, mensagens: list[str | None]):
    for msg in mensagens:
        if msg:
            try:
                await meta.send_text(phone, msg)
            except Exception as e:
                logger.error("Falha ao enviar mensagem para %s: %s", phone[-4:], e)


def _resumir_historico(agent) -> str:
    if not agent or not hasattr(agent, "historico"):
        return "(sem histórico)"
    ultimas = agent.historico[-6:]
    return "\n".join(
        f"{'Paciente' if m['role']=='user' else 'Ana'}: {m['content'][:120]}"
        for m in ultimas
    )


def _inferir_modalidade(phone_hash: str) -> str:
    """Tenta recuperar modalidade do agente anterior, senão presencial por padrão."""
    agent = _AGENT_STATE.get(phone_hash)
    if isinstance(agent, AgenteAtendimento) and agent.modalidade:
        return agent.modalidade
    return "presencial"
