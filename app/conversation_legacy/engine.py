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
import os
import unicodedata
import asyncio
from time import perf_counter

from app import llm_client
from app.conversation_legacy.state import (
    add_message,
    apply_correction,
    apply_tool_result,
    apply_turno_updates,
    load_state,
    save_state,
)
from app.conversation_legacy.interpreter import interpretar_turno
from app.conversation_legacy.planner import decidir_acao
from app.conversation_legacy.responder import gerar_resposta, sanitize_patient_responses
from app.metrics import record_turn_error, reset_error_count, write_turn_metric

logger = logging.getLogger(__name__)


async def _notificar_breno_b2b(state: dict) -> None:
    """Notifica Breno silenciosamente quando detectado contato B2B."""
    import os
    breno = os.environ.get("NUMERO_INTERNO", os.environ.get("BRENO_PHONE", "5531992059211"))
    cd = state.get("collected_data", {})
    phone = state.get("phone", "?")
    msg = (
        f"🏢 *CONTATO B2B*\n"
        f"📱 WhatsApp: {phone}\n"
        f"👤 Nome: {cd.get('nome') or 'não informado'}\n\n"
        "Solicitou atendimento corporativo — respondido com mensagem padrão B2B."
    )
    try:
        from app.meta_api import MetaAPIClient
        meta = MetaAPIClient()
        await meta.send_text(breno, msg)
        logger.info("Notificação B2B enviada ao Breno para %s", phone[-4:])
    except Exception as e:
        logger.warning("Falha ao notificar Breno sobre B2B: %s", e)


async def _notificar_cartao_thaynara(state: dict) -> None:
    """Notifica Thaynara quando pagamento via cartão é confirmado pelo engine."""
    import os
    thaynara = os.environ.get("THAYNARA_PHONE", "5531991394759")
    cd = state.get("collected_data", {})
    nome = cd.get("nome") or "Paciente"
    plano = cd.get("plano") or "—"
    modalidade = cd.get("modalidade") or "—"
    link_url = state.get("appointment", {}).get("link_cartao") or ""
    valor_txt = "—"
    try:
        from app import knowledge_base as _kb
        v = _kb.kb.get_valor(plano, modalidade)
        if v:
            valor_txt = f"R$ {v:.2f}"
    except Exception:
        pass
    msg = (
        f"💳 Pagamento via cartão confirmado\n"
        f"👤 Paciente: {nome}\n"
        f"💰 Valor: {valor_txt}\n"
        f"📋 Plano: {plano} ({modalidade})"
    )
    if link_url:
        msg += f"\n🔗 Link: {link_url}"
    try:
        from app.meta_api import MetaAPIClient
        meta = MetaAPIClient()
        await meta.send_text(thaynara, msg)
        logger.info("Notificação cartão enviada para Thaynara (paciente %s)", nome)
    except Exception as e:
        logger.warning("Falha ao notificar Thaynara sobre cartão: %s", e)


class ConversationEngine:
    """
    Motor central de conversação — stateless entre chamadas.
    Uma instância global é suficiente.
    """

    async def handle_message(self, phone_hash: str, message: str, phone: str = "") -> list:
        timeout = float(os.environ.get("TURN_TIMEOUT_SECONDS", "90"))
        try:
            return await asyncio.wait_for(
                self._handle_message_impl(phone_hash, message, phone=phone),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error("Timeout geral do turno para hash=%s apos %.1fs", phone_hash[-8:], timeout)
            await record_turn_error(phone_hash, "timeout")
            write_turn_metric({
                "phone_hash": phone_hash,
                "stage": None,
                "intent": None,
                "action": "timeout",
                "tool_duration_ms": None,
                "llm_calls": llm_client.get_llm_call_count(),
                "duration_ms": int(timeout * 1000),
                "decision": None,
                "integration_error_code": None,
                "error": "timeout",
            })
            return [
                "Estou com instabilidade para processar sua mensagem agora. "
                "Pode tentar novamente em alguns instantes? 💚"
            ]

    async def _handle_message_impl(self, phone_hash: str, message: str, phone: str = "") -> list:
        """
        Processa uma mensagem e retorna lista de respostas.

        phone_hash: hash do telefone (LGPD — nunca o número real)
        message:    texto recebido do paciente
        phone:      número real (necessário para tools Dietbox/Rede)
        """
        started = perf_counter()
        turno = {}
        plano = {}
        resultado_tool = None
        tool_duration_ms = None
        llm_client.reset_llm_call_count()
        try:
            # 1. Carregar estado
            state = await load_state(phone_hash, phone)
            add_message(state, "user", message)

            # Pre-processamento de botões de confirmação de presença
            if message == "confirmar_presenca":
                state["flags"]["confirmacao_presenca"] = True
                resposta = ["Confirmado então! Obrigadaaa 💚😉"]
                add_message(state, "assistant", resposta[0])
                await save_state(phone_hash, state)
                return resposta

            if message == "remarcar_consulta":
                # Trata como se o paciente tivesse escrito "quero remarcar minha consulta"
                message = "quero remarcar minha consulta"

            # 2. Interpretar turno (LLM)
            turno = await interpretar_turno(message, state)
            turno["_raw_message"] = message  # Disponível para heurísticas do planner

            # 3. Aplicar extrações e correções ao estado
            # Bug 2: preservar nome já preenchido (só muda com correção explícita)
            nome_anterior = state["collected_data"].get("nome")
            apply_turno_updates(state, turno)
            if nome_anterior and state["collected_data"].get("nome") != nome_anterior:
                correcao = turno.get("correcao") or {}
                tem_correcao_nome = correcao.get("campo") == "nome"
                nome_antigo_completo = len(str(nome_anterior).strip().split()) >= 2
                if not tem_correcao_nome and nome_antigo_completo:
                    state["collected_data"]["nome"] = nome_anterior
            # Bug 3: bloquear palavras genéricas salvas como nome
            _NOME_GENERICO = {
                "consulta", "agendar", "marcar", "oi", "olá", "ola",
                "sim", "não", "nao", "ok", "tudo", "bem",
                "quero", "preciso", "gostaria",
            }
            nome_atual = state["collected_data"].get("nome")
            if nome_atual and nome_atual.strip().lower() in _NOME_GENERICO:
                logger.warning("Nome genérico bloqueado: '%s'", nome_atual)
                state["collected_data"]["nome"] = None
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
            if plano.get("tool"):
                tool_started = perf_counter()
                resultado_tool = await self._executar_tool(plano, state, turno)
                tool_duration_ms = int((perf_counter() - tool_started) * 1000)
                apply_tool_result(state, plano["tool"], resultado_tool or {})
                state["last_action"] = plano["tool"]
                # Notifica Thaynara quando pagamento via cartão é confirmado
                if (
                    plano["tool"] == "confirmar_pagamento_dietbox"
                    and isinstance(resultado_tool, dict)
                    and resultado_tool.get("sucesso")
                ):
                    asyncio.create_task(_notificar_cartao_thaynara(state))
            else:
                state["last_action"] = plano.get("action")
                if plano.get("action") == "respond_b2b":
                    asyncio.create_task(_notificar_breno_b2b(state))

            # 8. Gerar resposta
            resposta = await gerar_resposta(state, plano, resultado_tool)
            resposta = sanitize_patient_responses(resposta, state)

            # 9. Adicionar respostas ao histórico
            for msg in resposta:
                if isinstance(msg, str):
                    add_message(state, "assistant", msg)
                elif isinstance(msg, dict) and msg.get("_interactive") and msg.get("body"):
                    add_message(state, "assistant", msg["body"])

            # 10. Persistir estado, inclusive concluido. O router usa esse snapshot
            # final para gravar nome/stage/id_agenda no Contact antes de limpar Redis.
            await save_state(phone_hash, state)
            tool_error = bool(
                isinstance(resultado_tool, dict)
                and resultado_tool.get("sucesso") is False
            )
            if tool_error:
                await record_turn_error(phone_hash, "tool_failure")
            else:
                await reset_error_count(phone_hash)
            write_turn_metric({
                "phone_hash": phone_hash,
                "stage": state.get("status"),
                "intent": turno.get("intent"),
                "action": plano.get("action"),
                "tool": plano.get("tool"),
                "tool_duration_ms": tool_duration_ms,
                "llm_calls": llm_client.get_llm_call_count(),
                "duration_ms": int((perf_counter() - started) * 1000),
                "decision": (plano.get("meta") or {}).get("decision"),
                "integration_error_code": (
                    resultado_tool.get("erro")
                    if isinstance(resultado_tool, dict) and resultado_tool.get("sucesso") is False
                    else None
                ),
                "error": "tool_failure" if tool_error else None,
            })

            return resposta
        except Exception as e:
            await record_turn_error(phone_hash, type(e).__name__)
            write_turn_metric({
                "phone_hash": phone_hash,
                "stage": None,
                "intent": turno.get("intent"),
                "action": plano.get("action"),
                "tool": plano.get("tool"),
                "tool_duration_ms": tool_duration_ms,
                "llm_calls": llm_client.get_llm_call_count(),
                "duration_ms": int((perf_counter() - started) * 1000),
                "decision": (plano.get("meta") or {}).get("decision"),
                "integration_error_code": (
                    resultado_tool.get("erro")
                    if isinstance(resultado_tool, dict) and resultado_tool.get("sucesso") is False
                    else None
                ),
                "error": type(e).__name__,
            })
            raise

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
            appt = state.get("appointment", {})
            consulta_atual = appt.get("consulta_atual") or {}
            if not params.get("consulta_atual_inicio") and consulta_atual.get("inicio"):
                params = {**params, "consulta_atual_inicio": consulta_atual.get("inicio")}
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
        raw = turno.get("_raw_message", "")
        if intent == "agendar" and state.get("goal") == "remarcar" and self._pedido_explicito_nova_consulta(raw):
            state["goal"] = "agendar_consulta"
            state["tipo_remarcacao"] = "nova_consulta"
            state["appointment"]["consulta_atual"] = None
            state["appointment"]["id_agenda"] = None
            state["last_slots_offered"] = []
            state["slots_pool"] = []
            state["collected_data"]["status_paciente"] = "novo"
            return

        new_goal = _MAP.get(intent)
        if new_goal and state.get("goal") == "desconhecido":
            state["goal"] = new_goal
        elif new_goal and intent in ("remarcar", "cancelar"):
            state["goal"] = new_goal

    @staticmethod
    def _pedido_explicito_nova_consulta(texto: str | None) -> bool:
        if not texto:
            return False
        sem_acento = unicodedata.normalize("NFKD", str(texto))
        t = "".join(ch for ch in sem_acento if not unicodedata.combining(ch)).lower()
        fala_agendar = any(p in t for p in (
            "agendar", "marcar", "nova consulta", "primeira consulta",
            "consulta nova", "quero consulta", "quero uma consulta",
        ))
        nega_remarcacao = any(p in t for p in (
            "nao e remarc", "nao quero remarc", "nao tenho consulta",
            "nao tenho email cadastrado", "sem email cadastrado",
        ))
        return fala_agendar and ("nova" in t or "primeira" in t or nega_remarcacao)


# ── Instância global ──────────────────────────────────────────────────────────

engine = ConversationEngine()
