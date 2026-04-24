"""
State — estado persistente da conversa como dict simples.

Funções de módulo:
  init_state_manager(redis_url) — chamado no lifespan
  load_state(phone_hash)        — carrega do Redis ou cria novo
  save_state(phone_hash, state) — persiste no Redis
  delete_state(phone_hash)      — remove do Redis (fim do fluxo)

Helpers de mutação:
  apply_turno_updates(state, turno)      — aplica campos extraídos ao collected_data
  apply_correction(state, campo, valor)  — aplica correção com invalidações em cascata
  apply_tool_result(state, tool, result) — incorpora resultado de tool no estado
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_state_mgr = None   # RedisStateManager — inicializado via init_state_manager()
_mem_store: dict[str, str] = {}  # fallback in-memory quando Redis não está disponível

_KEY_PREFIX = "conv_state:"


# ── Inicialização ─────────────────────────────────────────────────────────────


def init_state_manager(redis_url: str) -> None:
    """Inicializa a conexão com Redis. Chamado no lifespan do FastAPI."""
    global _state_mgr
    import redis.asyncio as aioredis
    _state_mgr = aioredis.Redis.from_url(redis_url, decode_responses=True)
    logger.info("ConversationState Redis inicializado: %s", redis_url)


# ── Estado inicial ────────────────────────────────────────────────────────────


def create_state(phone_hash: str, phone: str) -> dict:
    """Cria um estado de conversa vazio."""
    return {
        "_tipo": "conversation",
        "phone_hash": phone_hash,
        "phone": phone,
        "goal": "desconhecido",
        # "agendar_consulta" | "remarcar" | "cancelar" | "duvida" | "desconhecido"
        "status": "coletando",
        # "coletando" | "aguardando_pagamento" | "concluido"
        "collected_data": {
            "nome": None,
            "status_paciente": None,   # "novo" | "retorno"
            "objetivo": None,
            "plano": None,             # "premium" | "ouro" | "com_retorno" | "unica" | "formulario"
            "modalidade": None,        # "presencial" | "online"
            "preferencia_horario": None,  # dict com tipo/turno/hora/dia_semana/descricao
            "forma_pagamento": None,   # "pix" | "cartao"
            "data_nascimento": None,
            "email": None,
            "instagram": None,
            "profissao": None,
            "cep_endereco": None,
            "indicacao_origem": None,
            "motivo_cancelamento": None,
        },
        "appointment": {
            "slot_escolhido": None,
            "id_paciente": None,
            "id_agenda": None,
            "id_transacao": None,
            "consulta_atual": None,    # agendamento existente encontrado no Dietbox
        },
        "flags": {
            "upsell_oferecido": False,
            "planos_enviados": False,
            "pagamento_confirmado": False,
            "aguardando_motivo_cancel": False,
        },
        "last_action": None,
        "last_slots_offered": [],
        "slots_pool": [],
        "rodada_negociacao": 0,
        "tipo_remarcacao": None,       # "retorno" | "nova_consulta"
        "fim_janela_remarcar": None,   # ISO date string
        "link_pagamento": None,        # {"url", "parcelas", "parcela_valor"}
        "history": [],                 # [{role, content}] — max 20
    }


# ── Persistência ──────────────────────────────────────────────────────────────


async def load_state(phone_hash: str, phone: str = "") -> dict:
    """
    Carrega estado do Redis. Fallback para in-memory se Redis indisponível ou falhar.
    Retorna estado vazio se não encontrado.
    """
    key = f"{_KEY_PREFIX}{phone_hash}"
    if _state_mgr is not None:
        try:
            raw = await _state_mgr.get(key)
            if raw:
                return json.loads(raw)
            # Redis respondeu mas key não existe — checar _mem_store antes de criar novo estado
        except Exception as e:
            logger.warning("Redis load failed, usando fallback in-memory: %s", e)
    # fallback in-memory (sem Redis, key não encontrada no Redis, ou falha)
    raw = _mem_store.get(key)
    if raw:
        return json.loads(raw)
    return create_state(phone_hash, phone)


async def save_state(phone_hash: str, state: dict) -> None:
    """Persiste estado no Redis. Fallback para in-memory se Redis indisponível ou falhar."""
    key = f"{_KEY_PREFIX}{phone_hash}"
    serialized = json.dumps(state, ensure_ascii=False, default=str)
    if _state_mgr is not None:
        try:
            await _state_mgr.set(key, serialized)
            return
        except Exception as e:
            logger.warning("Redis save failed, usando fallback in-memory: %s", e)
    _mem_store[key] = serialized


async def delete_state(phone_hash: str) -> None:
    """Remove estado do Redis (e in-memory) quando status == 'concluido'."""
    key = f"{_KEY_PREFIX}{phone_hash}"
    _mem_store.pop(key, None)
    if _state_mgr is None:
        return
    try:
        await _state_mgr.delete(key)
    except Exception as e:
        logger.warning("Redis delete failed: %s", e)


# ── Helpers de mutação ────────────────────────────────────────────────────────


def add_message(state: dict, role: str, content: str | dict) -> None:
    """Adiciona mensagem ao histórico (max 20 entradas)."""
    content_str = content if isinstance(content, str) else "[mídia]"
    state["history"].append({"role": role, "content": content_str})
    if len(state["history"]) > 20:
        state["history"] = state["history"][-20:]


def apply_turno_updates(state: dict, turno: dict) -> None:
    """
    Aplica campos não-nulos extraídos pelo interpreter ao collected_data.
    Nunca sobrescreve um valor existente com None.
    """
    cd = state["collected_data"]
    for campo in (
        "nome", "status_paciente", "objetivo", "plano", "modalidade",
        "forma_pagamento", "preferencia_horario", "data_nascimento", "email",
        "instagram", "profissao", "cep_endereco", "indicacao_origem",
    ):
        valor = turno.get(campo)
        if valor is not None:
            cd[campo] = valor


def apply_correction(state: dict, campo: str, valor_novo) -> None:
    """
    Aplica correção declarada pelo paciente.
    Invalida estado dependente para forçar re-execução das etapas afetadas.
    """
    cd = state["collected_data"]

    if campo == "preferencia_horario":
        cd["preferencia_horario"] = valor_novo if isinstance(valor_novo, dict) else None
        state["last_slots_offered"] = []
        state["slots_pool"] = []
        state["appointment"]["slot_escolhido"] = None
        logger.info("Correção horário aplicada: %s", valor_novo)

    elif campo == "plano":
        cd["plano"] = str(valor_novo)
        state["flags"]["upsell_oferecido"] = False
        state["last_slots_offered"] = []
        state["appointment"]["slot_escolhido"] = None
        logger.info("Correção plano aplicada: %s", valor_novo)

    elif campo == "modalidade":
        cd["modalidade"] = str(valor_novo)
        state["last_slots_offered"] = []
        state["appointment"]["slot_escolhido"] = None
        logger.info("Correção modalidade aplicada: %s", valor_novo)

    elif campo == "forma_pagamento":
        cd["forma_pagamento"] = str(valor_novo)
        state["link_pagamento"] = None
        logger.info("Correção forma pagamento aplicada: %s", valor_novo)


def apply_tool_result(state: dict, tool: str, result: dict) -> None:
    """Incorpora resultado de uma tool call no estado."""
    if not result:
        return

    appt = state["appointment"]

    if "slots" in result:
        state["last_slots_offered"] = result["slots"][:3]
        state["slots_pool"] = result.get("slots_pool", result["slots"])

    if "slot_escolhido" in result:
        appt["slot_escolhido"] = result["slot_escolhido"]

    if "id_paciente" in result:
        appt["id_paciente"] = result["id_paciente"]

    if "id_agenda" in result:
        appt["id_agenda"] = result["id_agenda"]

    if "id_transacao" in result:
        appt["id_transacao"] = result["id_transacao"]

    if "consulta_atual" in result:
        appt["consulta_atual"] = result["consulta_atual"]
        if result["consulta_atual"]:
            appt["id_agenda"] = result["consulta_atual"].get("id")

    if "fim_janela" in result:
        state["fim_janela_remarcar"] = result["fim_janela"]

    if "tipo_remarcacao" in result:
        state["tipo_remarcacao"] = result["tipo_remarcacao"]
        if result["tipo_remarcacao"] == "nova_consulta":
            state["goal"] = "agendar_consulta"
            state["collected_data"]["status_paciente"] = "novo"
            appt["consulta_atual"] = None
            appt["id_agenda"] = None

    if "link_url" in result:
        state["link_pagamento"] = {
            "url": result["link_url"],
            "parcelas": result.get("parcelas"),
            "parcela_valor": result.get("parcela_valor"),
        }
