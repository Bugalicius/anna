"""
Planner — decide a próxima ação a partir do turno e do estado.

Função pública:
  decidir_acao(turno, state) -> dict  (plano)

O plano retornado tem a estrutura:
  {
    "action":      str,          # o que fazer
    "tool":        str | None,   # tool a executar (se action == "execute_tool")
    "params":      dict,         # parâmetros da tool
    "update_data": dict,         # updates para collected_data (via _atualizar_estado)
    "new_status":  str | None,   # novo status do estado
    "ask_context": any,          # contexto para o Responder (campo pedido, plano, etc.)
    "meta":        dict,         # dados auxiliares para transições no Engine
  }

Sem side-effects: apenas lê turno + state e retorna um plano.
As mutações de estado são responsabilidade do Engine.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── Constantes de ação ────────────────────────────────────────────────────────

ASK_FIELD            = "ask_field"
SEND_PLANOS          = "send_planos"
OFFER_UPSELL         = "offer_upsell"
APPLY_UPGRADE        = "apply_upgrade"        # Engine aplica upgrade e re-planeja
SLOT_CONFIRMED       = "slot_confirmed"        # Engine salva slot e re-planeja
PAGAMENTO_CONFIRMADO = "pagamento_confirmado"  # Engine seta flag e re-planeja
ASK_SLOT_CHOICE      = "ask_slot_choice"
ASK_FORMA_PAGAMENTO  = "ask_forma_pagamento"
AWAIT_PAYMENT        = "await_payment"
ANSWER_QUESTION      = "answer_question"
ANSWER_FREE          = "answer_free"
ESCALATE             = "escalate"
REMARKETING_RECUSA   = "handle_remarketing_refusal"
FORA_DE_CONTEXTO     = "respond_fora_de_contexto"
REDIRECT_RETENCAO    = "redirect_retencao"     # Engine muda goal e re-planeja
REDIRECT_ATENDIMENTO = "redirect_atendimento"  # Engine muda goal e re-planeja
EXECUTE_TOOL         = "execute_tool"
SEND_FORMULARIO      = "send_formulario_instrucoes"
ASK_MOTIVO_CANCEL    = "ask_motivo_cancelamento"
SEND_CONFIRMACAO     = "send_confirmacao"
SEND_CONFIRMACAO_REMARCAR = "send_confirmacao_remarcacao"
SEND_CONFIRMACAO_CANCEL   = "send_confirmacao_cancelamento"

# Mapa de upsell
_UPSELL_MAP = {"unica": "ouro", "com_retorno": "ouro", "ouro": "premium"}

# Intent → goal
_INTENT_TO_GOAL = {
    "agendar":            "agendar_consulta",
    "remarcar":           "remarcar",
    "cancelar":           "cancelar",
    "tirar_duvida":       "duvida",
    "confirmar_pagamento": "agendar_consulta",
    "duvida_clinica":     "duvida_clinica",
    "recusou_remarketing": "recusou_remarketing",
}


# ── Função pública ─────────────────────────────────────────────────────────────


async def decidir_acao(turno: dict, state: dict) -> dict:
    """
    Dado o turno interpretado e o estado atual, decide a próxima ação.

    Chamado repetidamente pelo Engine após mutações de estado intermediárias
    (ex: aplicar upgrade, confirmar slot, confirmar pagamento).
    """
    # 1. Dúvida clínica / escalação — sempre prioridade
    if turno.get("intent") == "duvida_clinica" or (
        turno.get("tem_pergunta") and turno.get("topico_pergunta") == "clinica"
    ):
        return _plano(ESCALATE)

    # 2. Recusa de remarketing
    if turno.get("intent") == "recusou_remarketing":
        return _plano(REMARKETING_RECUSA)

    # 3. Pergunta informativa respondível inline (apenas fora de momentos críticos)
    if (
        turno.get("tem_pergunta")
        and turno.get("topico_pergunta") in ("pagamento", "planos", "modalidade", "politica")
        and not _momento_critico(state)
    ):
        return _plano(ANSWER_QUESTION, ask_context=turno["topico_pergunta"])

    # 4. Resolve o goal efetivo
    goal = _resolve_goal(state, turno)

    # 5. Roteamento por goal
    if goal == "agendar_consulta":
        return _plan_agendar(state, turno)
    if goal == "remarcar":
        return _plan_remarcar(state, turno)
    if goal == "cancelar":
        return _plan_cancelar(state, turno)
    if goal == "duvida":
        return _plano(ANSWER_FREE)

    return _plano(FORA_DE_CONTEXTO)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _plano(action: str, tool=None, params=None, update_data=None,
           new_status=None, ask_context=None, meta=None) -> dict:
    return {
        "action":      action,
        "tool":        tool,
        "params":      params or {},
        "update_data": update_data or {},
        "new_status":  new_status,
        "ask_context": ask_context,
        "meta":        meta or {},
    }


def _resolve_goal(state: dict, turno: dict) -> str:
    current = state.get("goal", "desconhecido")
    intent = turno.get("intent", "fora_de_contexto")
    new_goal = _INTENT_TO_GOAL.get(intent)
    if new_goal:
        return new_goal
    return current if current != "desconhecido" else "desconhecido"


def _momento_critico(state: dict) -> bool:
    """Momentos em que perguntas inline não devem interromper o fluxo."""
    cd = state["collected_data"]
    return (
        not cd["nome"]
        or (state["last_slots_offered"] and not state["appointment"]["slot_escolhido"])
        or state.get("status") == "aguardando_pagamento"
    )


# ── Fluxo de agendamento ──────────────────────────────────────────────────────


def _plan_agendar(state: dict, turno: dict) -> dict:
    cd = state["collected_data"]
    flags = state["flags"]
    appt = state["appointment"]

    if not cd["nome"]:
        return _plano(ASK_FIELD, ask_context="nome")

    if cd.get("status_paciente") == "retorno":
        return _plano(REDIRECT_RETENCAO)

    if not cd["plano"] and not flags["planos_enviados"]:
        return _plano(SEND_PLANOS)

    if not cd["plano"]:
        return _plano(ASK_FIELD, ask_context="plano")

    if cd["plano"] == "formulario":
        return _plan_formulario(state, turno)

    if not cd["modalidade"]:
        return _plano(ASK_FIELD, ask_context="modalidade")

    # Upsell (uma vez por plano elegível)
    if cd["plano"] in _UPSELL_MAP and not flags["upsell_oferecido"]:
        if turno.get("aceita_upgrade") is True:
            return _plano(APPLY_UPGRADE, meta={"plano_upgrade": _UPSELL_MAP[cd["plano"]]})
        return _plano(OFFER_UPSELL, ask_context=cd["plano"])

    # Resposta a upsell já oferecido
    if flags["upsell_oferecido"] and cd["plano"] in _UPSELL_MAP and turno.get("aceita_upgrade") is True:
        return _plano(APPLY_UPGRADE, meta={"plano_upgrade": _UPSELL_MAP[cd["plano"]]})

    # Preferência de horário
    if not cd["preferencia_horario"] and not state["last_slots_offered"] and not turno.get("preferencia_horario"):
        return _plano(ASK_FIELD, ask_context="preferencia_horario")

    # Busca de slots
    pref = cd["preferencia_horario"] or turno.get("preferencia_horario")
    if not state["last_slots_offered"]:
        return _plano(EXECUTE_TOOL, tool="consultar_slots",
                      params={"modalidade": cd["modalidade"], "preferencia": pref})

    # Nova preferência expressa com slots já carregados → re-busca
    if turno.get("preferencia_horario") and not turno.get("escolha_slot") and not appt["slot_escolhido"]:
        return _plano(EXECUTE_TOOL, tool="consultar_slots",
                      params={"modalidade": cd["modalidade"],
                               "preferencia": turno["preferencia_horario"]})

    # Escolha de slot
    if not appt["slot_escolhido"]:
        idx = turno.get("escolha_slot")
        if idx and 1 <= idx <= len(state["last_slots_offered"]):
            return _plano(SLOT_CONFIRMED, ask_context=idx - 1)
        return _plano(ASK_SLOT_CHOICE)

    # Forma de pagamento
    if not cd["forma_pagamento"]:
        return _plano(ASK_FORMA_PAGAMENTO)

    # Cartão → gerar link (uma única vez)
    if cd["forma_pagamento"] == "cartao" and state.get("last_action") != "gerar_link_cartao":
        return _plano(EXECUTE_TOOL, tool="gerar_link_cartao",
                      params={"plano": cd["plano"], "modalidade": cd["modalidade"],
                               "phone_hash": state["phone_hash"]})

    # Aguarda pagamento
    if not flags["pagamento_confirmado"]:
        if turno.get("confirmou_pagamento"):
            return _plano(PAGAMENTO_CONFIRMADO)
        return _plano(AWAIT_PAYMENT, new_status="aguardando_pagamento")

    # Agenda no Dietbox
    if not appt["id_agenda"]:
        return _plano(EXECUTE_TOOL, tool="agendar",
                      params={"nome": cd["nome"], "telefone": state["phone"],
                               "plano": cd["plano"], "modalidade": cd["modalidade"],
                               "slot": appt["slot_escolhido"],
                               "forma_pagamento": cd["forma_pagamento"]})

    return _plano(SEND_CONFIRMACAO, new_status="concluido")


def _plan_formulario(state: dict, turno: dict) -> dict:
    flags = state["flags"]
    if state.get("status") != "aguardando_pagamento":
        return _plano(SEND_FORMULARIO, new_status="aguardando_pagamento")
    if turno.get("confirmou_pagamento"):
        return _plano(PAGAMENTO_CONFIRMADO)
    return _plano(AWAIT_PAYMENT)


# ── Fluxo de remarcação ───────────────────────────────────────────────────────


def _plan_remarcar(state: dict, turno: dict) -> dict:
    cd = state["collected_data"]
    appt = state["appointment"]

    if not cd["nome"]:
        return _plano(ASK_FIELD, ask_context="nome")

    if not state.get("tipo_remarcacao"):
        return _plano(EXECUTE_TOOL, tool="detectar_tipo_remarcacao",
                      params={"telefone": state["phone"]})

    if state["tipo_remarcacao"] == "nova_consulta":
        return _plano(REDIRECT_ATENDIMENTO)

    # Tipo "retorno": busca slots dentro da janela
    if not state["last_slots_offered"]:
        pref = cd["preferencia_horario"] or turno.get("preferencia_horario")
        if not pref:
            return _plano(ASK_FIELD, ask_context="preferencia_horario_remarcar")
        return _plano(EXECUTE_TOOL, tool="consultar_slots_remarcar",
                      params={"modalidade": cd.get("modalidade") or "presencial",
                               "preferencia": pref,
                               "fim_janela": state.get("fim_janela_remarcar"),
                               "excluir": []})

    if not appt["slot_escolhido"]:
        # Quer outras opções
        if turno.get("preferencia_horario") and not turno.get("escolha_slot"):
            excluir = [s["datetime"] for s in state["last_slots_offered"]]
            pool_restante = [s for s in state["slots_pool"] if s["datetime"] not in set(excluir)]
            if not pool_restante or state.get("rodada_negociacao", 0) >= 1:
                return _plano(EXECUTE_TOOL, tool="perda_retorno")
            return _plano(EXECUTE_TOOL, tool="consultar_slots_remarcar",
                          params={"modalidade": cd.get("modalidade") or "presencial",
                                   "preferencia": turno["preferencia_horario"],
                                   "fim_janela": state.get("fim_janela_remarcar"),
                                   "excluir": excluir,
                                   "pool": state["slots_pool"]})
        idx = turno.get("escolha_slot")
        if idx and 1 <= idx <= len(state["last_slots_offered"]):
            return _plano(SLOT_CONFIRMED, ask_context=idx - 1)
        return _plano(ASK_SLOT_CHOICE)

    if state.get("last_action") != "remarcar_dietbox":
        return _plano(EXECUTE_TOOL, tool="remarcar_dietbox",
                      params={"id_agenda_original": appt["id_agenda"],
                               "novo_slot": appt["slot_escolhido"],
                               "consulta_atual": appt.get("consulta_atual")})

    return _plano(SEND_CONFIRMACAO_REMARCAR, new_status="concluido")


# ── Fluxo de cancelamento ─────────────────────────────────────────────────────


def _plan_cancelar(state: dict, turno: dict) -> dict:
    cd = state["collected_data"]
    flags = state["flags"]

    if not cd["nome"]:
        return _plano(ASK_FIELD, ask_context="nome")

    if not flags["aguardando_motivo_cancel"]:
        return _plano(ASK_MOTIVO_CANCEL)

    if state.get("last_action") != "cancelar_dietbox":
        return _plano(EXECUTE_TOOL, tool="cancelar",
                      params={"telefone": state["phone"],
                               "motivo": cd.get("motivo_cancelamento") or "Não informado"})

    return _plano(SEND_CONFIRMACAO_CANCEL, new_status="concluido")
