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
import re

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
    "ajustes constantes e resultados sustentáveis, sem dietas extremas nem recomeços frustrantes."
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

MSG_PREFERENCIA_REMARCAR = (
    "Claro, sem problema. Vou tentar te ajudar com isso 😊\n\n"
    "Você prefere algum dia ou período da semana?"
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

MSG_CADASTRO = (
    "Excelente, {nome}! 😊\n\n"
    "Para finalizar seu cadastro e garantir o horário, me envie por favor:\n"
    "• Nome completo\n"
    "• Data de nascimento\n"
    "• WhatsApp para contato\n"
    "• E-mail\n"
    "• Instagram (se tiver)\n"
    "• Profissão\n"
    "• CEP e endereço completo\n"
    "• Se chegou por indicação ou por onde conheceu a Thaynara"
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
    "📍 *Local:* Videochamada pelo WhatsApp (a nutri irá te ligar no número cadastrado)\n"
    "✅ Certifique-se de ter uma boa conexão de internet.\n\n"
    "Políticas importantes:\n"
    "⏱️ Tolerância máxima de atraso: 10 minutos.\n"
    "🔄 Reagendar/cancelar: informar com 24h de antecedência.\n"
    "🚫 Não comparecimento: consulta considerada realizada, sem reembolso.\n\n"
    "💚 Obrigada pela confiança! Estamos te esperando."
)

MSG_CONFIRMACAO_REMARCACAO = (
    "Prontinho, sua consulta foi remarcada com sucesso ✅\n\n"
    "📅 *Nova data:* {data} às {hora}\n"
    "📍 *Modalidade:* {modalidade}\n\n"
    "Qualquer imprevisto, me chama por aqui 💚"
)

MSG_CANCELAMENTO_CONFIRMADO = (
    "Consulta cancelada com sucesso ✅\n\n"
    "Quando quiser retomar o acompanhamento, é só me chamar aqui! "
    "A Thaynara vai adorar te receber 💚"
)

MSG_ERRO_AGENDAMENTO = (
    "Ops! Tive um problema técnico ao confirmar seu agendamento no sistema 😔\n\n"
    "Vou acionar nossa equipe para verificar. "
    "Você receberá uma confirmação assim que estiver tudo certo 💚"
)

MSG_ERRO_REMARCACAO = (
    "Ops! Tive um problema técnico ao tentar confirmar a remarcação 😔\n\n"
    "Vou acionar nossa equipe para verificar e te retorno por aqui 💚"
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
        # Campos com UI interativa/operacional — sempre usar template (ignorar draft)
        if ask_context in ("objetivo", "plano", "modalidade", "preferencia_horario"):
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
            _build_planos_list(),
        ]

    # ── Upsell ────────────────────────────────────────────────────────────────
    if action == "offer_upsell":
        return [_build_upsell_msg(plano["ask_context"], cd.get("modalidade") or "presencial")]

    # ── Consultar slots ───────────────────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") in ("consultar_slots", "consultar_slots_remarcar"):
        if resultado_tool and resultado_tool.get("slots"):
            slots = resultado_tool["slots"]
            aviso = resultado_tool.get("aviso_preferencia", "")
            if plano.get("tool") == "consultar_slots_remarcar":
                intro = plano.get("draft_message") or "Olhei aqui e encontrei estas opções para remarcar:"
                return [intro, _build_slot_buttons(slots, aviso)]
            intro = plano.get("draft_message") or random.choice(_WAITING)
            return [intro, _build_slot_buttons(slots, aviso)]
        if plano.get("tool") == "consultar_slots_remarcar":
            return [
                "Poxa, não encontrei um horário disponível dentro dessa janela 😕\n\n"
                "Vou verificar uma alternativa com a Thaynara e te retorno por aqui."
            ]
        return [MSG_SEM_HORARIOS]

    # ── Escolha de slot / pede escolha ────────────────────────────────────────
    if action == "ask_slot_choice":
        slots = state.get("last_slots_offered", [])
        if not slots:
            return [MSG_SEM_HORARIOS]
        draft = plano.get("draft_message")
        intro = draft if draft else "Pode me dizer qual horário prefere? 😊"
        return [intro, _build_slot_buttons(slots)]

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
        if resultado_tool and resultado_tool.get("erro") == "cadastro_incompleto":
            campos = resultado_tool.get("campos_pendentes") or []
            if "data_nascimento" in campos:
                return ["Recebi seus dados, mas fiquei com dúvida na *data de nascimento*. Pode me mandar novamente no formato DD/MM/AAAA, por favor?"]
            if "email" in campos:
                return ["Recebi seus dados, mas preciso confirmar seu *e-mail* para cadastro. Pode me mandar novamente, por favor?"]
            if "nome" in campos:
                return ["Recebi seus dados, mas preciso confirmar seu *nome e sobrenome* para cadastro. Pode me mandar novamente, por favor?"]
        if resultado_tool and resultado_tool.get("sucesso"):
            return [random.choice(_WAITING)] + _build_confirmacao(state)
        return [{"_meta_action": "escalate", "motivo": "erro_agendamento"}]

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
        return [{"_meta_action": "escalate", "motivo": "erro_remarcacao"}]

    if action == "send_confirmacao_remarcacao":
        slot = state["appointment"].get("slot_escolhido") or {}
        return [MSG_CONFIRMACAO_REMARCACAO.format(
            data=slot.get("data_fmt", ""),
            hora=slot.get("hora", ""),
            modalidade=cd.get("modalidade") or "presencial",
        )]

    # ── Abandonar processo (desistir sem consulta agendada) ──────────────
    if action == "abandon_process":
        draft = plano.get("draft_message")
        if draft:
            return [draft]
        return [
            "Tudo bem, sem problemas! 😊\n\n"
            "Se mudar de ideia ou tiver alguma dúvida, "
            "é só me chamar aqui. A Thaynara vai adorar te receber 💚"
        ]

    if action == "ask_motivo_cancelamento":
        draft = plano.get("draft_message")
        texto = draft if draft else (
            f"Tudo bem, {nome}. Vou registrar o cancelamento da sua consulta.\n\n"
            "Só para saber: o que aconteceu? Ficou alguma dúvida ou posso ajudar de outra forma?"
        )
        # Só envia política para quem TEM consulta agendada
        appt = state.get("appointment", {})
        tem_consulta = bool(appt.get("id_agenda") or appt.get("consulta_atual"))
        if tem_consulta:
            politica = kb.get_politica("cancelamento")
            return [texto, f"_Política de cancelamento: {politica}_"]
        return [texto]

    if action == "execute_tool" and plano.get("tool") == "cancelar":
        if resultado_tool and resultado_tool.get("sucesso"):
            return [MSG_CANCELAMENTO_CONFIRMADO]
        return [{"_meta_action": "escalate", "motivo": "erro_cancelamento"}]

    if action == "send_confirmacao_cancelamento":
        return [MSG_CANCELAMENTO_CONFIRMADO]

    # ── Detectar tipo de remarcação ───────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "detectar_tipo_remarcacao":
        if state.get("goal") == "cancelar":
            if resultado_tool and resultado_tool.get("consulta_atual"):
                return [
                    "Vi aqui sua consulta agendada. Posso cancelar pra você, sim.\n\n"
                    "Só para registrar direitinho: o que aconteceu?"
                ]
            return [
                "Não localizei um agendamento confirmado para você 😊\n"
                "Se você tiver agendado por outro número, me envie o nome completo ou o e-mail cadastrado para eu conferir."
            ]
        if resultado_tool and resultado_tool.get("tipo_remarcacao") == "retorno":
            ca = resultado_tool.get("consulta_atual")
            fim_janela_str = resultado_tool.get("fim_janela") or state.get("fim_janela_remarcar")
            if ca:
                try:
                    from datetime import datetime as _dt, date as _date, timezone as _tz, timedelta as _td
                    _BRT = _tz(_td(hours=-3))
                    dt = _dt.fromisoformat(ca["inicio"])
                    if dt.tzinfo:
                        dt = dt.astimezone(_BRT)
                    data_fmt = dt.strftime("%d/%m/%Y")
                    hora_fmt = dt.strftime("%Hh")
                    modalidade_fmt = ca.get("modalidade") or "presencial"
                    nome = state.get("nome") or ""
                    primeiro_nome = nome.split()[0] if nome else ""
                    fim_janela_fmt = None
                    if fim_janela_str:
                        try:
                            _DIAS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
                            fj = _date.fromisoformat(fim_janela_str)
                            fim_janela_fmt = _DIAS_PT[fj.weekday()] + ", " + fj.strftime("%d/%m")
                        except Exception:
                            pass
                    intro = ("Tudo bem, " + primeiro_nome + "! Podemos remarcar sim, sem problema 😊\n\n") if primeiro_nome else "Podemos remarcar sim, sem problema 😊\n\n"
                    consulta_info = "Vi aqui sua consulta de *" + data_fmt + "* às *" + hora_fmt + "* (" + modalidade_fmt + ").\n\n"
                    aviso = (
                        "Só queria te orientar que no momento a agenda da Thaynara está bem cheia.\n"
                        "Se você conseguir manter o horário agendado, seria ótimo para não prejudicar\n"
                        "seu acompanhamento 💚\n\n"
                    )
                    if fim_janela_fmt:
                        prazo = (
                            "Caso realmente não consiga, podemos remarcar, até *" + fim_janela_fmt + "*\n"
                            "— esse é o prazo máximo para remarcação.\n\n"
                        )
                    else:
                        prazo = ""
                    pergunta = "Quais são os melhores horários e dias para você? 📅"
                    return [intro + consulta_info + aviso + prazo + pergunta]
                except Exception:
                    pass
            return [
                "Claro, sem problema. Vou tentar te ajudar com isso 😊\n\n"
                "Você prefere algum dia ou período da semana?"
            ]
        if resultado_tool and resultado_tool.get("precisa_identificacao"):
            return [
                "Tentei localizar sua consulta pelo número do WhatsApp, mas não encontrei um agendamento confirmado vinculado a ele.\n\n"
                "Pode me informar seu *nome completo* ou o *e-mail cadastrado* para eu tentar localizar por outro dado?"
            ]
        # nova_consulta ou não encontrado
        return [
            "Não localizei um agendamento confirmado para você 😊\n"
            "Se você tiver agendado por outro número, me envie o nome completo ou o e-mail cadastrado para eu conferir."
        ]

    # ── Perda de janela de remarcação ─────────────────────────────────────────
    if action == "execute_tool" and plano.get("tool") == "perda_retorno":
        return [
            "Entendo. Como não encontramos um horário dentro do prazo de remarcação do retorno, "
            "não consigo remarcar essa consulta como retorno 😕\n\n"
            "Mas posso te ajudar a ver uma nova consulta com a Thaynara e tentar achar "
            "um horário bom pra você. Posso te mandar os planos."
        ]

    # ── Resposta a dúvida do KB ───────────────────────────────────────────────
    if action == "answer_question":
        draft = plano.get("draft_message")
        if draft:
            return [draft]
        last_user = next(
            (m["content"] for m in reversed(state.get("history", [])) if m["role"] == "user"),
            "",
        )
        faq_answer = _answer_faq_from_message(last_user)
        if faq_answer:
            return [faq_answer]
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
            "Antes de continuar, pode me informar seu *nome e sobrenome* "
            "e se é sua *primeira consulta* ou se você *já é paciente*? 😊"
        ]
    if campo == "status_paciente":
        return [
            f"Obrigada, {nome.split()[0] if nome else ''}! 😊\n\n"
            "É sua primeira consulta com a Thaynara ou você já é paciente?"
        ]
    if campo == "cadastro":
        primeiro_nome = nome.split()[0] if nome else "você"
        return [MSG_CADASTRO.format(nome=primeiro_nome)]
    if campo == "objetivo":
        primeiro_nome = nome.split()[0] if nome else nome
        return [_build_objetivo_list(primeiro_nome)]
    if campo == "plano":
        return [_build_planos_list()]
    if campo == "modalidade":
        return [_build_modalidade_list()]
    if campo == "preferencia_horario_remarcar":
        return [MSG_PREFERENCIA_REMARCAR]
    if campo == "preferencia_horario":
        return [MSG_PREFERENCIA_HORARIO]
    if campo == "data_nascimento":
        return ["Recebi seus dados, mas você pode mandar novamente sua *data de nascimento* no formato DD/MM/AAAA, por favor?"]
    if campo == "email":
        return ["Recebi seus dados, mas você pode mandar novamente seu *e-mail* para cadastro, por favor?"]
    if campo == "telefone_contato":
        opcoes = state.get("flags", {}).get("telefone_opcoes") or []
        if opcoes:
            linhas = "\n".join(f"• {opcao}" for opcao in opcoes)
            return [
                "Recebi mais de um telefone na sua mensagem.\n\n"
                f"{linhas}\n\n"
                "Qual deles devo usar como WhatsApp de contato para o cadastro?"
            ]
        return ["Pode me informar o *WhatsApp de contato* para o cadastro, por favor?"]
    if campo == "identificacao_remarcacao":
        return [
            "Para eu tentar localizar sua consulta, me envie por favor seu *nome completo* ou o *e-mail cadastrado*."
        ]
    if campo == "instagram":
        return ["Se você tiver, pode me informar seu *Instagram*?"]
    if campo == "profissao":
        return ["Pode me informar sua *profissão*?"]
    if campo == "cep_endereco":
        return ["Pode me informar seu *CEP e endereço completo*?"]
    if campo == "indicacao_origem":
        return ["Você chegou até a Thaynara por indicação de alguém? Se não, por onde conheceu o trabalho dela?"]
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
        return "Aqui estão os planos:\n\n" + kb.resumo_planos_texto()
    return "Posso te ajudar com agendamentos e informações sobre as consultas 💚"


def _normalize_question(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[?!.,:;*_\-]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _answer_faq_from_message(message: str) -> str | None:
    """Tenta responder pergunta específica diretamente do FAQ estático/minerado."""
    pergunta = _normalize_question(message)
    if not pergunta:
        return None

    for item in kb.faq_combinado():
        faq_q = _normalize_question(item.get("pergunta", ""))
        if not faq_q:
            continue
        if pergunta == faq_q or pergunta in faq_q or faq_q in pergunta:
            return item.get("resposta")
    return None


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


def _build_planos_list() -> dict:
    """Retorna dict de mensagem interativa com a lista curta de planos."""
    return {
        "_interactive": "list",
        "body": "Hoje temos estas opções. Qual faz mais sentido pra você agora?",
        "button_label": "Ver opções",
        "rows": [
            {"id": "premium", "title": "Premium - 6 consultas"},
            {"id": "ouro", "title": "Ouro - 3 consultas"},
            {"id": "com_retorno", "title": "Consulta com retorno"},
            {"id": "unica", "title": "Consulta individual"},
        ],
    }


def _build_modalidade_list() -> dict:
    """Retorna dict de mensagem interativa com as modalidades."""
    return {
        "_interactive": "button",
        "body": "Vamos definir a modalidade: como você prefere fazer sua consulta com a Thaynara?",
        "buttons": [
            {"id": "presencial", "title": "Presencial"},
            {"id": "online", "title": "Online"},
        ],
    }


_RESPOSTA_LIVRE_GUARDRAIL = """\
Você é a Ana, assistente de agendamentos da nutricionista Thaynara Teixeira.

REGRAS OBRIGATÓRIAS:
- NUNCA confirme agendamento, remarcação ou cancelamento. Essas ações só podem ser feitas pelo sistema.
- NUNCA invente datas, horários, links de pagamento ou chaves PIX.
- NUNCA envie política de cancelamento/remarcação por conta própria.
- NUNCA diga "sua consulta foi confirmada/remarcada/cancelada".
- Se não souber o que responder, pergunte como pode ajudar.
- Tom informal, acolhedor, máx 3 linhas. Emojis com moderação.
- Você só pode: tirar dúvidas gerais, pedir que o paciente repita, ou redirecionar para o fluxo de agendamento.
"""


async def _resposta_livre(state: dict) -> str:
    """LLM fallback para casos não cobertos pelos templates."""
    if os.environ.get("DISABLE_LLM_FOR_TESTS") == "true":
        return "Posso te ajudar com agendamentos e informações sobre as consultas. Como posso te ajudar? 😊"

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    history_clean = sanitize_historico(state.get("history", [])[-6:])
    msgs = [{"role": m["role"], "content": m["content"]} for m in history_clean]
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=[
                {
                    "type": "text",
                    "text": _RESPOSTA_LIVRE_GUARDRAIL,
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            messages=msgs,
        )
        text = response.content[0].text.strip()
        # Guardrail pós-geração: bloquear respostas que parecem confirmações
        _BLOCKED_PATTERNS = (
            "consulta foi confirmada", "consulta confirmada com sucesso",
            "remarcada com sucesso", "cancelada com sucesso",
            "✅ Consulta", "✅ *Consulta",
        )
        if any(p in text for p in _BLOCKED_PATTERNS):
            logger.warning("Resposta livre bloqueada (alucinação): %s", text[:100])
            return "Posso te ajudar com agendamentos e informações sobre as consultas. Como posso te ajudar? 😊"
        return text
    except Exception as e:
        logger.error("Erro LLM resposta livre: %s", e)
        return "Desculpa, tive um problema técnico. Pode repetir? 😊"
