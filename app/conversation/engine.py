"""
ConversationEngine — motor central de conversação.

Substitui o sistema de múltiplos agentes FSM por um único loop inteligente:
  1. Carrega estado
  2. Interpreta turno (LLM)
  3. Decide ação (Planner)
  4. Executa tool (se houver)
  5. Atualiza estado
  6. Gera resposta

Integração com o router atual via engine_instance.handle_message().
"""
from __future__ import annotations

import logging

from app.conversation.state import (
    add_message,
    apply_correction,
    apply_tool_result,
    apply_turno_updates,
    create_state,
    delete_state,
    load_state,
    save_state,
)
from app.conversation.interpreter import interpretar_turno
from app.conversation.planner import (
    decidir_acao,
    APPLY_UPGRADE,
    SLOT_CONFIRMED,
    PAGAMENTO_CONFIRMADO,
    OFFER_UPSELL,
    SEND_PLANOS,
    REDIRECT_RETENCAO,
    REDIRECT_ATENDIMENTO,
    ASK_MOTIVO_CANCEL,
)
from app.conversation.responder import gerar_resposta

logger = logging.getLogger(__name__)

# Máximo de re-planejamentos por turno (evita loop infinito)
_MAX_REPLANS = 4


class ConversationEngine:
    """
    Motor central de conversação.
    Uma instância global é suficiente — stateless entre chamadas.
    """

    async def handle_message(self, phone_hash: str, message: str, phone: str = "") -> list:
        """
        Processa uma mensagem e retorna lista de respostas.

        phone_hash: hash do telefone (nunca o número real — LGPD)
        message:    texto recebido do paciente
        phone:      número real (necessário para tools que chamam Dietbox/Rede)
        """
        # 1. Carregar estado
        state = await load_state(phone_hash, phone)
        add_message(state, "user", message)

        # 2. Interpretar turno
        turno = await interpretar_turno(message, state)

        # 3. Aplicar extração e correções ao estado (antes do planner)
        apply_turno_updates(state, turno)
        if turno.get("correcao"):
            c = turno["correcao"]
            apply_correction(state, c["campo"], c["valor_novo"])

        # 4. Atualiza goal baseado na intenção interpretada
        self._atualizar_goal(state, turno)

        # 5. Loop de planejamento (permite re-planejar após mutações intermediárias)
        resultado_tool = None
        plano = None

        for _ in range(_MAX_REPLANS):
            plano = await decidir_acao(turno, state)
            action = plano["action"]

            # Mutações intermediárias que exigem re-planejamento imediato
            if action == APPLY_UPGRADE:
                plano_upgrade = plano["meta"]["plano_upgrade"]
                state["collected_data"]["plano"] = plano_upgrade
                state["flags"]["upsell_oferecido"] = True
                logger.info("Upgrade aplicado: %s", plano_upgrade)
                continue

            if action == SLOT_CONFIRMED:
                idx = plano["ask_context"]
                state["appointment"]["slot_escolhido"] = state["last_slots_offered"][idx]
                turno["escolha_slot"] = None  # evita reprocessamento
                logger.info("Slot confirmado: idx=%d", idx)
                continue

            if action == PAGAMENTO_CONFIRMADO:
                state["flags"]["pagamento_confirmado"] = True
                state["status"] = "coletando"
                logger.info("Pagamento confirmado")
                continue

            if action == REDIRECT_RETENCAO:
                state["goal"] = "remarcar"
                turno = {**turno, "intent": "remarcar"}
                continue

            if action == REDIRECT_ATENDIMENTO:
                state["goal"] = "agendar_consulta"
                state["tipo_remarcacao"] = None
                state["collected_data"]["status_paciente"] = "novo"
                turno = {**turno, "intent": "agendar"}
                continue

            # Marca flags de progresso antes de executar
            if action == OFFER_UPSELL:
                state["flags"]["upsell_oferecido"] = True

            if action == SEND_PLANOS:
                state["flags"]["planos_enviados"] = True

            if action == ASK_MOTIVO_CANCEL:
                state["flags"]["aguardando_motivo_cancel"] = True
                # Salva motivo da mensagem atual se for resposta ao pedido anterior
                if state["flags"].get("aguardando_motivo_cancel") and message:
                    state["collected_data"]["motivo_cancelamento"] = message[:200]

            # 6. Executar tool (se houver)
            if plano.get("tool"):
                resultado_tool = await self._executar_tool(plano, state)
                apply_tool_result(state, plano["tool"], resultado_tool or {})
                state["last_action"] = plano["tool"]

            break  # Sai do loop — plano final encontrado

        # 7. Atualizar estado via plano
        state = self._atualizar_estado(state, turno, plano, resultado_tool)

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

    def _atualizar_estado(self, state: dict, turno: dict, plano: dict, resultado: dict | None) -> dict:
        """
        Aplica mutações finais ao estado após execução do plano.

        Atualiza last_action, collected_data e status conforme o plano.
        """
        # Atualiza ação registrada
        state["last_action"] = plano.get("action")

        # Aplica atualizações de campos coletados declaradas pelo planner
        if plano.get("update_data"):
            state["collected_data"].update(plano["update_data"])

        # Aplica novo status se declarado
        if plano.get("new_status"):
            state["status"] = plano["new_status"]

        return state

    # ── Helpers internos ──────────────────────────────────────────────────────

    def _atualizar_goal(self, state: dict, turno: dict) -> None:
        """Atualiza o goal do estado baseado na intenção do turno."""
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
            # Intents de interrupt sobrescrevem o goal atual
            state["goal"] = new_goal


# ── Instância global ──────────────────────────────────────────────────────────

engine = ConversationEngine()
