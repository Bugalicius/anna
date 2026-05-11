"""
Orchestrator - coordena o pipeline de um turno conversacional v2.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.conversation.state import add_message, load_state, save_state
from app.conversation_v2 import response_writer, rules, state_machine
from app.conversation_v2.config_loader import config
from app.conversation_v2.interpreter import interpretar
from app.conversation_v2.models import AcaoAutorizada, Mensagem, ResultadoTurno, TipoAcao
from app.conversation_v2.tools.registry import call_tool

logger = logging.getLogger(__name__)

FLUXO_ID = "agendamento_paciente_novo"
LOG_PATH = Path("logs/metrics.jsonl")

ACTION_NEXT_STATE = {
    "ir_apresentacao_planos": "apresentando_planos",
    "oferecer_upsell": "oferecendo_upsell",
    "ir_modalidade": "aguardando_modalidade",
    "ir_aguardando_preferencia_horario": "aguardando_preferencia_horario",
    "ir_aguardando_forma_pagamento": "aguardando_forma_pagamento",
    "ir_aguardando_pagamento_pix": "aguardando_pagamento_pix",
    "ir_aguardando_pagamento_cartao": "aguardando_pagamento_cartao",
    "criar_agendamento": "criando_agendamento",
}


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


def _ensure_v2_state(state: dict[str, Any], phone: str) -> dict[str, Any]:
    state.setdefault("phone", phone)
    state.setdefault("fluxo_id", FLUXO_ID)
    state.setdefault("estado", "inicio")
    state.setdefault("history", [])
    state.setdefault("collected_data", {})
    state.setdefault("appointment", {})
    state.setdefault("flags", {})
    state.setdefault("last_slots_offered", [])
    state.setdefault("slots_pool", [])
    state.setdefault("slots_rejeitados", [])
    state.setdefault("rodada_negociacao", 0)
    state.setdefault("status", "coletando")
    cd = state["collected_data"]
    for key in (
        "nome",
        "status_paciente",
        "objetivo",
        "plano",
        "modalidade",
        "preferencia_horario",
        "forma_pagamento",
        "data_nascimento",
        "email",
        "whatsapp_contato",
        "instagram",
        "profissao",
        "cep_endereco",
        "indicacao_origem",
    ):
        cd.setdefault(key, None)
    state["appointment"].setdefault("slot_escolhido", None)
    state["flags"].setdefault("pagamento_confirmado", False)
    return state


def _get_path(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    if parts[0] == "state":
        parts = parts[1:]
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def _primeiro_nome(state: dict[str, Any]) -> str:
    nome = (state.get("collected_data") or {}).get("nome") or ""
    return str(nome).split()[0].capitalize() if str(nome).strip() else ""


def _slot_label(slot: dict[str, Any]) -> str:
    return f"{slot.get('data_fmt') or slot.get('datetime', '')} {slot.get('hora') or ''}".strip()


def _slot_descricao(slot: dict[str, Any]) -> str:
    return _slot_label(slot)


def _slot_por_id(state: dict[str, Any], slot_id: str | None) -> dict[str, Any] | None:
    if not slot_id or not slot_id.startswith("slot_"):
        return None
    try:
        idx = int(slot_id.split("_", 1)[1]) - 1
    except ValueError:
        return None
    slots = state.get("last_slots_offered") or []
    return slots[idx] if 0 <= idx < len(slots) else None


def _valor_total(state: dict[str, Any]) -> float:
    cd = state.get("collected_data") or {}
    plano = cd.get("plano") or "ouro"
    modalidade = cd.get("modalidade") or "presencial"
    plano_cfg = config.get_plano(str(plano))
    return float(plano_cfg.valores.pix_online if modalidade == "online" else plano_cfg.valores.pix_presencial)


def _contexto_template(state: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = dict(state)
    ctx["primeiro_nome"] = _primeiro_nome(state)
    total = _valor_total(state) if (state.get("collected_data") or {}).get("plano") else 0
    ctx["valor_total"] = f"{total:.2f}".replace(".", ",") if total else ""
    ctx["valor_sinal"] = f"{(total * 0.5):.2f}".replace(".", ",") if total else ""
    slot = (state.get("appointment") or {}).get("slot_escolhido") or {}
    if isinstance(slot, dict):
        ctx["data_completa"] = slot.get("data_fmt") or slot.get("datetime", "")[:10]
        ctx["hora"] = slot.get("hora") or slot.get("datetime", "")[11:16]
        ctx["dia_semana"] = ctx["data_completa"]
    for i, s in enumerate(state.get("last_slots_offered") or [], start=1):
        ctx[f"slot_{i}_descricao"] = _slot_descricao(s)
        ctx[f"slot_{i}_label_curto"] = _slot_label(s)[:20]
    if extra:
        ctx.update(extra)
    return ctx


def _normalizar_entidades(
    state: dict[str, Any],
    entities: dict[str, Any],
    botao_id: str | None,
    texto_original: str,
) -> dict[str, Any]:
    entidades = dict(entities or {})
    texto = texto_original or str(entidades.get("texto_original") or "")
    cd = state.get("collected_data") or {}

    texto_norm = texto.lower()
    if "online" in texto_norm:
        entidades["modalidade_mencionada"] = "online"
        cd["modalidade"] = "online"
    elif "presencial" in texto_norm:
        entidades["modalidade_mencionada"] = "presencial"
        cd["modalidade"] = "presencial"

    plano_atual = cd.get("plano")
    upsell_dest = {"unica": "com_retorno", "com_retorno": "ouro", "ouro": "premium"}.get(str(plano_atual))
    if upsell_dest:
        entidades["plano_destino_calculado"] = upsell_dest

    slot = _slot_por_id(state, botao_id) or _slot_por_id(state, entidades.get("slot_correspondente"))
    if slot:
        entidades["slot_correspondente"] = slot
        entidades["slot_match"] = slot
    elif isinstance(entidades.get("slot_match"), str):
        slot = _slot_por_id(state, entidades["slot_match"])
        if slot:
            entidades["slot_match"] = slot
    entidades["rodada_atual"] = state.get("rodada_negociacao", 0)
    return entidades


def _aplicar_salvar_no_estado(state: dict[str, Any], salvar: dict[str, Any]) -> None:
    for path, value in (salvar or {}).items():
        if isinstance(value, str) and value.startswith("{") and value.endswith("}"):
            continue
        _set_path(state, path, value)


def _aplicar_efeitos_especiais(state: dict[str, Any], acao: AcaoAutorizada) -> None:
    if acao.situacao_nome == "rejeitou_todos":
        rejeitados = list(state.get("slots_rejeitados") or [])
        for slot in state.get("last_slots_offered") or []:
            if slot not in rejeitados:
                rejeitados.append(slot)
        state["slots_rejeitados"] = rejeitados
        state["last_slots_offered"] = []
        state["rodada_negociacao"] = int(state.get("rodada_negociacao") or 0) + 1


def _acao_navegacao(acao: AcaoAutorizada) -> str | None:
    action = (acao.dados or {}).get("action")
    return ACTION_NEXT_STATE.get(str(action or ""))


def _deve_disparar_on_enter(acao: AcaoAutorizada, target: str | None) -> bool:
    if not target:
        return False
    return not (acao.mensagens or acao.mensagens_a_enviar)


def _acao_on_enter_custom(state: dict[str, Any], estado: str) -> AcaoAutorizada | None:
    cd = state.get("collected_data") or {}
    if estado == "oferecendo_upsell":
        plano = cd.get("plano")
        destino = {"unica": "com_retorno", "com_retorno": "ouro", "ouro": "premium"}.get(str(plano))
        if not destino:
            return AcaoAutorizada(tipo=TipoAcao.enviar_mensagem, proximo_estado="aguardando_modalidade")
        origem_cfg = config.get_plano(str(plano))
        destino_cfg = config.get_plano(destino)
        modalidade = cd.get("modalidade") or "presencial"
        origem_val = origem_cfg.valores.pix_online if modalidade == "online" else origem_cfg.valores.pix_presencial
        dest_val = destino_cfg.valores.pix_online if modalidade == "online" else destino_cfg.valores.pix_presencial
        diff = dest_val - origem_val
        texto = (
            f"Ótima escolha! Posso te dar uma dica? Por +R${diff:.0f} você sobe para "
            f"{destino_cfg.nome_publico}. Quer trocar ou manter sua escolha?"
        )
        return AcaoAutorizada(
            tipo=TipoAcao.enviar_mensagem,
            mensagens=[Mensagem(tipo="botoes", conteudo=texto, botoes=[
                {"id": "upsell_aceitar", "label": f"Quero {destino_cfg.nome_publico}"},  # type: ignore[list-item]
                {"id": "upsell_recusar", "label": "Manter escolha"},  # type: ignore[list-item]
            ])],
            proximo_estado="oferecendo_upsell",
        )
    if estado == "confirmacao_final":
        return _confirmacao_final_acao(state)
    return None


def _confirmacao_final_acao(state: dict[str, Any]) -> AcaoAutorizada:
    cd = state.get("collected_data") or {}
    modalidade = cd.get("modalidade") or "presencial"
    ctx = _contexto_template(state)
    base = (
        f"{ctx.get('primeiro_nome') or 'Seu agendamento'}, sua consulta foi confirmada com sucesso!\n\n"
        f"Data e hora: {ctx.get('data_completa') or ''} às {ctx.get('hora') or ''}\n"
    )
    mensagens = [Mensagem(tipo="texto", conteudo=base)]
    if modalidade == "online":
        mensagens.extend([
            Mensagem(tipo="imagem", arquivo="COMO-SE-PREPARAR---ONLINE.jpg"),
            Mensagem(tipo="pdf", arquivo="Guia - Circunferências Corporais - Mulheres.pdf"),
            Mensagem(tipo="texto", conteudo="A consulta online será por videochamada no WhatsApp. Envie as fotos e medidas antes da consulta, por favor."),
        ])
    else:
        mensagens.extend([
            Mensagem(tipo="texto", conteudo="Local: Aura Clinic & Beauty - Rua Melo Franco, 204/Sala 103, Jardim da Glória, Vespasiano."),
            Mensagem(tipo="imagem", arquivo="COMO-SE-PREPARAR---presencial.jpg"),
        ])
    return AcaoAutorizada(tipo=TipoAcao.enviar_mensagem, mensagens=mensagens, proximo_estado="concluido")


async def _mensagens_on_enter(state: dict[str, Any], estado: str) -> tuple[list[Mensagem], str | None]:
    custom = _acao_on_enter_custom(state, estado)
    if custom:
        msgs = await response_writer.escrever_async(custom, _contexto_template(state))
        return msgs, custom.proximo_estado
    if estado == "aguardando_pagamento_cartao":
        cd = state.get("collected_data") or {}
        result = await call_tool(
            "gerar_link_pagamento",
            {
                "plano": cd.get("plano") or "ouro",
                "modalidade": cd.get("modalidade") or "presencial",
                "phone_hash": state.get("phone_hash") or "",
            },
        )
        url = result.dados.get("url") if result.sucesso else None
        if url:
            state["link_pagamento"] = result.dados
            return [
                Mensagem(
                    tipo="texto",
                    conteudo=f"Segue o link: {url}\n\nPode parcelar em até 10x sem juros. Após o pagamento, te confirmo aqui.",
                )
            ], None
        return [
            Mensagem(
                tipo="texto",
                conteudo="Não consegui gerar o link agora. Quer seguir por PIX para garantir o horário?",
            )
        ], "aguardando_forma_pagamento"
    on_enter = state_machine.on_enter_estado(FLUXO_ID, estado)
    if not on_enter:
        return [], None
    msgs = await response_writer.escrever_async(on_enter, _contexto_template(state))
    return msgs, on_enter.proximo_estado


async def _executar_consultar_slots(state: dict[str, Any]) -> tuple[list[Mensagem], str]:
    cd = state["collected_data"]
    result = await call_tool(
        "consultar_slots",
        {
            "modalidade": cd.get("modalidade") or "presencial",
            "preferencia": cd.get("preferencia_horario") or {},
            "excluir_slots": state.get("slots_rejeitados") or [],
            "max_resultados": 3,
        },
    )
    dados = result.dados if result.sucesso else {"slots": [], "slots_count": 0, "match_exato": False}
    slots = dados.get("slots") or []
    state["last_slots_offered"] = slots[:3]
    state["slots_pool"] = slots
    if not slots:
        return [Mensagem(tipo="texto", conteudo="No momento não tenho horários disponíveis nesse período. Quer que eu olhe outro horário?")], "aguardando_preferencia_horario"
    linhas = "\n".join(f"{i}. {_slot_descricao(s)}" for i, s in enumerate(slots[:3], start=1))
    intro = "Encontrei essas opções:" if dados.get("match_exato") else "Não tenho exatamente esse horário, mas tenho:"
    botoes = [{"id": f"slot_{i}", "label": _slot_label(s)[:20]} for i, s in enumerate(slots[:3], start=1)]
    return [Mensagem(tipo="botoes", conteudo=f"{intro}\n\n{linhas}\n\nQual prefere?", botoes=botoes)], "aguardando_escolha_slot"  # type: ignore[arg-type]


async def _executar_pagamento_pix(state: dict[str, Any], mensagem: dict[str, Any], entities: dict[str, Any]) -> tuple[list[Mensagem], str]:
    cd = state["collected_data"]
    valor_total = _valor_total(state)
    valor_sinal = round(valor_total * 0.5, 2)
    valor_pago = entities.get("valor_pago")
    image_bytes = mensagem.get("image_bytes") or mensagem.get("bytes") or b""
    mime_type = mensagem.get("mime_type") or "image/jpeg"

    if valor_pago is None and image_bytes:
        result = await call_tool("analisar_comprovante", {
            "imagem_bytes": image_bytes,
            "mime_type": mime_type,
            "plano": cd.get("plano") or "ouro",
            "modalidade": cd.get("modalidade") or "presencial",
        })
        if result.sucesso:
            valor_pago = result.dados.get("valor")
    if valor_pago is None:
        return [Mensagem(tipo="texto", conteudo="Não consegui ler o comprovante. Pode me mandar a tela do PIX confirmado?")], "aguardando_pagamento_pix"

    valor_pago = float(valor_pago)
    state["collected_data"]["valor_pago_sinal"] = valor_pago
    if valor_pago < valor_sinal:
        falta = valor_sinal - valor_pago
        return [Mensagem(tipo="texto", conteudo=f"Recebi R$ {valor_pago:.2f}, mas o sinal mínimo é R$ {valor_sinal:.2f}. Pode mandar mais R$ {falta:.2f}?")], "aguardando_pagamento_pix"
    state["flags"]["pagamento_confirmado"] = True
    if valor_pago >= valor_total:
        state["flags"]["pago_integral"] = True
        return [Mensagem(tipo="texto", conteudo=f"Recebi pagamento integral de R$ {valor_pago:.2f}. Tudo quitado.")], "aguardando_cadastro"
    restante = valor_total - valor_pago
    return [Mensagem(tipo="texto", conteudo=f"Recebi seu sinal de R$ {valor_pago:.2f}. Falta R$ {restante:.2f} para acertar no dia da consulta.")], "aguardando_cadastro"


def _acao_bloqueio_cadastro_se_necessario(
    estado: str,
    interpretacao_texto: str,
    entidades: dict[str, Any],
) -> AcaoAutorizada | None:
    texto = interpretacao_texto.lower()
    idade = entidades.get("tem_idade")
    try:
        idade_num = int(idade) if idade is not None else None
    except (TypeError, ValueError):
        idade_num = None

    if estado != "aguardando_cadastro":
        return None
    if idade_num is not None and idade_num < 16 or any(t in texto for t in ("grávida", "gravida", "gestante", "gestação", "gestacao")):
        return AcaoAutorizada(
            tipo=TipoAcao.escalar,
            mensagens=[
                Mensagem(
                    tipo="texto",
                    conteudo=(
                        "Infelizmente a Thaynara não realiza atendimento para gestantes "
                        "ou menores de 16 anos no momento. Vou avisar a equipe para te orientar por aqui."
                    ),
                )
            ],
            proximo_estado="concluido_escalado",
            dados={"action": "escalar_breno_silencioso"},
        )
    return None


async def _criar_agendamento_e_confirmar(state: dict[str, Any]) -> tuple[list[Mensagem], str]:
    # A execução real de criação no Dietbox fica para a tool de agendamento completa.
    # Nesta fase, o fluxo confirma após cadastro completo e pagamento confirmado.
    state["status"] = "concluido"
    state["appointment"].setdefault("id_agenda", "v2-pendente-dietbox")
    acao = _confirmacao_final_acao(state)
    msgs = await response_writer.escrever_async(acao, _contexto_template(state))
    return msgs, "concluido"


async def _log_metric(payload: dict[str, Any]) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as exc:
        logger.warning("Falha ao registrar métrica v2: %s", exc)


async def processar_turno(phone: str, mensagem: dict[str, Any]) -> ResultadoTurno:
    started = time.perf_counter()
    phone_hash = _phone_hash(phone)
    state = _ensure_v2_state(await load_state(phone_hash, phone), phone)
    estado_antes = state.get("estado", "inicio")
    mensagens: list[Mensagem] = []
    tools_chamadas: list[str] = []
    erro: str | None = None

    try:
        if estado_antes == "inicio":
            enter_msgs, prox = await _mensagens_on_enter(state, "inicio")
            mensagens.extend(enter_msgs)
            state["estado"] = prox or "aguardando_nome"
            add_message(state, "user", mensagem.get("text") or mensagem.get("body") or "")
            add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
            await save_state(phone_hash, state)
            return ResultadoTurno(sucesso=True, mensagens_enviadas=mensagens, novo_estado=state["estado"], fluxo_id=FLUXO_ID)

        interpretacao = await interpretar(mensagem, estado_antes, state.get("history", [])[-6:], state=state)
        entidades = _normalizar_entidades(
            state,
            interpretacao.entities,
            interpretacao.botao_id,
            interpretacao.texto_original,
        )

        acao = _acao_bloqueio_cadastro_se_necessario(estado_antes, interpretacao.texto_original, entidades)
        if acao is None and estado_antes == "aguardando_pagamento_pix" and entidades.get("valor_pago") is not None:
            acao = AcaoAutorizada(
                tipo=TipoAcao.executar_tool,
                tool_a_executar="analisar_comprovante",
                proximo_estado="validando_comprovante",
            )
        if acao is None:
            acao = state_machine.proxima_acao(
                estado_atual=estado_antes,
                intent=interpretacao.intent,
                entities=entidades,
                fluxo_id=FLUXO_ID,
                confidence=interpretacao.confidence,
                botao_id=interpretacao.botao_id,
                message_type=interpretacao.message_type,
                texto_original=interpretacao.texto_original,
                validacoes=interpretacao.validacoes,
                contexto_extra=_contexto_template(state, entidades),
            )
        if acao is None:
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[Mensagem(tipo="texto", conteudo="Pode me mandar de outro jeito para eu entender certinho?")],
                proximo_estado=estado_antes,
            )

        validation = rules.validar_acao_pre_envio(acao, state)
        blocked = next((v for v in validation if not v.passou and v.severidade == "BLOCKING"), None)
        if blocked:
            acao = AcaoAutorizada(
                tipo=TipoAcao.enviar_mensagem,
                mensagens=[Mensagem(tipo="texto", conteudo="Preciso validar essa informação antes de seguir.")],
                proximo_estado=estado_antes,
            )

        _aplicar_efeitos_especiais(state, acao)
        _aplicar_salvar_no_estado(state, acao.salvar_no_estado)
        target = acao.proximo_estado or _acao_navegacao(acao)

        if acao.tool_a_executar == "consultar_slots":
            tools_chamadas.append("consultar_slots")
            tool_msgs, target = await _executar_consultar_slots(state)
            mensagens.extend(tool_msgs)
        elif acao.tool_a_executar == "analisar_comprovante":
            tools_chamadas.append("analisar_comprovante")
            tool_msgs, target = await _executar_pagamento_pix(state, mensagem, entidades)
            mensagens.extend(tool_msgs)
        elif (acao.dados or {}).get("action") == "criar_agendamento":
            tool_msgs, target = await _criar_agendamento_e_confirmar(state)
            mensagens.extend(tool_msgs)
        else:
            mensagens.extend(await response_writer.escrever_async(acao, _contexto_template(state, entidades)))

        if target == "aguardando_modalidade" and state["collected_data"].get("modalidade"):
            target = "aguardando_preferencia_horario"

        if target:
            state["estado"] = target
            if _deve_disparar_on_enter(acao, target) and not mensagens:
                enter_msgs, prox = await _mensagens_on_enter(state, target)
                mensagens.extend(enter_msgs)
                if prox:
                    state["estado"] = prox
            elif _deve_disparar_on_enter(acao, target) and target in {
                "apresentando_planos",
                "aguardando_modalidade",
                "aguardando_preferencia_horario",
                "aguardando_forma_pagamento",
                "aguardando_pagamento_pix",
                "aguardando_cadastro",
                "oferecendo_upsell",
            }:
                enter_msgs, prox = await _mensagens_on_enter(state, target)
                mensagens.extend(enter_msgs)
                if prox:
                    state["estado"] = prox

        if state.get("estado") == "criando_agendamento":
            final_msgs, final_state = await _criar_agendamento_e_confirmar(state)
            mensagens.extend(final_msgs)
            state["estado"] = final_state

        add_message(state, "user", interpretacao.texto_original)
        add_message(state, "assistant", "\n".join(m.conteudo for m in mensagens if m.conteudo))
        await save_state(phone_hash, state)
        return ResultadoTurno(
            sucesso=True,
            mensagens_enviadas=mensagens,
            novo_estado=state["estado"],
            fluxo_id=FLUXO_ID,
            duracao_ms=int((time.perf_counter() - started) * 1000),
        )
    except Exception as exc:
        erro = str(exc)
        logger.exception("Erro no orchestrator v2: %s", exc)
        fallback = Mensagem(tipo="texto", conteudo="Tive uma instabilidade aqui. Pode me mandar de novo, por favor?")
        return ResultadoTurno(sucesso=False, mensagens_enviadas=[fallback], novo_estado=state.get("estado"), fluxo_id=FLUXO_ID, erro=erro)
    finally:
        await _log_metric({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phone_hash": phone_hash,
            "fluxo": FLUXO_ID,
            "estado_antes": estado_antes,
            "estado_depois": state.get("estado"),
            "tools_chamadas": tools_chamadas,
            "duracao_ms": int((time.perf_counter() - started) * 1000),
            "erro": erro,
        })
