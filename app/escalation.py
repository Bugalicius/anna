"""
Escalação para humano — 3 caminhos (D-05, D-06, D-07).

Caminhos:
  D-05: duvida_clinica + paciente cadastrado → envia contato da Thaynara
  D-06: duvida_clinica + lead → relay para Breno com PendingEscalation
  D-07: Ana não sabe → relay para Breno com PendingEscalation

Relay bidirecional (D-09, D-10):
  - Breno recebe contexto + lembretes (15min x4, depois 1h)
  - Após 1h sem resposta: paciente avisado
  - Resposta do Breno repassada ao paciente e salva como FAQ aprendido (D-11)

REGRAS DE SEGURANÇA:
  - _NUMERO_INTERNO NUNCA exposto ao paciente — usado apenas para envio e detecção
  - Paciente recebe apenas mensagens filtradas
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

BRT = timezone(timedelta(hours=-3))

logger = logging.getLogger(__name__)

# ── Constantes internas — NUNCA expor ao paciente ─────────────────────────────

_NUMERO_INTERNO = os.environ.get(
    "NUMERO_INTERNO",
    os.environ.get("BRENO_PHONE", "5531992059211"),
)
_NUMERO_THAYNARA = "5531991394759"

# ── Mensagens ao paciente ─────────────────────────────────────────────────────

_MSG_DUVIDA_CLINICA_PACIENTE = (
    "Aqui é um canal somente para marcação de consultas. "
    "Para dúvidas clínicas, por favor chame a Thaynara no WhatsApp 💚"
)

_MSG_AGUARDANDO_VERIFICACAO = "Só um instante, vou verificar essa informação 💚"

_MSG_TIMEOUT_1H = "Ainda estou verificando, te aviso assim que tiver retorno 💚"

# Mensagem original (mantida por compatibilidade com router.py)
_MSG_PACIENTE_ESCALACAO = (
    "Para dúvidas clínicas, nossa equipe está aqui pra te orientar melhor! 💚\n\n"
    "Vou encaminhar sua mensagem pra Thaynara — ela já foi avisada 😊"
)

# Timeout de espera por resposta humana (em minutos) — legado
TIMEOUT_MINUTOS = 15


# ── Funções auxiliares ────────────────────────────────────────────────────────

def _digits_only(numero: str) -> str:
    return "".join(ch for ch in str(numero or "") if ch.isdigit())


def _sem_nono_digito_brasil(numero: str) -> str:
    digits = _digits_only(numero)
    if digits.startswith("55") and len(digits) == 13 and digits[4] == "9":
        return digits[:4] + digits[5:]
    return digits


def is_numero_interno(numero: str) -> bool:
    """Reconhece o número interno com ou sem nono dígito normalizado pela Meta."""
    recebido = _digits_only(numero)
    interno = _digits_only(_NUMERO_INTERNO)
    return recebido in {interno, _sem_nono_digito_brasil(interno)}

def _em_horario_comercial(agora: datetime | None = None) -> bool:
    """Retorna True se agora está dentro do horário de atendimento (seg–sex, 08h–19h BRT)."""
    agora = agora or datetime.now(BRT)
    if agora.weekday() >= 5:   # sábado=5, domingo=6
        return False
    return 8 <= agora.hour < 19


def build_contexto_escalacao(
    nome_paciente: str | None,
    telefone_paciente: str,
    historico_resumido: str,
    motivo: str,
) -> str:
    """
    Monta a mensagem de contexto enviada ao número interno.
    Não inclui dados sensíveis ao paciente.
    """
    nome = nome_paciente or "Paciente não identificado"
    agora = datetime.now(BRT).strftime("%d/%m/%Y %H:%M")
    return (
        f"🔔 *ESCALAÇÃO — {agora}*\n\n"
        f"*Paciente:* {nome}\n"
        f"*WhatsApp:* {telefone_paciente}\n"
        f"*Motivo:* {motivo}\n\n"
        f"*Resumo da conversa:*\n{historico_resumido}"
    )


def _formatar_tempo(td: timedelta) -> str:
    """Formata timedelta como '15 min', '1h30', '2h', etc."""
    total_segundos = int(td.total_seconds())
    if total_segundos < 0:
        return "0 min"
    minutos = total_segundos // 60
    horas = minutos // 60
    mins_restantes = minutos % 60

    if horas == 0:
        return f"{minutos} min"
    if mins_restantes == 0:
        return f"{horas}h"
    return f"{horas}h{mins_restantes:02d}"


# ── Caminho principal — 3 rotas de escalação ──────────────────────────────────

async def escalar_duvida(
    meta_client,
    telefone_paciente: str,
    phone_hash: str,
    nome_paciente: str | None,
    historico_resumido: str,
    motivo: str,
    is_paciente_cadastrado: bool,
) -> str:
    """
    Roteia escalação para o caminho correto.

    Returns: "contato_thaynara" | "relay_breno"

    D-05: duvida_clinica + cadastrado → VCard Thaynara
    D-06: duvida_clinica + lead → relay Breno
    D-07: outro motivo → relay Breno
    """
    if motivo == "duvida_clinica" and is_paciente_cadastrado:
        # D-05: envia mensagem. Contato da Thaynara NUNCA é enviado automaticamente.
        # Apenas Breno (número interno) pode autorizar o envio do contato ao paciente.
        await meta_client.send_text(telefone_paciente, _MSG_DUVIDA_CLINICA_PACIENTE)
        logger.info(
            "D-05: dúvida clínica recebida de paciente cadastrado %s, encaminhando ao Breno",
            telefone_paciente[-4:],
        )
        # D-05 agora usa relay (não mais direct contact) — vai para D-06/D-07
        is_paciente_cadastrado = False  # força o fluxo de relay abaixo

    # D-06 e D-07: relay para Breno
    await meta_client.send_text(telefone_paciente, _MSG_AGUARDANDO_VERIFICACAO)
    await criar_escalacao_relay(
        meta_client=meta_client,
        phone_hash=phone_hash,
        telefone_paciente=telefone_paciente,
        nome_paciente=nome_paciente,
        historico_resumido=historico_resumido,
        motivo=motivo,
    )
    return "relay_breno"


async def criar_escalacao_relay(
    meta_client,
    phone_hash: str,
    telefone_paciente: str,
    nome_paciente: str | None,
    historico_resumido: str,
    motivo: str,
) -> str:
    """
    Cria PendingEscalation no banco e envia contexto ao Breno.

    Returns: id da escalação criada
    """
    from app.database import SessionLocal
    from app.models import PendingEscalation

    contexto = build_contexto_escalacao(
        nome_paciente, telefone_paciente, historico_resumido, motivo
    )
    now = datetime.now(BRT)
    next_reminder = now + timedelta(minutes=15)

    with SessionLocal() as db:
        esc = PendingEscalation(
            phone_hash=phone_hash,
            phone_e164=telefone_paciente,
            pergunta_original=motivo,
            contexto=contexto,
            status="aguardando",
            next_reminder_at=next_reminder,
            reminder_count=0,
        )
        db.add(esc)
        db.commit()
        esc_id = esc.id

    # Enviar contexto ao Breno (número interno)
    try:
        response = await meta_client.send_text(_NUMERO_INTERNO, contexto)
        message_id = (response.get("messages") or [{}])[0].get("id")
        logger.info(
            "Escalação enviada ao Breno id=%s meta_message_id=%s destino=%s",
            esc_id,
            message_id,
            _NUMERO_INTERNO[-4:],
        )
    except Exception as e:
        logger.exception("Falha ao enviar escalação ao Breno id=%s: %s", esc_id, e)

    logger.info(
        "Escalação relay criada id=%s para paciente=%s",
        esc_id, telefone_paciente[-4:],
    )
    return esc_id


async def processar_resposta_breno(
    meta_client,
    texto_resposta: str,
) -> bool:
    """
    Processa resposta do Breno: encontra PendingEscalation mais recente aguardando,
    marca como respondido, repassa ao paciente, salva FAQ aprendido (D-11).

    Returns: True se escalação foi encontrada e processada, False caso contrário.
    """
    from app.database import SessionLocal
    from app.models import PendingEscalation

    texto_limpo = (texto_resposta or "").strip().lower()
    if texto_limpo in {"abrir janela", "abrir", "/abrir", "ping"}:
        logger.info("Mensagem operacional do Breno recebida para abrir janela; sem relay ao paciente")
        return False

    with SessionLocal() as db:
        esc = (
            db.query(PendingEscalation)
            .filter_by(status="aguardando")
            .order_by(PendingEscalation.created_at.desc())
            .first()
        )
        if not esc:
            logger.warning("Resposta do Breno recebida mas sem escalação pendente")
            return False

        esc.status = "respondido"
        esc.responded_at = datetime.now(BRT)
        esc.resposta_breno = texto_resposta
        telefone_paciente = esc.phone_e164
        pergunta = esc.pergunta_original
        db.commit()

    # Repassar resposta ao paciente
    await meta_client.send_text(telefone_paciente, texto_resposta)
    logger.info("Resposta do Breno repassada ao paciente %s", telefone_paciente[-4:])

    # Salvar FAQ aprendido (D-11)
    try:
        from app.knowledge_base import salvar_faq_aprendido
        salvar_faq_aprendido(pergunta, texto_resposta)
    except Exception as e:
        logger.error("Falha ao salvar FAQ aprendido: %s", e)

    return True


async def enviar_lembretes_pendentes(meta_client) -> int:
    """
    Verifica escalações pendentes e envia lembretes ao Breno + aviso ao paciente.
    Chamado pelo APScheduler a cada 5 minutos.

    Schedule de lembretes (D-09):
    - Primeira hora: a cada 15 min (reminder_count 0..3)
    - Após primeira hora: a cada 1h

    Após 1h sem resposta (D-10): avisa paciente uma vez (quando reminder_count atingir 4).
    """
    from app.database import SessionLocal
    from app.models import PendingEscalation

    now = datetime.now(BRT)
    enviados = 0

    with SessionLocal() as db:
        pendentes = (
            db.query(PendingEscalation)
            .filter_by(status="aguardando")
            .filter(PendingEscalation.next_reminder_at <= now)
            .all()
        )

        for esc in pendentes:
            esc.reminder_count += 1
            tempo_decorrido = now - esc.created_at

            # D-10: após 1h sem resposta (reminder_count == 4), avisa paciente
            if esc.reminder_count == 4:
                try:
                    await meta_client.send_text(esc.phone_e164, _MSG_TIMEOUT_1H)
                except Exception as e:
                    logger.error("Falha ao avisar paciente sobre timeout: %s", e)

            # Define próximo lembrete
            if esc.reminder_count < 4:
                # Primeira hora: a cada 15 min
                esc.next_reminder_at = now + timedelta(minutes=15)
            else:
                # Após primeira hora: a cada 1h
                esc.next_reminder_at = now + timedelta(hours=1)

            # Enviar lembrete ao Breno (número interno)
            lembrete = (
                f"⏰ *LEMBRETE #{esc.reminder_count}* — escalação pendente há "
                f"{_formatar_tempo(tempo_decorrido)}\n\n{esc.contexto}"
            )
            try:
                await meta_client.send_text(_NUMERO_INTERNO, lembrete)
                enviados += 1
            except Exception as e:
                logger.error("Falha ao enviar lembrete ao Breno: %s", e)

            db.commit()

    return enviados


# ── Compatibilidade — função legada usada em router.py ───────────────────────

async def escalar_para_humano(
    meta_client,
    telefone_paciente: str,
    nome_paciente: str | None,
    historico_resumido: str,
    motivo: str = "Dúvida clínica ou solicitação de atendimento humano",
) -> bool:
    """
    Notifica o número interno e envia mensagem de espera ao paciente.
    Mantido por compatibilidade com router.py — usa relay interno.

    Returns: True se as mensagens foram enviadas com sucesso.
    """
    em_horario = _em_horario_comercial()

    # 1. Avisa o paciente
    try:
        await meta_client.send_text(telefone_paciente, _MSG_PACIENTE_ESCALACAO)
    except Exception as e:
        logger.error("Falha ao enviar msg de escalação ao paciente %s: %s", telefone_paciente[-4:], e)

    # 2. Envia contexto para número interno
    contexto = build_contexto_escalacao(
        nome_paciente, telefone_paciente, historico_resumido, motivo
    )

    prefixo = "" if em_horario else "⏳ *FORA DO HORÁRIO — responder ao retornar:*\n\n"
    try:
        await meta_client.send_text(_NUMERO_INTERNO, prefixo + contexto)
        logger.info(
            "Escalação enviada ao número interno (paciente=%s, motivo=%s)",
            telefone_paciente[-4:], motivo,
        )
        return True
    except Exception as e:
        logger.error("Falha ao enviar escalação ao número interno: %s", e)
        return False
