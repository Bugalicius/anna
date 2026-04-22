"""
Responder — gera as respostas a enviar ao paciente.

Função pública:
  gerar_resposta(state, plano, resultado_tool) -> list[str | dict]

Retorna lista de mensagens (str = texto, dict = mídia).
Usa templates fixos quando possível; LLM apenas para respostas livres.
"""
from __future__ import annotations

import logging
import os
import random

import anthropic

from app.knowledge_base import kb
from app.pii_sanitizer import sanitize_historico

logger = logging.getLogger(__name__)

# ── Templates de mensagem ─────────────────────────────────────────────────────

MSG_BOAS_VINDAS = (
    "Olá! Que bom ter você por aqui 💚\n\n"
    "Sou a Ana, responsável pelos agendamentos da nutricionista Thaynara Teixeira.\n\n"
    "Pra começar, você poderia me informar:\n"
    "• Qual seu nome e sobrenome?\n"
    "• É sua primeira consulta ou você já é paciente?\n\n"
    "Ah, um aviso importante: no momento a Thaynara não realiza atendimento "
    "para gestantes e menores de 16 anos, tudo bem?"
)

MSG_OBJETIVOS = (
    "Ótimo, {nome}! 😊\n\n"
    "Me conta: qual é o seu principal objetivo com o acompanhamento nutricional?\n\n"
    "👉 Emagrecer\n"
    "👉 Ganhar massa\n"
    "👉 Tratar lipedema\n"
    "👉 Outro objetivo"
)

MSG_PLANOS_INTRO = "Obrigada pelas informações! 💚"

MSG_PLANOS_RESUMO = (
    "Acabei de enviar nosso mídia kit com todas as opções, valores e benefícios exclusivos 😊\n\n"
    "A Thaynara trabalha com o método *#NutriTransforma* — acompanhamento real, "
    "ajustes constantes e resultados sustentáveis, sem dietas extremas nem recomeços frustrantes.\n\n"
    "Dá uma olhadinha com calma e me responde: qual modalidade e plano fazem mais sentido pra você agora?"
)

MSG_PREFERENCIA_HORARIO = (
    "Para seguirmos com o agendamento, me informe qual horário atende melhor à sua rotina:\n\n"
    "Segunda a Sexta-feira:\n"
    "Manhã: 08h, 09h e 10h\n"
    "Tarde: 15h, 16h e 17h\n"
    "Noite: 18h e 19h (exceto sexta à noite)\n\n"
    "Importante: só realizamos o agendamento mediante confirmação do pagamento. "
    "Quanto antes o sinal for enviado, maior a chance de garantir o horário de sua preferência."
)

MSG_AGENDAMENTO_OPCOES = (
    "Tenho essas opções disponíveis para {modalidade}:\n\n{opcoes}\n\nQual horário funciona melhor pra você?"
)

MSG_FORMA_PAGAMENTO = (
    "Perfeito, {nome}! 😊\n\n"
    "Para confirmar seu agendamento, é necessário o pagamento antecipado. "
    "Essa é uma política da clínica — garante que seu horário fique reservado exclusivamente pra você 💚\n\n"
    "*{plano_nome}* ({modalidade}):\n"
    "• PIX com desconto: *R${valor:.0f}* (sinal de 50%: *R${sinal:.0f}*)\n"
    "• Cartão: *{parcelas}x de R${parcela:.0f}* sem juros (valor integral)\n\n"
    "Qual opção prefere?\n"
    "👉 PIX\n"
    "👉 Cartão de crédito"
)

MSG_PIX = (
    "Segue a chave PIX para pagamento:\n\n"
    "CPF: *{chave_pix}*\n\n"
    "Valor do sinal (50%): *R${sinal:.0f}*\n\n"
    "Assim que concluir, me manda o comprovante pra eu confirmar tudo e enviar as demais informações 😊"
)

MSG_CARTAO = (
    "Claro! Segue o link para pagamento seguro via cartão 💳\n\n"
    "{link}\n\n"
    "{parcelas}x de R${parcela:.0f}. Após confirmar o pagamento, a consulta fica garantida!"
)

MSG_AGUARDA_COMPROVANTE = (
    "Aguardo o comprovante de pagamento para confirmar sua consulta 😊"
)

MSG_CONFIRMACAO_PRESENCIAL = (
    "{nome}, sua consulta foi confirmada com sucesso! ✅\n\n"
    "📅 *Data e hora:* {data} às {hora}\n"
    "📍 *Local:* Aura Clinic & Beauty\n"
    "Rua Melo Franco, 204/Sala 103, Jardim da Glória, Vespasiano\n"
    "https://maps.app.goo.gl/XxHgHxHh7aCxitDs8\n\n"
    "Políticas importantes:\n"
    "⏱️ Tolerância máxima de atraso: 10 minutos.\n"
    "🔄 Reagendar/cancelar: informar com 24h de antecedência.\n"
    "🚫 Não comparecimento: consulta considerada realizada, sem reembolso.\n\n"
    "💚 Obrigada pela confiança! Estamos te esperando."
)

MSG_CONFIRMACAO_ONLINE = (
    "{nome}, sua consulta foi confirmada com sucesso! ✅\n\n"
    "📅 *Data e hora:* {data} às {hora}\n"
    "📍 *Local:* Chamada de vídeo pelo WhatsApp (a nutri irá te ligar no número cadastrado)\n"
    "✅ Certifique-se de ter uma boa conexão de internet.\n\n"
    "Políticas importantes:\n"
    "⏱️ Tolerância máxima de atraso: 10 minutos.\n"
    "🔄 Reagendar/cancelar: informar com 24h de antecedência.\n"
    "🚫 Não comparecimento: consulta considerada realizada, sem reembolso.\n\n"
    "💚 Obrigada pela confiança! Estamos te esperando."
)

MSG_CONFIRMACAO_REMARCACAO = (
    "✅ *Consulta remarcada com sucesso!*\n\n"
    "📅 *Nova data:* {data} às {hora}\n"
    "📍 *Modalidade:* {modalidade}\n\n"
    "Qualquer dúvida, é só me chamar aqui 💚"
)

MSG_CANCELAMENTO_CONFIRMADO = (
    "Consulta cancelada com sucesso ✅\n\n"
    "Quando quiser retomar o acompanhamento, é só me chamar aqui! "
    "A Thaynara vai adorar te receber 💚"
)

MSG_ERRO_AGENDAMENTO = (
    "Ops! Tive um problema técnico ao confirmar seu agendamento no sistema 😔\n\n"
    "Vou acionar a equipe para resolver manualmente. "
    "Você receberá uma confirmação assim que estiver tudo certo 💚"
)

MSG_ERRO_REMARCACAO = (
    "Ops! Tive um problema técnico ao tentar confirmar a remarcação 😔\n\n"
    "Vou pedir para a Thaynara verificar manualmente, tudo bem? 💚"
)

MSG_SEM_HORARIOS = (
    "Poxa, não encontrei horários disponíveis nos próximos dias úteis. "
    "Mas não se preocupa! Deixa eu verificar opções com a Thaynara e "
    "já te retorno com as disponibilidades 🔍"
)

MSG_FORA_CONTEXTO = (
    "Oi! Sou a Ana, assistente da nutricionista Thaynara Teixeira 💚 "
    "Posso te ajudar com agendamentos e informações sobre as consultas. "
    "Tem algo nesse sentido que posso te ajudar?"
)

MSG_ENCERRAMENTO_REMARKETING = (
    "Tudo bem! Posso perguntar o que pesou na decisão? "
    "Só pra melhorar nosso atendimento 😊"
)

MSG_FORMULARIO_PAGAMENTO = (
    "Para garantir o compromisso, o formulário só é enviado após o pagamento 😊\n\n"
    f"R$ 100 — Chave PIX (CPF): *{kb.contatos['pix_chave']}*\n\n"
    "Feito, me manda o comprovante que retorno com a confirmação e orientações! 👈✅"
)

MSG_UPSELL = {
    "unica": (
        "Ótima escolha! Mas posso te dar uma dica? 💚\n\n"
        "O *Plano Ouro* sai por R${valor_ouro:.0f} presencial (ou R${valor_ouro_online:.0f} online) "
        "e já inclui 3 consultas + 130 dias de acompanhamento — "
        "o custo por consulta fica bem menor e o suporte é muito mais completo.\n\n"
        "Quer manter a Consulta Única ou prefere o Ouro?"
    ),
    "com_retorno": (
        "Ótima escolha! Posso te dar uma dica? 💚\n\n"
        "Por apenas +R${diff:.0f} você sobe pro *Plano Ouro*: 3 consultas, 130 dias de acompanhamento "
        "e a Lilly inclusa. É bem mais suporte pelo investimento.\n\n"
        "Quer manter a Consulta com Retorno ou prefere o Ouro?"
    ),
    "ouro": (
        "Ótima escolha! Posso te dar uma dica? 💚\n\n"
        "O *Plano Premium* dobra as consultas (6 no total), 270 dias de acompanhamento, "
        "encontros coletivos e a Lilly — fica por R${valor_premium:.0f} presencial.\n\n"
        "Quer manter o Ouro ou prefere o Premium?"
    ),
}

_WAITING = [
    "Um instante, por favor 💚",
    "Só um minutinho, já verifico pra você 💚",
    "Aguarda um instante que já te respondo 💚",
]

# ── Função pública ─────────────────────────────────────────────────────────────


async def gerar_resposta(state: dict, plano: dict, resultado_tool: dict | None) -> list:
    """
    Gera a lista de mensagens a enviar ao paciente.

    Retorna list[str | dict], onde dict representa envio de mídia:
      {"media_type": "document"|"image", "media_key": str, "caption": str}
    """
    action = plano["action"]
    cd = state["collected_data"]
    nome = cd.get("nome") or ""

    # ── Perguntar campo ───────────────────────────────────────────────────────
    if action == "ask_field":
        draft = plano.get("draft_message")
        history = state.get("history", [])
        ask_context = plano.get("ask_context", "")
        # Campos com UI interativa — sempre usar template (ignorar draft)
        if ask_context == "objetivo":
            return _ask_field(ask_context, nome, state)
        # Usa draft do planner para turnos além da primeira mensagem
        if draft and len(history) > 1:
            return [draft]
        return _ask_field(ask_context, nome, state)

    # ── Enviar planos ─────────────────────────────────────────────────────────
    if action == "send_planos":
        return [
            MSG_PLANOS_INTRO,
            {"media_type": "document", "media_key": "pdf_thaynara",
             "caption": "Nosso mídia kit completo"},
            MSG_PLANOS_RESUMO,
        ]

    # ── Upsell ────────────────────────────────────────────────────────────────
    if action == "offer_upsell":
        return [_build_upsell_msg(plano["ask_context"], cd.get("modalidade") or "presencial")]

    # ── Consultar slots ───────────────────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") in ("consultar_slots", "consultar_slots_remarcar"):
        if resultado_tool and resultado_tool.get("slots"):
            slots = resultado_tool["slots"]
            aviso = resultado_tool.get("aviso_preferencia", "")
            return [random.choice(_WAITING), _build_slot_buttons(slots, aviso)]
        return [MSG_SEM_HORARIOS]

    # ── Escolha de slot / pede escolha ────────────────────────────────────────
    if action == "ask_slot_choice":
        slots = state.get("last_slots_offered", [])
        if not slots:
            return [MSG_SEM_HORARIOS]
        return ["Pode me dizer qual horário prefere? 😊", _build_slot_buttons(slots)]

    # ── Forma de pagamento ────────────────────────────────────────────────────
    if action == "ask_forma_pagamento":
        return [_build_forma_pagamento_interactive(cd, nome)]

    # ── Aguarda pagamento ─────────────────────────────────────────────────────
    if action == "await_payment":
        if cd.get("forma_pagamento") == "pix":
            plano_key = cd.get("plano") or "unica"
            modal = cd.get("modalidade") or "presencial"
            valor = kb.get_valor(plano_key, modal)
            return [MSG_PIX.format(
                chave_pix=kb.contatos["pix_chave"],
                sinal=valor * 0.5,
            )]
        return [MSG_AGUARDA_COMPROVANTE]

    # ── Gerar link cartão ─────────────────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "gerar_link_cartao":
        if resultado_tool and resultado_tool.get("sucesso") and resultado_tool.get("link_url"):
            lp = resultado_tool
            return [
                random.choice(_WAITING),
                MSG_CARTAO.format(
                    link=lp["link_url"],
                    parcelas=lp.get("parcelas", 1),
                    parcela=lp.get("parcela_valor", 0),
                ),
            ]
        # Fallback para PIX
        plano_key = cd.get("plano") or "unica"
        modal = cd.get("modalidade") or "presencial"
        valor = kb.get_valor(plano_key, modal)
        return [
            f"Ops, tive um problema ao gerar o link de pagamento 😕 "
            f"Me dá um instante e vou verificar. Se preferir, o PIX funciona direto: "
            f"chave CPF *{kb.contatos['pix_chave']}*",
            MSG_PIX.format(chave_pix=kb.contatos["pix_chave"], sinal=valor * 0.5),
        ]

    # ── Agendamento no Dietbox ────────────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "agendar":
        if resultado_tool and resultado_tool.get("sucesso"):
            return [random.choice(_WAITING)] + _build_confirmacao(state)
        return [random.choice(_WAITING), MSG_ERRO_AGENDAMENTO]

    # ── Confirmação final ─────────────────────────────────────────────────────
    if action == "send_confirmacao":
        return _build_confirmacao(state)

    # ── Formulário ────────────────────────────────────────────────────────────
    if action == "send_formulario_instrucoes":
        return [MSG_FORMULARIO_PAGAMENTO]

    if action == "send_formulario_link":
        return [
            f"Aqui está o link para preencher o formulário 💚\n\n"
            f"{kb.contatos['formulario_link']}\n\n"
            "Responda todas as perguntas com atenção — elas são a base do seu plano alimentar.\n\n"
            "Envie no número da nutri fotos de short/top (frente, costas, lateral). "
            "Sua dieta será entregue em até 5 dias úteis 💪",
            f"Contato da nutricionista: {kb.contatos['numero_nutri_publico']}",
        ]

    # ── Remarcação / cancelamento ─────────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "remarcar_dietbox":
        if resultado_tool and resultado_tool.get("sucesso"):
            slot = state["appointment"].get("slot_escolhido") or {}
            return [MSG_CONFIRMACAO_REMARCACAO.format(
                data=slot.get("data_fmt", ""),
                hora=slot.get("hora", ""),
                modalidade=cd.get("modalidade") or "presencial",
            )]
        return [MSG_ERRO_REMARCACAO]

    if action == "send_confirmacao_remarcacao":
        slot = state["appointment"].get("slot_escolhido") or {}
        return [MSG_CONFIRMACAO_REMARCACAO.format(
            data=slot.get("data_fmt", ""),
            hora=slot.get("hora", ""),
            modalidade=cd.get("modalidade") or "presencial",
        )]

    if action == "ask_motivo_cancelamento":
        politica = kb.get_politica("cancelamento")
        draft = plano.get("draft_message")
        texto = draft if draft else (
            f"Tudo bem, {nome}. Vou registrar o cancelamento da sua consulta.\n\n"
            "Só para saber: o que aconteceu? Ficou alguma dúvida ou posso ajudar de outra forma?"
        )
        return [texto, f"_Política de cancelamento: {politica}_"]

    if action == "execute_tool" and plano.get("tool") == "cancelar":
        if resultado_tool and resultado_tool.get("sucesso"):
            return [MSG_CANCELAMENTO_CONFIRMADO]
        return ["Ops! Tive um problema técnico ao registrar o cancelamento 😔\n\n"
                "Vou pedir para a Thaynara verificar manualmente, tudo bem? 💚"]

    if action == "send_confirmacao_cancelamento":
        return [MSG_CANCELAMENTO_CONFIRMADO]

    # ── Detectar tipo de remarcação ───────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "detectar_tipo_remarcacao":
        if resultado_tool and resultado_tool.get("tipo_remarcacao") == "retorno":
            ca = resultado_tool.get("consulta_atual")
            if ca:
                try:
                    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
                    _BRT = _tz(_td(hours=-3))
                    dt = _dt.fromisoformat(ca["inicio"])
                    if dt.tzinfo:
                        dt = dt.astimezone(_BRT)
                    data_fmt = dt.strftime("%d/%m/%Y")
                    hora_fmt = dt.strftime("%Hh")
                    return [
                        f"Vi aqui que sua consulta está agendada para *{data_fmt}* às *{hora_fmt}* "
                        f"({cd.get('modalidade') or 'presencial'}) 📅\n\n"
                        "Posso remarcar para outro horário! Quais são os melhores dias e horários para você?"
                    ]
                except Exception:
                    pass
            return [f"Tudo bem, {nome}. Podemos remarcar sim, sem problema 😊\n\n"
                    "Quais são os melhores horários e dias para você? 📅"]
        # nova_consulta ou não encontrado
        return [
            "Não localizei um agendamento confirmado para você 😊\n"
            "Vou te passar para o fluxo de agendamento — me conta o que você está procurando!"
        ]

    # ── Perda de janela de remarcação ─────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "perda_retorno":
        return [
            "Infelizmente não conseguimos encontrar um horário dentro do prazo de remarcação 😔\n\n"
            "Como o prazo se encerrou, o retorno não poderá mais ser remarcado.\n\n"
            "Mas posso te ajudar a agendar uma nova consulta! Quer que eu verifique os planos? 💚"
        ]

    # ── Resposta a dúvida do KB ───────────────────────────────────────────────
    if action == "answer_question":
        draft = plano.get("draft_message")
        if draft:
            return [draft]
        return [_answer_from_kb(plano["ask_context"], cd)]

    # ── Escalação ─────────────────────────────────────────────────────────────
    if action == "escalate":
        # Sentinel detectado pelo router — ele chama escalar_para_humano()
        return [{"_meta_action": "escalate"}]

    # ── Remarketing recusa ────────────────────────────────────────────────────
    if action == "handle_remarketing_refusal":
        return [MSG_ENCERRAMENTO_REMARKETING]

    # ── Fora de contexto ──────────────────────────────────────────────────────
    if action == "respond_fora_de_contexto":
        draft = plano.get("draft_message")
        if draft:
            return [draft]
        return [MSG_FORA_CONTEXTO]

    # ── Redirect (sem resposta — Engine re-planeja) ───────────────────────────
    if action in ("redirect_retencao", "redirect_atendimento"):
        return []

    # ── Ações intermediárias (sem resposta direta) ────────────────────────────
    if action in ("apply_upgrade", "slot_confirmed", "pagamento_confirmado"):
        return []

    # ── Fallback: resposta livre via LLM ─────────────────────────────────────
    return [await _resposta_livre(state)]


# ── Builders internos ─────────────────────────────────────────────────────────


def _ask_field(campo: str, nome: str, state: dict) -> list:
    if campo == "nome":
        history = state.get("history", [])
        if len(history) <= 1:
            return [MSG_BOAS_VINDAS]
        return [
            "Antes de continuar, pode me informar seu *nome completo* "
            "e se é sua *primeira consulta* ou se você *já é paciente*? 😊"
        ]
    if campo == "status_paciente":
        return [
            f"Obrigada, {nome.split()[0] if nome else ''}! 😊\n\n"
            "É sua primeira consulta com a Thaynara ou você já é paciente?"
        ]
    if campo == "objetivo":
        primeiro_nome = nome.split()[0] if nome else nome
        return [_build_objetivo_list(primeiro_nome)]
    if campo == "plano":
        return [
            "Qual plano faz mais sentido pra você?\n\n"
            "👉 Consulta única\n"
            "👉 Consulta com retorno\n"
            "👉 Plano Ouro\n"
            "👉 Plano Premium\n"
            "👉 Dieta por formulário"
        ]
    if campo == "modalidade":
        return [
            "Prefere o atendimento *presencial* (Aura Clinic — Vespasiano/MG) "
            "ou *online* (videochamada pelo WhatsApp)? 😊"
        ]
    if campo in ("preferencia_horario", "preferencia_horario_remarcar"):
        return [MSG_PREFERENCIA_HORARIO]
    return [f"Pode me informar {campo}? 😊"]


def _build_upsell_msg(plano: str, modalidade: str) -> str:
    if plano == "unica":
        return MSG_UPSELL["unica"].format(
            valor_ouro=kb.get_valor("ouro", "presencial"),
            valor_ouro_online=kb.get_valor("ouro", "online"),
        )
    if plano == "com_retorno":
        diff = kb.get_valor("ouro", modalidade) - kb.get_valor("com_retorno", modalidade)
        return MSG_UPSELL["com_retorno"].format(diff=diff)
    if plano == "ouro":
        return MSG_UPSELL["ouro"].format(valor_premium=kb.get_valor("premium", "presencial"))
    return ""


def _build_forma_pagamento(cd: dict, nome: str) -> str:
    plano_key = cd.get("plano") or "unica"
    modal = cd.get("modalidade") or "presencial"
    plano_dados = kb.get_plano(plano_key) or {}
    valor = kb.get_valor(plano_key, modal)
    parcelas = kb.get_parcelas(plano_key)
    parcela = plano_dados.get(f"parcela_{modal}", valor / max(parcelas, 1))
    return MSG_FORMA_PAGAMENTO.format(
        nome=nome,
        plano_nome=plano_dados.get("nome", plano_key),
        modalidade=modal,
        valor=valor,
        sinal=valor * 0.5,
        parcelas=parcelas,
        parcela=parcela,
    )


def _build_confirmacao(state: dict) -> list:
    cd = state["collected_data"]
    appt = state["appointment"]
    slot = appt.get("slot_escolhido") or {}
    nome = cd.get("nome") or ""
    data = slot.get("data_fmt", "")
    hora = slot.get("hora", "")
    modal = cd.get("modalidade") or "presencial"

    if modal == "online":
        return [
            MSG_CONFIRMACAO_ONLINE.format(nome=nome, data=data, hora=hora),
            {"media_type": "image", "media_key": "img_preparo_online",
             "caption": "Como se preparar para a consulta online"},
            {"media_type": "document", "media_key": "pdf_guia_circunf_mulher",
             "caption": "Guia de medidas corporais"},
            f"Contato da nutricionista: {kb.contatos['numero_nutri_publico']}",
            "Não esquece de mandar a foto e as medidas no número da Nutri 💚",
        ]
    return [
        MSG_CONFIRMACAO_PRESENCIAL.format(nome=nome, data=data, hora=hora),
        {"media_type": "image", "media_key": "img_preparo_presencial",
         "caption": "Como se preparar para a consulta presencial"},
    ]


def _answer_from_kb(topico: str, cd: dict) -> str:
    plano = cd.get("plano")
    modal = cd.get("modalidade")
    if topico == "pagamento":
        if plano and modal:
            plano_dados = kb.get_plano(plano) or {}
            valor = kb.get_valor(plano, modal)
            parcelas = kb.get_parcelas(plano)
            parcela = plano_dados.get(f"parcela_{modal}", valor / max(parcelas, 1))
            return (
                f"*{plano_dados.get('nome', plano)}* ({modal}):\n"
                f"• PIX com desconto: *R${valor:.0f}*\n"
                f"• Cartão: *{parcelas}x de R${parcela:.0f}*\n\n"
                f"Política: {kb.get_politica('pagamento')}"
            )
        return kb.get_politica("pagamento")
    if topico == "modalidade":
        return (
            "Funciona assim 😊\n\n"
            "• *Presencial*: consulta na Aura Clinic, em Vespasiano\n"
            "• *Online*: videochamada pelo WhatsApp no horário agendado"
        )
    if topico == "politica":
        return (
            f"Pagamento: {kb.get_politica('pagamento')}\n\n"
            f"Remarcação/cancelamento: {kb.get_politica('cancelamento')}"
        )
    if topico == "planos":
        return kb.resumo_planos_texto()
    return "Posso te ajudar com agendamentos e informações sobre as consultas 💚"


def _build_slot_buttons(slots: list, aviso: str = "") -> dict:
    """Retorna dict de mensagem interativa com botões para escolha de slot."""
    body_parts = []
    if aviso:
        body_parts.append(aviso)
    body_parts.append("Qual horário funciona melhor pra você?")
    return {
        "_interactive": "button",
        "body": "\n\n".join(body_parts),
        "buttons": [
            {"id": f"slot_{i+1}", "title": f"{s['data_fmt']} {s['hora']}"}
            for i, s in enumerate(slots[:3])
        ],
    }


def _build_forma_pagamento_interactive(cd: dict, nome: str) -> dict:
    """Retorna dict de mensagem interativa com botões PIX / Cartão."""
    plano_key = cd.get("plano") or "unica"
    modal = cd.get("modalidade") or "presencial"
    plano_dados = kb.get_plano(plano_key) or {}
    valor = kb.get_valor(plano_key, modal)
    parcelas = kb.get_parcelas(plano_key)
    parcela = plano_dados.get(f"parcela_{modal}", valor / max(parcelas, 1))
    body = (
        f"Perfeito, {nome}! 😊\n\n"
        f"Para confirmar seu agendamento, é necessário o pagamento antecipado. "
        f"Essa é uma política da clínica — garante que seu horário fique reservado exclusivamente pra você 💚\n\n"
        f"*{plano_dados.get('nome', plano_key)}* ({modal}):\n"
        f"• PIX com desconto: *R${valor:.0f}* (sinal de 50%: *R${valor * 0.5:.0f}*)\n"
        f"• Cartão: *{parcelas}x de R${parcela:.0f}* sem juros (valor integral)\n\n"
        f"Qual opção prefere?"
    )
    return {
        "_interactive": "button",
        "body": body,
        "buttons": [
            {"id": "pix", "title": "PIX"},
            {"id": "cartao", "title": "Cartão de crédito"},
        ],
    }


def _build_objetivo_list(nome: str) -> dict:
    """Retorna dict de mensagem interativa com lista de objetivos."""
    return {
        "_interactive": "list",
        "body": (
            f"Ótimo, {nome}! 😊\n\n"
            "Me conta: qual é o seu principal objetivo com o acompanhamento nutricional?"
        ),
        "button_label": "Meu objetivo",
        "rows": [
            {"id": "emagrecer",    "title": "Emagrecer"},
            {"id": "ganhar_massa", "title": "Ganhar massa"},
            {"id": "lipedema",     "title": "Tratar lipedema"},
            {"id": "outro",        "title": "Outro objetivo"},
        ],
    }


async def _resposta_livre(state: dict) -> str:
    """LLM fallback para casos não cobertos pelos templates."""
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    history_clean = sanitize_historico(state.get("history", [])[-10:])
    msgs = [{"role": m["role"], "content": m["content"]} for m in history_clean]
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=kb.system_prompt(),
            messages=msgs,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Erro LLM resposta livre: %s", e)
        return "Desculpa, tive um problema técnico. Pode repetir? 😊"
