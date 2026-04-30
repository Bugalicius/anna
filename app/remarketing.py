"""
Módulo de remarketing — APScheduler AsyncIOScheduler.

Responsabilidades:
- create_scheduler(): cria AsyncIOScheduler com SQLAlchemyJobStore
- _dispatch_due_messages(): processa fila RemarketingQueue de forma async
- _check_escalation_reminders(): verifica lembretes de escalação (async)
- Funções sync de agendamento/cancelamento (usam SQLAlchemy sync)
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import date, datetime, UTC, timedelta

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from app.models import Contact, RemarketingQueue

logger = logging.getLogger(__name__)

REMARKETING_SEQUENCE = [
    {"position": 1, "template": "ana_followup_24h", "delay_hours": 24},
    {"position": 2, "template": "ana_followup_7d", "delay_hours": 168},
    {"position": 3, "template": "ana_followup_30d", "delay_hours": 720},
]

MAX_REMARKETING = 3
RATE_LIMIT_PER_MIN = 30

# ── Textos aprovados — fonte de verdade (D-02, D-03, D-04) ───────────────────

MSG_FOLLOWUP_24H = (
    "Eiii! \U0001f60a Tudo bem por aí?\n\n"
    "Fico pensando se ficou alguma dúvida sobre a consulta com a Thaynara... "
    "Pode me perguntar à vontade, tô aqui pra isso! \U0001f49a\n\n"
    "Quando quiser marcar é só me falar \U0001f4c5"
)

MSG_FOLLOWUP_7D = (
    "Oii! Passando pra saber se você teve chance de pensar na consulta "
    "com a Thaynara \U0001f33f\n\n"
    "Às vezes bate aquela dúvida se vale a pena... mas a maioria das pacientes "
    "conta que a primeira consulta já muda bastante a relação com a alimentação \U0001f60a\n\n"
    "Se quiser conversar sobre qualquer coisa antes de decidir, me chama! \U0001f449"
)

MSG_FOLLOWUP_30D = (
    "Eiii, última passagem por aqui! \U0001f49a\n\n"
    "Sei que a vida corrida faz a gente adiar algumas coisas... "
    "Se um dia você quiser dar esse passo, pode me chamar que a gente vê "
    "o melhor horário pra você com a Thaynara \U0001f4c5\n\n"
    "Qualquer coisa, estarei por aqui! \U0001f60a"
)

TEMPLATE_NAMES = {
    1: "ana_followup_24h",
    2: "ana_followup_7d",
    3: "ana_followup_30d",
}

# Textos por posicao na sequencia (usados por _enviar_remarketing)
_MSG_POR_POSICAO = {
    1: MSG_FOLLOWUP_24H,
    2: MSG_FOLLOWUP_7D,
    3: MSG_FOLLOWUP_30D,
}

# Templates Meta aprovados? Mudar para True apos aprovacao no Business Manager (D-06)
# Env var permite ativar sem redeploy: REMARKETING_TEMPLATES_APPROVED=true
TEMPLATES_APPROVED = os.environ.get("REMARKETING_TEMPLATES_APPROVED", "false").lower() == "true"

# ── Guia: Submissao de Templates no Meta Business Manager ────────────────────
#
# Templates necessarios (D-07):
#   1. ana_followup_24h  — categoria: MARKETING
#   2. ana_followup_7d   — categoria: MARKETING
#   3. ana_followup_30d  — categoria: MARKETING
#
# Passos:
#   1. Acesse business.facebook.com > WhatsApp Manager > Message Templates
#   2. Crie cada template com categoria "Marketing"
#   3. Idioma: Portuguese (BR) — codigo pt_BR
#   4. Corpo: copie EXATAMENTE o texto de MSG_FOLLOWUP_* (incluindo emojis)
#   5. Submeta para revisao — aprovacao pode levar ate 48h
#   6. Apos aprovacao, defina REMARKETING_TEMPLATES_APPROVED=true no .env
#
# Enquanto templates nao aprovados:
#   - Mensagem 24h: tenta send_text (funciona se paciente escreveu nas ultimas 24h)
#   - Mensagens 7d/30d: ficam na fila, nao sao enviadas (sem erro)
# ─────────────────────────────────────────────────────────────────────────────


# ── Funções sync de agendamento (mantidas síncronas) ──────────────────────────

def can_schedule_remarketing(db: Session, contact_id: str) -> bool:
    """Verifica se o contato pode receber mais mensagens de remarketing."""
    contact = db.get(Contact, contact_id)
    if not contact or contact.remarketing_count >= MAX_REMARKETING:
        return False
    if contact.stage == "lead_perdido":
        return False

    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(RemarketingQueue)
        .filter(
            RemarketingQueue.contact_id == contact_id,
            RemarketingQueue.sent_at >= today_start,
            RemarketingQueue.counts_toward_limit.is_(True),
        )
        .first()
    )
    return sent_today is None


def schedule_time_remarketing(db: Session, contact_id: str, template: str,
                               delay_hours: float, position: int) -> "RemarketingQueue | None":
    """Agenda mensagem de remarketing por tempo."""
    if not can_schedule_remarketing(db, contact_id):
        return None
    scheduled = datetime.now(UTC) + timedelta(hours=delay_hours)
    entry = RemarketingQueue(
        contact_id=contact_id,
        template_name=template,
        scheduled_for=scheduled,
        status="pending",
        sequence_position=position,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()
    return entry



def cancel_pending_remarketing(db: Session, contact_id: str):
    """Cancela todas as entradas pendentes de remarketing para o contato."""
    pending = (
        db.query(RemarketingQueue)
        .filter_by(contact_id=contact_id, status="pending")
        .all()
    )
    for entry in pending:
        entry.status = "cancelled"
    db.commit()


# ── Jobs async do scheduler ───────────────────────────────────────────────────

async def _dispatch_due_messages() -> None:
    """Job APScheduler: processa entradas pendentes da fila de remarketing."""
    from app.database import SessionLocal
    from app.meta_api import MetaAPIClient

    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    redis_client = aioredis.Redis.from_url(redis_url, decode_responses=True)

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("WHATSAPP_TOKEN", ""),
    )

    try:
        with SessionLocal() as db:
            now = datetime.now(UTC)
            due = (
                db.query(RemarketingQueue)
                .filter(RemarketingQueue.status == "pending",
                        RemarketingQueue.scheduled_for <= now)
                .order_by(RemarketingQueue.scheduled_for)
                .limit(50)
                .all()
            )

            for entry in due:
                # Rate limit Redis: máx 30/min
                minute_key = f"meta:rate:{now.strftime('%Y%m%d%H%M')}"
                count = await redis_client.incr(minute_key)
                if count == 1:
                    await redis_client.expire(minute_key, 60)
                if count > RATE_LIMIT_PER_MIN:
                    # Reagendar para próximo minuto
                    entry.scheduled_for = now + timedelta(minutes=1)
                    db.commit()
                    continue

                contact = db.get(Contact, entry.contact_id)
                if not contact or contact.stage in ("archived", "lead_perdido"):
                    entry.status = "cancelled"
                    db.commit()
                    continue

                if not contact.phone_e164:
                    logger.error("Contato %s sem phone_e164, cancelando entry", entry.contact_id)
                    entry.status = "cancelled"
                    db.commit()
                    continue

                # D-11: pular se paciente tem conversa ativa no Redis
                state_key = f"agent_state:{contact.phone_hash}"
                has_active = await redis_client.exists(state_key)
                if has_active:
                    logger.info("Remarketing skip — conversa ativa para %s", contact.phone_hash[-4:])
                    continue  # pula este ciclo, tenta no proximo (1 min)

                success = await _enviar_remarketing(meta, contact.phone_e164, entry)
                if success:
                    entry.status = "sent"
                    entry.sent_at = now
                    if entry.counts_toward_limit:
                        contact.remarketing_count += 1
                    if contact.remarketing_count >= MAX_REMARKETING:
                        contact.stage = "lead_perdido"  # D-01: apos 3 sem resposta = lead perdido
                    db.commit()
                    await asyncio.sleep(2)  # intervalo mínimo entre disparos
                else:
                    # Para position 1 (janela fechada): marca failed
                    # Para position 2/3 (templates nao aprovados): mantém pending
                    if entry.sequence_position == 1:
                        entry.status = "failed"
                        db.commit()
                    # positions 2/3 sem template aprovado: nao muda status — retry no proximo ciclo
    finally:
        await redis_client.aclose()


async def _enviar_remarketing(
    meta: "MetaAPIClient",
    to: str,
    entry: "RemarketingQueue",
) -> bool:
    """
    Envia mensagem de remarketing usando o canal correto.

    - Position 1 (24h): tenta send_text primeiro (D-05).
      Se a Meta rejeitar por janela fechada (erro 131026), loga e retorna False.
    - Position 2/3 (7d/30d): usa send_template se aprovados (D-06).
      Se templates nao aprovados, retorna False (entry permanece pending).

    Returns: True se enviado com sucesso, False se falhou ou nao disponivel.
    """
    position = entry.sequence_position

    if position == 1:
        # 24h — tenta texto livre (D-05)
        texto = _MSG_POR_POSICAO.get(position)
        if not texto:
            return False
        try:
            await meta.send_text(to=to, text=texto)
            return True
        except Exception as e:
            error_str = str(e)
            if "131026" in error_str or "re-engage" in error_str.lower():
                logger.warning("Janela 24h fechada para %s — aguardando template", to[-4:])
            else:
                logger.error("Falha send_text remarketing para %s: %s", to[-4:], e)
            return False
    else:
        # 7d/30d — usa template Meta (D-06)
        if not TEMPLATES_APPROVED:
            logger.info(
                "Templates Meta nao aprovados — skip position %d para %s",
                position, to[-4:],
            )
            return False
        template_name = TEMPLATE_NAMES.get(position)
        if not template_name:
            return False
        try:
            await meta.send_template(to=to, template_name=template_name)
            return True
        except Exception as e:
            logger.error("Falha send_template %s para %s: %s", template_name, to[-4:], e)
            return False


async def _check_escalation_reminders() -> None:
    """Job APScheduler: verifica lembretes de escalação pendentes a cada 5 minutos."""
    from app.meta_api import MetaAPIClient
    from app.escalation import enviar_lembretes_pendentes

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("WHATSAPP_TOKEN", ""),
    )

    try:
        enviados = await enviar_lembretes_pendentes(meta)
        if enviados > 0:
            logger.info("Lembretes de escalação enviados: %d", enviados)
    except Exception as e:
        logger.error("Falha no job de lembretes de escalação: %s", e)


# ── Helper testavel para logica de dispatch ───────────────────────────────────

async def _dispatch_from_db(
    entries: list,
    db,
    redis_client,
    meta,
) -> None:
    """
    Processa lista de entries de remarketing com redis_client e meta injetados.

    Extraido de _dispatch_due_messages para permitir testes unitarios sem
    necessidade de patchear imports internos (mesmo padrao do Plan 03-01).
    """
    now = datetime.now(UTC)

    for entry in entries:
        # Rate limit Redis: max 30/min
        minute_key = f"meta:rate:{now.strftime('%Y%m%d%H%M')}"
        count = await redis_client.incr(minute_key)
        if count == 1:
            await redis_client.expire(minute_key, 60)
        if count > RATE_LIMIT_PER_MIN:
            entry.scheduled_for = now + timedelta(minutes=1)
            db.commit()
            continue

        contact = db.get(Contact, entry.contact_id)
        if not contact or contact.stage in ("archived", "lead_perdido"):
            entry.status = "cancelled"
            db.commit()
            continue

        if not contact.phone_e164:
            logger.error("Contato %s sem phone_e164, cancelando entry", entry.contact_id)
            entry.status = "cancelled"
            db.commit()
            continue

        # D-11: pular se paciente tem conversa ativa no Redis
        state_key = f"agent_state:{contact.phone_hash}"
        has_active = await redis_client.exists(state_key)
        if has_active:
            logger.info("Remarketing skip — conversa ativa para %s", contact.phone_hash[-4:])
            continue  # pula este ciclo, tenta no proximo (1 min)

        success = await _enviar_remarketing(meta, contact.phone_e164, entry)
        if success:
            entry.status = "sent"
            entry.sent_at = now
            if entry.counts_toward_limit:
                contact.remarketing_count += 1
            if contact.remarketing_count >= MAX_REMARKETING:
                contact.stage = "lead_perdido"  # D-01: apos 3 sem resposta = lead perdido
            db.commit()
            await asyncio.sleep(2)  # intervalo minimo entre disparos
        else:
            # Para position 1 (janela fechada): marca failed
            # Para position 2/3 (templates nao aprovados): mantém pending
            if entry.sequence_position == 1:
                entry.status = "failed"
                db.commit()
            # positions 2/3 sem template aprovado: nao muda status — retry no proximo ciclo


# ── Confirmação de presença ───────────────────────────────────────────────────

_DIAS_SEMANA_PT = {
    0: "Segunda-feira", 1: "Terça-feira", 2: "Quarta-feira",
    3: "Quinta-feira", 4: "Sexta-feira", 5: "Sábado", 6: "Domingo",
}

_ENDERECO_PRESENCIAL = (
    "📍 Aura Clinic & Beauty – Rua Melo Franco, 204, Sala 103, Jardim da Glória – Vespasiano."
)


def _formatar_dt(dt: datetime) -> str:
    dia = _DIAS_SEMANA_PT[dt.weekday()]
    hora = dt.strftime("%Hh%M") if dt.minute != 0 else dt.strftime("%Hh")
    return f"{dia}, {dt.day:02d}/{dt.month:02d}/{dt.year}, às {hora}"


def _corpo_confirmacao_sexta(primeiro_nome: str, dt: datetime, tipo: str) -> str:
    """
    Corpo da mensagem de sexta (com botões interativos).
    Inclui orientações específicas por tipo, mas sem botão embutido no texto.
    """
    data_fmt = _formatar_dt(dt)

    _POLITICA = (
        "👉 Caso precise cancelar ou remarcar, avise com pelo menos 24h de antecedência.\n"
        "⚠️ Sem aviso no prazo, a consulta é considerada realizada e o valor não é reembolsado."
    )

    if tipo in ("consulta_presencial", "retorno_presencial"):
        tipo_label = "retorno presencial" if tipo == "retorno_presencial" else "consulta presencial"
        return (
            f"Oi, {primeiro_nome}! Tudo bem?\n\n"
            "Aqui é a Ana, assistente da Nutri Thaynara.\n"
            f"Sua {tipo_label} está marcada para {data_fmt}.\n\n"
            f"{_POLITICA}\n\n"
            f"{_ENDERECO_PRESENCIAL}\n"
            "⏳ Tolerância de atraso: 10 min.\n"
            "Lembre-se de vir com short e top/camiseta de treino 💚"
        )
    elif tipo in ("consulta_online", "retorno_online"):
        tipo_label = "retorno online" if tipo == "retorno_online" else "consulta online"
        extras = (
            "\n\nNão se esqueça:\n"
            "  • Pese-se pela manhã\n"
            "  • Envie as fotos antes da consulta (no número da nutri)\n"
            "  • Certifique-se de ter boa conexão de internet\n"
            "⏳ Tolerância de atraso: 10 min."
        )
        return (
            f"Oi, {primeiro_nome}! Tudo bem?\n\n"
            "Aqui é a Ana, assistente da Nutri Thaynara.\n"
            f"Seu {tipo_label} está marcado para {data_fmt}.\n\n"
            f"{_POLITICA}"
            f"{extras}"
        )
    else:  # pre_agendamento
        return (
            f"Oi, {primeiro_nome}! Tudo bem?\n\n"
            "Aqui é a Ana, assistente da Nutri Thaynara.\n"
            f"Sua consulta pré-agendada está marcada para {data_fmt}.\n\n"
            f"{_POLITICA}"
        )


def _msg_lembrete_vespera(primeiro_nome: str, dt: datetime, tipo: str) -> str:
    """Mensagem simples de lembrete na véspera (18h), sem botões."""
    data_fmt = _formatar_dt(dt)

    if tipo in ("consulta_online", "retorno_online"):
        extras = (
            "\n\nNão esqueça de se pesar pela manhã e enviar as fotos antes da consulta 📸"
        )
    elif tipo in ("consulta_presencial", "retorno_presencial"):
        extras = "\n\nLembra de chegar com 10 minutinhos de antecedência 😊"
    else:
        extras = ""

    return (
        f"Oi, {primeiro_nome}! Passando só para te lembrar da sua consulta *amanhã*, {data_fmt} 💚"
        f"{extras}\n\n"
        "Qualquer dúvida ou imprevisto, me avisa por aqui!"
    )


_BOTOES_CONFIRMACAO = [
    {"id": "confirmar_presenca", "title": "Confirmar ✅"},
    {"id": "remarcar_consulta", "title": "Preciso remarcar 📅"},
]


async def _disparar_confirmacoes_sexta(consultas: list[dict]) -> None:
    """Envia mensagem com botões interativos (confirmar / remarcar) para cada consulta."""
    from app.meta_api import MetaAPIClient

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("WHATSAPP_TOKEN", ""),
    )

    for consulta in consultas:
        telefone = consulta["telefone"]
        corpo = _corpo_confirmacao_sexta(
            consulta["primeiro_nome"], consulta["datetime"], consulta["tipo"]
        )
        try:
            await meta.send_interactive_buttons(
                to=telefone, body=corpo, buttons=_BOTOES_CONFIRMACAO,
            )
            logger.info(
                "Confirmação semanal (botões) enviada → %s [%s]", telefone[-4:], consulta["tipo"],
            )
        except Exception as e:
            error_str = str(e)
            if "131026" in error_str or "re-engage" in error_str.lower():
                logger.warning("Janela 24h fechada para %s — confirmação semanal não enviada", telefone[-4:])
            else:
                logger.error("Falha ao enviar confirmação semanal para %s: %s", telefone[-4:], e)
        await asyncio.sleep(random.randint(8, 20))


async def _disparar_lembretes_vespera(consultas: list[dict]) -> None:
    """Envia lembrete simples de texto para cada consulta do dia seguinte."""
    from app.meta_api import MetaAPIClient

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("WHATSAPP_TOKEN", ""),
    )

    for consulta in consultas:
        telefone = consulta["telefone"]
        mensagem = _msg_lembrete_vespera(
            consulta["primeiro_nome"], consulta["datetime"], consulta["tipo"]
        )
        try:
            await meta.send_text(to=telefone, text=mensagem)
            logger.info("Lembrete véspera enviado → %s [%s]", telefone[-4:], consulta["tipo"])
        except Exception as e:
            error_str = str(e)
            if "131026" in error_str or "re-engage" in error_str.lower():
                logger.warning("Janela 24h fechada para %s — lembrete véspera não enviado", telefone[-4:])
            else:
                logger.error("Falha ao enviar lembrete véspera para %s: %s", telefone[-4:], e)
        await asyncio.sleep(random.randint(8, 20))


# ── Jobs de confirmação de presença (DESATIVADOS — ativar no lançamento) ──────
# Para ativar: descomentar os add_job correspondentes em create_scheduler().

async def _confirmacao_semanal() -> None:
    """Job: toda sexta às 13h — envia confirmação com botões para consultas da semana seguinte."""
    from app.agents.dietbox_worker import buscar_consultas_periodo

    hoje = date.today()
    dias_ate_segunda = (7 - hoje.weekday()) % 7 or 7
    proxima_segunda = hoje + timedelta(days=dias_ate_segunda)
    proxima_sexta = proxima_segunda + timedelta(days=4)

    logger.info("Confirmação semanal: buscando consultas de %s a %s", proxima_segunda, proxima_sexta)
    try:
        consultas = buscar_consultas_periodo(proxima_segunda, proxima_sexta)
        logger.info("Confirmação semanal: %d consulta(s) encontrada(s)", len(consultas))
        await _disparar_confirmacoes_sexta(consultas)
    except Exception as e:
        logger.error("Falha no job de confirmação semanal: %s", e)


async def _lembrete_vespera() -> None:
    """Job: todo dia às 18h — envia lembrete de texto para consultas do dia seguinte."""
    from app.agents.dietbox_worker import buscar_consultas_periodo

    amanha = date.today() + timedelta(days=1)
    logger.info("Lembrete véspera: buscando consultas de %s", amanha)
    try:
        consultas = buscar_consultas_periodo(amanha, amanha)
        logger.info("Lembrete véspera: %d consulta(s) encontrada(s)", len(consultas))
        await _disparar_lembretes_vespera(consultas)
    except Exception as e:
        logger.error("Falha no job de lembrete véspera: %s", e)


# ── Factory do scheduler ──────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    """Cria AsyncIOScheduler com SQLAlchemyJobStore para persistência entre reinicios."""
    db_url = os.environ.get("DATABASE_URL", "")
    jobstores = {"default": SQLAlchemyJobStore(url=db_url)} if db_url else {}
    scheduler = AsyncIOScheduler(jobstores=jobstores)
    scheduler.add_job(
        _dispatch_due_messages, "interval", minutes=1,
        id="remarketing_dispatcher", replace_existing=True,
    )
    scheduler.add_job(
        _check_escalation_reminders, "interval", minutes=5,
        id="escalation_reminders", replace_existing=True,
    )
    # ── Confirmação de presença — DESATIVADA até o lançamento ─────────────────
    # Descomentar quando pronto para ativar:
    # scheduler.add_job(
    #     _confirmacao_semanal,
    #     CronTrigger(day_of_week="fri", hour=13, minute=0, timezone="America/Sao_Paulo"),
    #     id="confirmacao_semanal", replace_existing=True,
    # )
    # scheduler.add_job(
    #     _lembrete_vespera,
    #     CronTrigger(hour=18, minute=0, timezone="America/Sao_Paulo"),
    #     id="lembrete_vespera", replace_existing=True,
    # )
    return scheduler
