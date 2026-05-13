"""
Scheduler v2 — jobs automáticos do Agente Ana.

Jobs:
  - job_confirmacao_semanal: toda sexta-feira às 13h
    Busca consultas da semana seguinte e envia mensagem com botões
    "Confirmar / Remarcar". Armazena chave Redis para rastrear resposta.
    Agenda follow-up dinâmico de 24h via APScheduler.

  - job_lembrete_vespera: todo dia às 18h
    Busca consultas do dia seguinte e envia lembrete de texto simples
    (sem botões — janela 24h da Meta pode estar fechada).

  - job_followup_check: a cada hora
    Varre chaves Redis de confirmação pendente. Se enviado há 24h+ e
    paciente não respondeu, envia "{nome}?" (único follow-up).
    Se dia da consulta chegou e ainda sem resposta, notifica Breno.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))
REDIS_TTL_CONFIRMACAO = 60 * 60 * 24 * 7  # 7 dias

_scheduler = None  # referência ao scheduler registrado


# ─────────────────────────────────────────────────────────────────────────────
# Registro de jobs
# ─────────────────────────────────────────────────────────────────────────────

def register_jobs(scheduler) -> None:
    """Adiciona os jobs v2 ao scheduler existente."""
    global _scheduler
    _scheduler = scheduler

    scheduler.add_job(
        job_confirmacao_semanal,
        "cron",
        day_of_week="fri",
        hour=13,
        minute=0,
        id="v2_confirmacao_semanal",
        replace_existing=True,
    )
    scheduler.add_job(
        job_lembrete_vespera,
        "cron",
        hour=18,
        minute=0,
        id="v2_lembrete_vespera",
        replace_existing=True,
    )
    scheduler.add_job(
        job_followup_check,
        "interval",
        hours=1,
        id="v2_followup_check",
        replace_existing=True,
    )
    logger.info("Jobs v2 registrados: confirmacao_semanal, lembrete_vespera, followup_check")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de data
# ─────────────────────────────────────────────────────────────────────────────

def _proxima_semana() -> tuple[date, date]:
    """Retorna (proxima_segunda, proxima_sexta)."""
    hoje = datetime.now(BRT).date()
    dias_ate_segunda = (7 - hoje.weekday()) % 7
    if dias_ate_segunda == 0:
        dias_ate_segunda = 7
    segunda = hoje + timedelta(days=dias_ate_segunda)
    sexta = segunda + timedelta(days=4)
    return segunda, sexta


def _amanha() -> date:
    return datetime.now(BRT).date() + timedelta(days=1)


DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]


# ─────────────────────────────────────────────────────────────────────────────
# Redis helpers
# ─────────────────────────────────────────────────────────────────────────────

def _redis_key_confirmacao(telefone: str) -> str:
    return f"confirmacao_pendente:{telefone}"


async def _salvar_confirmacao_pendente(telefone: str, nome: str, dt_consulta: datetime) -> None:
    try:
        import redis.asyncio as aioredis
        import os
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        client = aioredis.Redis.from_url(url, decode_responses=True)
        payload = json.dumps({
            "nome": nome,
            "dt_consulta": dt_consulta.isoformat(),
            "enviada_em": datetime.now(BRT).isoformat(),
            "followup_enviado": False,
        })
        await client.set(_redis_key_confirmacao(telefone), payload, ex=REDIS_TTL_CONFIRMACAO)
        await client.aclose()
    except Exception as exc:
        logger.warning("Falha ao salvar confirmacao Redis para %s: %s", telefone, exc)


async def limpar_confirmacao_pendente(telefone: str) -> None:
    """Chamado pelo orchestrator quando paciente confirma ou pede para remarcar."""
    try:
        import redis.asyncio as aioredis
        import os
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        client = aioredis.Redis.from_url(url, decode_responses=True)
        await client.delete(_redis_key_confirmacao(telefone))
        await client.aclose()
    except Exception as exc:
        logger.warning("Falha ao limpar confirmacao Redis para %s: %s", telefone, exc)


async def _buscar_pendentes() -> list[dict[str, Any]]:
    """Busca todas as confirmacoes pendentes do Redis."""
    try:
        import redis.asyncio as aioredis
        import os
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        client = aioredis.Redis.from_url(url, decode_responses=True)
        keys = await client.keys("confirmacao_pendente:*")
        pendentes = []
        for key in keys:
            raw = await client.get(key)
            if raw:
                data = json.loads(raw)
                data["telefone"] = key.split(":", 1)[1]
                data["_redis_key"] = key
                pendentes.append(data)
        await client.aclose()
        return pendentes
    except Exception as exc:
        logger.warning("Falha ao buscar pendentes Redis: %s", exc)
        return []


async def _marcar_followup_enviado(telefone: str) -> None:
    try:
        import redis.asyncio as aioredis
        import os
        url = os.environ.get("REDIS_URL", "redis://redis:6379")
        client = aioredis.Redis.from_url(url, decode_responses=True)
        key = _redis_key_confirmacao(telefone)
        raw = await client.get(key)
        if raw:
            data = json.loads(raw)
            data["followup_enviado"] = True
            ttl = await client.ttl(key)
            await client.set(key, json.dumps(data), ex=max(ttl, 1))
        await client.aclose()
    except Exception as exc:
        logger.warning("Falha ao marcar followup enviado para %s: %s", telefone, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Templates de confirmação
# ─────────────────────────────────────────────────────────────────────────────

def _template_presencial(primeiro_nome: str, dia_semana: str, data_fmt: str, hora_fmt: str) -> str:
    return (
        f"Oi, {primeiro_nome}! Tudo bem?\n\n"
        f"Aqui é a Ana, assistente da Nutri Thaynara.\n"
        f"Passando para te lembrar da sua consulta presencial na {dia_semana}, {data_fmt}, às {hora_fmt}. *Posso confirmar?*\n\n"
        "👉 Caso precise cancelar ou remarcar, é necessário avisar com mínimo de 24h de antecedência.\n"
        "⚠️ Se não houver aviso nesse prazo ou se você não comparecer, a consulta será considerada realizada e o valor pago, não será reembolsado.\n\n"
        "📍 Aura Clinic & Beauty – Rua Melo Franco, 204, Sala 103, Jardim da Glória – Vespasiano.\n"
        "⏳ Tolerância de atraso: 10 min.\n"
        "Ah, não esqueça de vir com short e top/camiseta de treino, pois teremos sua avaliação física.\n\n"
        "Até logo!! 💚"
    )


def _template_online(primeiro_nome: str, tipo_consulta: str, dia_semana: str, data_fmt: str, hora_fmt: str) -> str:
    return (
        f"Oi, {primeiro_nome}. Tudo bem?\n\n"
        f"Aqui é a Ana, assistente da Nutri Thaynara.\n"
        f"Passando para te lembrar do seu {tipo_consulta} online agendado para {dia_semana}, {data_fmt}, às {hora_fmt}. *Posso confirmar?*\n\n"
        "👉 Caso precise cancelar ou remarcar, é necessário avisar com pelo menos 24h de antecedência.\n"
        "⚠️ Se não houver aviso nesse prazo ou se você não comparecer, a consulta será considerada realizada normalmente "
        "(tanto para quem já fez sinal quanto para quem tem plano Premium).\n\n"
        "✅ Certifique-se de ter uma boa conexão de internet durante o horário.\n"
        "⏳ Tolerância de atraso: 10 min.\n\n"
        "Ah, não se esqueça:\n"
        "  • Pese-se pela manhã\n"
        "  • Envie as fotos com a mesma roupa e de preferência no mesmo local, para o número da Nutri antes da consulta.\n\n"
        "Qualquer dúvida, estou a disposição!"
    )


BOTOES_CONFIRMACAO = [
    {"id": "confirmar_presenca", "title": "Confirmar ✅"},
    {"id": "remarcar_consulta", "title": "Preciso remarcar 📅"},
]


# ─────────────────────────────────────────────────────────────────────────────
# Job 1 — Confirmação semanal (sex 13h)
# ─────────────────────────────────────────────────────────────────────────────

async def job_confirmacao_semanal() -> None:
    """Busca consultas da semana seguinte e envia confirmação com botões."""
    from app.agents.dietbox_worker import buscar_consultas_periodo
    from app.meta_api import MetaAPIClient

    segunda, sexta = _proxima_semana()
    logger.info("job_confirmacao_semanal: buscando consultas %s – %s", segunda, sexta)

    loop = asyncio.get_event_loop()
    try:
        consultas = await loop.run_in_executor(
            None, lambda: buscar_consultas_periodo(segunda, sexta)
        )
    except Exception as exc:
        logger.exception("Erro ao buscar consultas para confirmacao semanal: %s", exc)
        return

    if not consultas:
        logger.info("job_confirmacao_semanal: nenhuma consulta encontrada")
        return

    client = MetaAPIClient()
    for consulta in consultas:
        try:
            await _enviar_confirmacao(client, consulta)
        except Exception as exc:
            logger.exception(
                "Erro ao enviar confirmacao para %s: %s", consulta.get("telefone"), exc
            )


async def _enviar_confirmacao(client, consulta: dict[str, Any]) -> None:
    telefone = str(consulta.get("telefone") or "")
    if not telefone:
        return

    primeiro_nome = str(consulta.get("primeiro_nome") or "você")
    dt = consulta.get("datetime")
    if not isinstance(dt, datetime):
        return

    dia_semana = DIAS_PT[dt.weekday()]
    data_fmt = dt.strftime("%d/%m/%Y")
    hora_fmt = dt.strftime("%H:%M")
    tipo = str(consulta.get("tipo") or "")
    is_online = "online" in tipo
    tipo_consulta = "retorno" if "retorno" in tipo else "consulta"

    if is_online:
        texto = _template_online(primeiro_nome, tipo_consulta, dia_semana, data_fmt, hora_fmt)
    else:
        texto = _template_presencial(primeiro_nome, dia_semana, data_fmt, hora_fmt)

    await client.send_interactive_buttons(to=telefone, body=texto, buttons=BOTOES_CONFIRMACAO)

    # Para online: envia contato da Thaynara após a mensagem
    if is_online:
        try:
            await client.send_contact(to=telefone, nome="Thaynara Teixeira", telefone="5531991394759")
        except Exception as exc:
            logger.warning("Falha ao enviar contato Thaynara para %s: %s", telefone, exc)

    # Persiste pendência no Redis para rastrear follow-up
    await _salvar_confirmacao_pendente(telefone, primeiro_nome, dt)
    logger.info("Confirmacao enviada para %s (%s)", telefone, primeiro_nome)


# ─────────────────────────────────────────────────────────────────────────────
# Job 2 — Lembrete véspera (diário 18h)
# ─────────────────────────────────────────────────────────────────────────────

async def job_lembrete_vespera() -> None:
    """Busca consultas do dia seguinte e envia lembrete de texto simples."""
    from app.agents.dietbox_worker import buscar_consultas_periodo
    from app.meta_api import MetaAPIClient

    amanha = _amanha()
    logger.info("job_lembrete_vespera: buscando consultas para %s", amanha)

    loop = asyncio.get_event_loop()
    try:
        consultas = await loop.run_in_executor(
            None, lambda: buscar_consultas_periodo(amanha, amanha)
        )
    except Exception as exc:
        logger.exception("Erro ao buscar consultas para lembrete vespera: %s", exc)
        return

    if not consultas:
        logger.info("job_lembrete_vespera: nenhuma consulta para amanha")
        return

    client = MetaAPIClient()
    for consulta in consultas:
        try:
            await _enviar_lembrete_vespera(client, consulta)
        except Exception as exc:
            logger.exception(
                "Erro ao enviar lembrete vespera para %s: %s", consulta.get("telefone"), exc
            )


async def _enviar_lembrete_vespera(client, consulta: dict[str, Any]) -> None:
    telefone = str(consulta.get("telefone") or "")
    if not telefone:
        return

    primeiro_nome = str(consulta.get("primeiro_nome") or "você")
    dt = consulta.get("datetime")
    if not isinstance(dt, datetime):
        return

    hora_fmt = dt.strftime("%H:%M")
    # Sem botões — janela 24h da Meta pode estar fechada
    texto = f"Oi {primeiro_nome}! 💚 Só passando pra te lembrar da sua consulta amanhã às {hora_fmt}.\nAté lá! 💚"
    await client.send_text(to=telefone, text=texto)
    logger.info("Lembrete vespera enviado para %s", telefone)


# ─────────────────────────────────────────────────────────────────────────────
# Job 3 — Follow-up check (a cada hora)
# ─────────────────────────────────────────────────────────────────────────────

async def job_followup_check() -> None:
    """
    Varre confirmações pendentes no Redis.
    - 24h+ sem resposta e followup não enviado → manda "{nome}?"
    - Dia da consulta sem resposta → notifica Breno (nunca desmarca automaticamente)
    """
    from app.meta_api import MetaAPIClient
    from app.conversation.tools.registry import call_tool

    pendentes = await _buscar_pendentes()
    if not pendentes:
        return

    agora = datetime.now(BRT)
    client = MetaAPIClient()

    for p in pendentes:
        telefone = p.get("telefone") or ""
        nome = p.get("nome") or "você"
        followup_enviado = bool(p.get("followup_enviado"))

        try:
            enviada_em = datetime.fromisoformat(str(p.get("enviada_em") or ""))
            dt_consulta = datetime.fromisoformat(str(p.get("dt_consulta") or ""))
        except ValueError:
            continue

        horas_desde_envio = (agora - enviada_em.astimezone(BRT)).total_seconds() / 3600

        # Dia da consulta chegou e ainda sem resposta → notifica Breno
        if agora.date() >= dt_consulta.date():
            await _notificar_breno_nao_confirmou(call_tool, nome, telefone, dt_consulta)
            await limpar_confirmacao_pendente(telefone)
            continue

        # 24h+ sem resposta, follow-up ainda não enviado
        if horas_desde_envio >= 24 and not followup_enviado:
            try:
                await client.send_text(to=telefone, text=f"{nome}?")
                await _marcar_followup_enviado(telefone)
                logger.info("Follow-up 24h enviado para %s", telefone)
            except Exception as exc:
                logger.warning("Falha ao enviar follow-up para %s: %s", telefone, exc)


async def _notificar_breno_nao_confirmou(
    call_tool, nome: str, telefone: str, dt_consulta: datetime
) -> None:
    hora = dt_consulta.strftime("%H:%M")
    mensagem = (
        f"⚠️ Ana: {nome} não confirmou presença para hoje às {hora}.\n"
        f"Telefone: {telefone}\n\n"
        "Aguardo orientação se devo desmarcar ou continuar tentando contato.\n"
        "NUNCA desmarcado automaticamente sem aprovação."
    )
    try:
        await call_tool("notificar_breno", {"mensagem": mensagem})
        logger.info("Breno notificado sobre nao-confirmacao de %s", nome)
    except Exception as exc:
        logger.warning("Falha ao notificar Breno sobre %s: %s", nome, exc)
