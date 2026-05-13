"""
Processador de comandos internos — Fluxo 8.

Detecta mensagens vindas de números autorizados (Thaynara / Breno),
interpreta o comando via Gemini e executa a ação correspondente.

Fluxo:
    1. _numero_autorizado() verifica o telefone do remetente
    2. interpretar_comando() (LLM) extrai comando + parâmetros
    3. _executar_comando() roteia para o handler específico
    4. Retorna ComandoResult com mensagens para enviar DE VOLTA ao operador

Todos os handlers que enviam mensagem ao paciente usam a Meta API diretamente,
independente do fluxo normal do orchestrator.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.conversation.config_loader import config
from app.conversation.models import Mensagem
from app.conversation.tools.registry import call_tool

logger = logging.getLogger(__name__)

_AJUDA_COMANDOS = (
    "Comandos disponíveis:\n"
    "• *status [nome ou telefone do paciente]*\n"
    "• *troca de horário para [nome/telefone]*\n"
    "• *cancelar consulta de [nome/telefone]*\n"
    "• *remarcar consulta de [nome/telefone]*\n"
    "• *responder escalação [id]: [sua resposta]*\n"
    "• *mensagem para [nome/telefone]: [texto]*"
)


@dataclass
class ComandoResult:
    processado: bool
    mensagens: list[Mensagem] = field(default_factory=list)
    proximo_estado: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Detecção de número autorizado
# ─────────────────────────────────────────────────────────────────────────────

def _numero_autorizado(phone: str) -> dict[str, Any] | None:
    """Retorna config do número se autorizado para comandos, None caso contrário."""
    try:
        numeros = config.global_config.numeros
        phone_digits = "".join(c for c in phone if c.isdigit())
        for nome, cfg in numeros.items():
            if not cfg.get("pode_dar_comandos"):
                continue
            cfg_phone = "".join(c for c in str(cfg.get("phone", "")) if c.isdigit())
            if not cfg_phone:
                continue
            # Compara sufixo de 11 dígitos (DDD + número) para tolerar DDI variante
            if phone_digits.endswith(cfg_phone[-11:]) or cfg_phone.endswith(phone_digits[-11:]):
                return {"nome": nome, **{k: v for k, v in cfg.items()}}
    except Exception as exc:
        logger.warning("Erro ao verificar número autorizado: %s", exc)
    return None


def _texto_mensagem(mensagem: dict[str, Any]) -> str:
    if isinstance(mensagem.get("text"), str):
        return mensagem["text"]
    if isinstance(mensagem.get("text"), dict):
        return str(mensagem["text"].get("body") or "")
    return str(mensagem.get("body") or mensagem.get("content") or "")


# ─────────────────────────────────────────────────────────────────────────────
# Handlers de cada comando
# ─────────────────────────────────────────────────────────────────────────────

async def _cmd_consultar_status(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Retorna resumo do estado atual de um paciente."""
    telefone = str(params.get("telefone_paciente") or params.get("telefone") or "").strip()
    nome = str(params.get("nome_paciente") or params.get("nome") or "").strip()

    if not telefone and not nome:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso do nome ou telefone do paciente para consultar o status.")],
        )

    try:
        import hashlib
        from app.conversation_legacy.state import load_state

        if telefone:
            phone_hash = hashlib.sha256(telefone.encode()).hexdigest()[:64]
            state = await load_state(phone_hash, telefone)
        else:
            return ComandoResult(
                processado=True,
                mensagens=[Mensagem(tipo="texto", conteudo=f"Busca por nome ainda não suportada. Use o telefone do paciente.")],
            )

        if not state:
            return ComandoResult(
                processado=True,
                mensagens=[Mensagem(tipo="texto", conteudo=f"Nenhuma conversa ativa encontrada para {telefone}.")],
            )

        cd = state.get("collected_data") or {}
        apt = state.get("appointment") or {}
        flags = state.get("flags") or {}
        resumo = (
            f"*Status do paciente {cd.get('nome') or telefone}*\n\n"
            f"Estado: {state.get('estado') or 'desconhecido'}\n"
            f"Fluxo: {state.get('fluxo_id') or '-'}\n"
            f"Plano: {cd.get('plano') or '-'}\n"
            f"Modalidade: {cd.get('modalidade') or '-'}\n"
            f"Slot escolhido: {(apt.get('slot_escolhido') or {}).get('data_fmt') or '-'}\n"
            f"Pagamento confirmado: {'Sim' if flags.get('pagamento_confirmado') else 'Não'}\n"
            f"Fora de contexto (count): {state.get('fora_contexto_count') or 0}"
        )
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=resumo)],
        )
    except Exception as exc:
        logger.exception("Erro ao consultar status do paciente: %s", exc)
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Erro ao buscar status: {exc}")],
        )


async def _cmd_perguntar_troca(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Envia mensagem ao paciente perguntando se pode trocar de horário."""
    telefone = str(params.get("telefone_paciente") or params.get("telefone") or "").strip()

    if not telefone:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso do telefone do paciente para perguntar sobre troca de horário.")],
        )

    msg_paciente = (
        "Oi! A Thaynara precisa fazer uma alteração na agenda e gostaria de saber se você consegue "
        "trocar o horário da sua consulta. Tem algum dia e horário de sua preferência?"
    )
    sucesso = await _enviar_para_paciente(telefone, msg_paciente)
    if sucesso:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Mensagem de troca de horário enviada para {telefone}.")],
        )
    return ComandoResult(
        processado=True,
        mensagens=[Mensagem(tipo="texto", conteudo=f"Falha ao enviar mensagem para {telefone}. Verifique o número.")],
    )


async def _cmd_cancelar(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Instrui o paciente a contatar para cancelamento ou executa via tool."""
    telefone = str(params.get("telefone_paciente") or params.get("telefone") or "").strip()
    motivo = str(params.get("motivo") or "solicitado pela clínica").strip()

    if not telefone:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso do telefone do paciente para cancelar a consulta.")],
        )

    try:
        result = await call_tool("detectar_tipo_remarcacao", {"telefone": telefone, "identificador": None})
        dados = result.dados if result.sucesso else {}
        consulta = dados.get("consulta_atual") or {}
        id_agenda = consulta.get("id") or consulta.get("id_agenda")

        if not id_agenda:
            return ComandoResult(
                processado=True,
                mensagens=[Mensagem(tipo="texto", conteudo=f"Nenhuma consulta ativa encontrada para {telefone}.")],
            )

        cancel_result = await call_tool("cancelar_dietbox", {"id_agenda": id_agenda})
        if cancel_result.sucesso:
            msg_paciente = "Olá! Precisamos cancelar sua consulta agendada. Em breve a equipe entrará em contato para reagendar."
            await _enviar_para_paciente(telefone, msg_paciente)
            return ComandoResult(
                processado=True,
                mensagens=[Mensagem(tipo="texto", conteudo=f"Consulta de {telefone} cancelada. Paciente foi notificado.")],
            )
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Erro ao cancelar no Dietbox: {cancel_result.erro}")],
        )
    except Exception as exc:
        logger.exception("Erro ao cancelar consulta via comando: %s", exc)
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Erro interno ao cancelar: {exc}")],
        )


async def _cmd_remarcar(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Inicia fluxo de remarcação com o paciente."""
    telefone = str(params.get("telefone_paciente") or params.get("telefone") or "").strip()

    if not telefone:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso do telefone do paciente para remarcar.")],
        )

    msg_paciente = (
        "Oi! A Thaynara precisa remarcar sua consulta. "
        "Qual dia e horário funcionam melhor pra você?"
    )
    sucesso = await _enviar_para_paciente(telefone, msg_paciente)

    # Ativa o fluxo de remarcação no estado do paciente
    try:
        import hashlib
        from app.conversation_legacy.state import load_state, save_state

        phone_hash = hashlib.sha256(telefone.encode()).hexdigest()[:64]
        state = await load_state(phone_hash, telefone)
        if state:
            state["fluxo_id"] = "remarcacao"
            state["estado"] = "remarcacao_oferecendo_seguranca"
            await save_state(phone_hash, state)
    except Exception as exc:
        logger.warning("Não conseguiu ativar fluxo de remarcação no estado do paciente: %s", exc)

    if sucesso:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Mensagem de remarcação enviada para {telefone}. Fluxo ativado.")],
        )
    return ComandoResult(
        processado=True,
        mensagens=[Mensagem(tipo="texto", conteudo=f"Falha ao enviar mensagem para {telefone}.")],
    )


async def _cmd_responder_escalacao(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Encaminha a resposta do operador para o paciente que fez a escalação."""
    from app.conversation.tools.notifications import _ESCALACOES_PENDENTES

    escalacao_id = str(params.get("escalacao_id") or "").strip()
    resposta = str(params.get("resposta") or params.get("mensagem") or "").strip()

    if not resposta:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso da resposta para encaminhar ao paciente. Use: 'responder escalação [id]: [sua resposta]'")],
        )

    # Tenta localizar a escalação
    escalacao = None
    if escalacao_id and escalacao_id in _ESCALACOES_PENDENTES:
        escalacao = _ESCALACOES_PENDENTES[escalacao_id]
    elif not escalacao_id:
        # Pega a mais recente pendente
        pendentes = [e for e in _ESCALACOES_PENDENTES.values() if e.get("status") == "pendente"]
        if pendentes:
            escalacao = sorted(pendentes, key=lambda e: e.get("criado_em", ""), reverse=True)[0]
            escalacao_id = escalacao["id"]

    if not escalacao:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Escalação '{escalacao_id}' não encontrada ou já resolvida.")],
        )

    contexto = escalacao.get("contexto") or {}
    state_escala = contexto.get("state") or {}
    telefone_paciente = state_escala.get("phone") or str(contexto.get("telefone") or "").strip()

    if not telefone_paciente:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Não encontrei o telefone do paciente na escalação {escalacao_id}.")],
        )

    sucesso = await _enviar_para_paciente(telefone_paciente, resposta)
    if sucesso:
        _ESCALACOES_PENDENTES[escalacao_id]["status"] = "resolvida"
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Resposta enviada para o paciente ({telefone_paciente}). Escalação {escalacao_id} resolvida.")],
        )
    return ComandoResult(
        processado=True,
        mensagens=[Mensagem(tipo="texto", conteudo=f"Falha ao enviar resposta para o paciente {telefone_paciente}.")],
    )


async def _cmd_enviar_mensagem(params: dict[str, Any], operador: dict[str, Any]) -> ComandoResult:
    """Envia mensagem livre para o paciente."""
    telefone = str(params.get("telefone_paciente") or params.get("telefone") or "").strip()
    mensagem_texto = str(params.get("mensagem") or params.get("texto") or "").strip()

    if not telefone or not mensagem_texto:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Preciso do telefone e da mensagem. Use: 'mensagem para [telefone]: [texto]'")],
        )

    sucesso = await _enviar_para_paciente(telefone, mensagem_texto)
    if sucesso:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Mensagem enviada para {telefone}.")],
        )
    return ComandoResult(
        processado=True,
        mensagens=[Mensagem(tipo="texto", conteudo=f"Falha ao enviar mensagem para {telefone}.")],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _enviar_para_paciente(telefone: str, texto: str) -> bool:
    """Envia texto diretamente ao paciente via Meta API. Retorna True se enviou."""
    try:
        from app.meta_api import MetaAPIClient
        client = MetaAPIClient()
        await client.send_text(to=telefone, text=texto)
        return True
    except Exception as exc:
        logger.exception("Erro ao enviar mensagem para paciente %s: %s", telefone, exc)
        return False


async def _executar_comando(
    comando: str,
    params: dict[str, Any],
    confidence: float,
    state: dict[str, Any],
    phone: str,
    operador: dict[str, Any],
) -> ComandoResult:
    if comando == "nao_reconhecido" or confidence < 0.3:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Não entendi o comando.\n\n{_AJUDA_COMANDOS}")],
        )

    handlers = {
        "consultar_status_paciente": _cmd_consultar_status,
        "perguntar_paciente_troca_horario": _cmd_perguntar_troca,
        "cancelar_consulta": _cmd_cancelar,
        "remarcar_consulta": _cmd_remarcar,
        "responder_escalacao": _cmd_responder_escalacao,
        "enviar_mensagem_para_paciente": _cmd_enviar_mensagem,
    }

    handler = handlers.get(comando)
    if handler is None:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo=f"Comando '{comando}' não implementado.\n\n{_AJUDA_COMANDOS}")],
        )

    return await handler(params, operador)


# ─────────────────────────────────────────────────────────────────────────────
# Ponto de entrada público
# ─────────────────────────────────────────────────────────────────────────────

async def processar_comando_interno(
    phone: str,
    mensagem: dict[str, Any],
    state: dict[str, Any],
) -> ComandoResult:
    """
    Tenta processar como comando interno.

    Retorna ComandoResult(processado=False) quando:
    - O número não é autorizado
    - A mensagem está vazia

    Retorna ComandoResult(processado=True) com mensagens para enviar ao operador
    quando o comando é reconhecido (mesmo que com erro de execução).
    """
    operador = _numero_autorizado(phone)
    if operador is None:
        return ComandoResult(processado=False)

    texto = _texto_mensagem(mensagem)
    if not texto.strip():
        return ComandoResult(processado=False)

    logger.info("Comando interno de %s (%s): %r", operador["nome"], phone, texto[:80])

    result = await call_tool("interpretar_comando", {"texto": texto, "remetente": operador["nome"]})
    if not result.sucesso:
        return ComandoResult(
            processado=True,
            mensagens=[Mensagem(tipo="texto", conteudo="Erro ao interpretar comando. Tente novamente.")],
        )

    dados = result.dados or {}
    comando = str(dados.get("comando_identificado") or "nao_reconhecido")
    params = dict(dados.get("parametros_extraidos") or {})
    confidence = float(dados.get("confidence") or 0.0)

    logger.info("Comando interpretado: %s (conf=%.2f) params=%s", comando, confidence, params)

    return await _executar_comando(comando, params, confidence, state, phone, operador)
