"""
ConversationEngine — motor central de conversação.

Fluxo linear por turno:
  1. Carrega estado
  2. Interpreta turno (LLM — interpreter)
  3. Aplica extrações ao estado
  4. Decide ação (LLM — planner)
  5. Aplica mutações de estado declaradas pelo planner
  6. Executa tool (se houver)
  7. Gera resposta
  8. Persiste estado

O Planner LLM decide tudo em um único passo — sem loop de re-planejamento.
"""
from __future__ import annotations

import logging

from app.conversation.state import (
    add_message,
    apply_correction,
    apply_tool_result,
    apply_turno_updates,
    load_state,
    save_state,
)
from app.conversation.interpreter import interpretar_turno
from app.conversation.planner import decidir_acao
from app.conversation.responder import gerar_resposta

logger = logging.getLogger(__name__)


class ConversationEngine:
    """
    Motor central de conversação — stateless entre chamadas.
    Uma instância global é suficiente.
    """

    async def handle_message(self, phone_hash: str, message: str, phone: str = "") -> list:
        """
        Processa uma mensagem e retorna lista de respostas.

        phone_hash: hash do telefone (LGPD — nunca o número real)
        message:    texto recebido do paciente
        phone:      número real (necessário para tools Dietbox/Rede)
        """
        # 1. Carregar estado
        state = await load_state(phone_hash, phone)
        add_message(state, "user", message)

        # 2. Interpretar turno (LLM)
        turno = await interpretar_turno(message, state)
        turno["_raw_message"] = message  # Disponível para heurísticas do planner

        # 3. Aplicar extrações e correções ao estado
        apply_turno_updates(state, turno)
        if turno.get("correcao"):
            c = turno["correcao"]
            apply_correction(state, c["campo"], c["valor_novo"])

        # 4. Atualizar goal para persistência entre turnos
        self._atualizar_goal(state, turno)

        # 5. Decidir ação (LLM — planner)
        plano = await decidir_acao(turno, state)

        # 6. Aplicar mutações de estado declaradas pelo planner
        self._aplicar_mutacoes(state, plano)

        # 7. Executar tool (se houver)
        resultado_tool = None
        if plano.get("tool"):
            resultado_tool = await self._executar_tool(plano, state, turno)
            apply_tool_result(state, plano["tool"], resultado_tool or {})
            state["last_action"] = plano["tool"]
        else:
            state["last_action"] = plano.get("action")

        # 8. Gerar resposta
        resposta = await gerar_resposta(state, plano, resultado_tool)

        # 9. Adicionar respostas ao histórico
        for msg in resposta:
            if isinstance(msg, str):
                add_message(state, "assistant", msg)
            elif isinstance(msg, dict) and msg.get("_interactive") and msg.get("body"):
                add_message(state, "assistant", msg["body"])

        # 10. Persistir estado, inclusive concluido. O router usa esse snapshot
        # final para gravar nome/stage/id_agenda no Contact antes de limpar Redis.
        await save_state(phone_hash, state)

        return resposta

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _aplicar_mutacoes(self, state: dict, plano: dict) -> None:
        """
        Aplica ao estado as mutações declaradas pelo planner LLM.

        O planner pode declarar updates em:
          - collected_data (update_data)
          - appointment    (update_appointment)
          - flags          (update_flags)
          - status         (new_status)
        """
        if plano.get("update_data"):
            state["collected_data"].update(plano["update_data"])

        if plano.get("update_appointment"):
            state["appointment"].update(plano["update_appointment"])

        if plano.get("update_flags"):
            state["flags"].update(plano["update_flags"])

        if plano.get("new_status"):
            state["status"] = plano["new_status"]

    async def _executar_tool(self, plano: dict, state: dict, turno: dict | None = None) -> dict | None:
        """Despacha para a tool correta com base no nome."""
        tool_name = plano["tool"]
        params = plano.get("params", {})

        # Helper: resolve slot object from last_slots_offered using escolha_slot
        def _resolver_slot() -> dict | None:
            idx = (turno or {}).get("escolha_slot")
            slots = state.get("last_slots_offered", [])
            if idx and 1 <= int(idx) <= len(slots):
                return slots[int(idx) - 1]
            appt_slot = state.get("appointment", {}).get("slot_escolhido")
            if isinstance(appt_slot, dict) and appt_slot.get("datetime"):
                return appt_slot
            return slots[0] if slots else None

        if tool_name == "consultar_slots":
            from app.tools.scheduling import consultar_slots
            return await consultar_slots(**params)

        if tool_name == "consultar_slots_remarcar":
            from app.tools.scheduling import consultar_slots_remarcar
            return await consultar_slots_remarcar(**params)

        if tool_name == "agendar":
            from app.tools.scheduling import agendar
            # Resolve slot: usa _resolver_slot() se LLM não passou ou passou null
            if not isinstance(params.get("slot"), dict) or not params["slot"].get("datetime"):
                params = {**params, "slot": _resolver_slot()}
            return await agendar(**params)

        if tool_name == "remarcar_dietbox":
            from app.tools.scheduling import remarcar
            # Resolve novo_slot: usa _resolver_slot() se LLM passou objeto incompleto
            if not isinstance(params.get("novo_slot"), dict) or not params["novo_slot"].get("datetime"):
                params = {**params, "novo_slot": _resolver_slot()}
            # Resolve ids do estado quando LLM não passou
            appt = state.get("appointment", {})
            if not params.get("consulta_atual"):
                params = {**params, "consulta_atual": appt.get("consulta_atual")}
            if not params.get("id_agenda_original"):
                params = {**params, "id_agenda_original": appt.get("id_agenda")}
            if not params.get("id_agenda_original") or not isinstance(params.get("novo_slot"), dict):
                logger.warning(
                    "Remarcacao bloqueada por dados incompletos: id_agenda=%s novo_slot=%s",
                    bool(params.get("id_agenda_original")),
                    bool(params.get("novo_slot")),
                )
                return {
                    "sucesso": False,
                    "erro": "dados_remarcacao_incompletos",
                    "escalar": True,
                }
            return await remarcar(**params)

        if tool_name == "cancelar":
            from app.tools.scheduling import cancelar
            return await cancelar(**params)

        if tool_name == "gerar_link_cartao":
            from app.tools.payments import gerar_link
            return await gerar_link(**params)

        if tool_name == "detectar_tipo_remarcacao":
            from app.tools.patients import detectar_tipo_remarcacao
            return await detectar_tipo_remarcacao(**params)

        if tool_name == "perda_retorno":
            return {"sucesso": True, "tipo": "perda_retorno"}

        if tool_name == "confirmar_pagamento_dietbox":
            from app.tools.payments import confirmar_pagamento_dietbox
            return await confirmar_pagamento_dietbox(**params)

        logger.warning("Tool desconhecida: %s", tool_name)
        return None

    def _atualizar_goal(self, state: dict, turno: dict) -> None:
        """
        Atualiza state.goal com base na intenção do turno.
        Usado pelo router para atualizar o stage do contato no banco.
        """
        _MAP = {
            "agendar":             "agendar_consulta",
            "remarcar":            "remarcar",
            "cancelar":            "cancelar",
            "tirar_duvida":        "duvida",
            "confirmar_pagamento": "agendar_consulta",
            "duvida_clinica":      "duvida_clinica",
            "recusou_remarketing": "recusou_remarketing",
        }
        intent = turno.get("intent", "fora_de_contexto")
        new_goal = _MAP.get(intent)
        if new_goal and state.get("goal") == "desconhecido":
            state["goal"] = new_goal
        elif new_goal and intent in ("remarcar", "cancelar"):
            state["goal"] = new_goal


# ── Instância global ──────────────────────────────────────────────────────────

engine = ConversationEngine()
