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
    delete_state,
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
            resultado_tool = await self._executar_tool(plano, state)
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

        # 10. Persistir ou deletar estado
        if state.get("status") == "concluido":
            await delete_state(phone_hash)
        else:
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

    async def _executar_tool(self, plano: dict, state: dict) -> dict | None:
        """Despacha para a tool correta com base no nome."""
        tool_name = plano["tool"]
        params = plano.get("params", {})

        if tool_name == "consultar_slots":
            from app.tools.scheduling import consultar_slots
            return await consultar_slots(**params)

        if tool_name == "consultar_slots_remarcar":
            from app.tools.scheduling import consultar_slots_remarcar
            return await consultar_slots_remarcar(**params)

        if tool_name == "agendar":
            from app.tools.scheduling import agendar
            return await agendar(**params)

        if tool_name == "remarcar_dietbox":
            from app.tools.scheduling import remarcar
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
