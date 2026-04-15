"""
Agente 1 — Atendimento Geral

Fluxo completo de 10 etapas:
  1. boas_vindas        — coleta nome e status (novo / retorno)
  2. qualificacao       — objetivo do paciente
  3. apresentacao_planos — envia PDF + resumo dos planos
  4. escolha_plano      — confirma escolha + upsell único
  5. agendamento        — consulta Dietbox, oferece 3 opções de horário
  6. forma_pagamento    — PIX ou cartão
  7. pagamento          — PIX: chave CPF | Cartão: link Mercado Pago
  8. cadastro_dietbox   — cadastra + agenda no Dietbox
  9. confirmacao        — envia arquivos de preparação (presencial/online)
  10. finalizacao       — altera etiqueta para OK
"""
from __future__ import annotations

import logging
import os
import random
from datetime import datetime, date, timedelta, timezone

import anthropic

from app.agents.dietbox_worker import (
    consultar_slots_disponiveis,
    processar_agendamento,
)
from app.agents.rede_worker import gerar_link_pagamento
from app.knowledge_base import kb
from app.pii_sanitizer import sanitize_historico
from app.tags import Tag

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

# ── Stages do fluxo ──────────────────────────────────────────────────────────

ETAPAS = [
    "boas_vindas",
    "qualificacao",
    "apresentacao_planos",
    "escolha_plano",
    "agendamento",
    "forma_pagamento",
    "pagamento",
    "cadastro_dietbox",
    "confirmacao",
    "finalizacao",
]

# ── Mensagens fixas ──────────────────────────────────────────────────────────

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
    "Dá uma olhadinha com calma e me responde: qual modalidade faz mais sentido pra você agora?"
)

MSG_UPSELL = {
    "unica": (
        "Ótima escolha! Só pra você comparar: o *Plano Ouro* tem 3 consultas + 130 dias de acompanhamento "
        "por R${valor_upgrade:.0f} presencial (ou R${valor_upgrade_online:.0f} online) — "
        "o valor por consulta fica bem mais em conta e você tem muito mais suporte! 💚 "
        "Prefere manter a Consulta Única ou o Plano Ouro faz mais sentido pra você?"
    ),
    "com_retorno": (
        "Ótima escolha! Vale mencionar que o *Plano Ouro* tem 3 consultas + 130 dias de acompanhamento "
        "por apenas +R${diff:.0f}. Mais consultas, mais suporte e a Lilly inclusa! "
        "Prefere manter a Consulta com Retorno ou o Plano Ouro faz mais sentido?"
    ),
    "ouro": (
        "Ótima escolha! Só pra você saber: o *Plano Premium* dobra as consultas (6 no total), "
        "270 dias de acompanhamento, encontros coletivos e a Lilly — nossa assistente virtual "
        "que te ajuda com substituições de alimentos na hora que precisar, mantendo seu plano sempre ajustado! "
        "Fica por R${valor_upgrade:.0f} presencial. Vale muito a pena! "
        "Prefere manter o Ouro ou o Premium faz mais sentido?"
    ),
}

MSG_AGENDAMENTO_OPCOES = (
    "Ótimo! Vou verificar os horários disponíveis agora... 📅\n\n"
    "Tenho essas opções para {modalidade}:\n\n"
    "{opcoes}\n\n"
    "Qual horário funciona melhor pra você?"
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

MSG_PIX_1 = "Segue a chave PIX para pagamento:"
MSG_PIX_2 = "CPF: *{chave_pix}*"
MSG_PIX_3 = (
    "Valor do sinal (50%): *R${sinal:.0f}*\n\n"
    "Assim que concluir, me manda o comprovante pra eu confirmar tudo e enviar as demais informações 😊"
)

MSG_CARTAO = (
    "Claro! Segue o link para pagamento seguro via cartão 💳\n\n"
    "{link}\n\n"
    "{parcelas}x de R${parcela:.0f}. "
    "Após confirmar o pagamento, a consulta fica garantida!"
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

MSG_CONFIRMACAO_ONLINE_MEDIDAS = (
    "Não esquece de mandar a foto e as medidas no número da Nutri, por favor. "
    "Elas são muito importantes na realização da consulta. Obrigadaaa 💚"
)

MSG_FINALIZACAO = (
    "Pronto! Tudo certo, {nome} 💚\n\n"
    "Você receberá uma mensagem de lembrete 24h antes da consulta.\n"
    "Qualquer dúvida, é só me chamar aqui. Até lá! 🌿"
)

# ── Waiting indicators — exibidos antes de operações demoradas (D-21) ─────────

_WAITING_MESSAGES = [
    "Um instante, por favor 💚",
    "Só um minutinho, já verifico pra você 💚",
    "Aguarda um instante que já te respondo 💚",
]

MSG_SEM_HORARIOS = (
    "Poxa, não encontrei horários disponíveis nos próximos dias úteis. "
    "Mas não se preocupa! Deixa eu verificar opções com a Thaynara e "
    "já te retorno com as disponibilidades 🔍"
)

MSG_ERRO_PAGAMENTO = (
    "Ops, tive um problema ao gerar o link de pagamento 😕 "
    "Me dá um instante e vou verificar. Se preferir, o PIX funciona direto: "
    f"chave CPF *{kb.contatos['pix_chave']}*"
)


# ── Motor de resposta via LLM ─────────────────────────────────────────────────

def _gerar_resposta_llm(
    historico: list[dict],
    etapa: str,
    contexto_extra: str = "",
) -> str:
    """
    Usa Claude Haiku para gerar resposta livre dentro da etapa atual.
    Usado quando a resposta fixa não cobre o caso (ex: objeção, dúvida inesperada).
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    system = kb.system_prompt() + f"\n\n## Etapa atual do fluxo: {etapa}\n{contexto_extra}"

    # LGPD: sanitizar PII antes de enviar ao LLM (META-04)
    historico_limpo = sanitize_historico(historico[-10:])
    msgs = [{"role": m["role"], "content": m["content"]} for m in historico_limpo]

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=system,
            messages=msgs,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Erro LLM em etapa %s: %s", etapa, e)
        return "Desculpa, tive um problema técnico. Pode repetir?"


# ── Classe principal do Agente 1 ──────────────────────────────────────────────

class AgenteAtendimento:
    """
    Gerencia o estado de um atendimento individual.

    O estado é serializado para ser armazenado no banco/Redis entre mensagens.
    """

    def __init__(self, telefone: str, phone_hash: str) -> None:
        self.telefone = telefone
        self.phone_hash = phone_hash

        # Estado persistido
        self.etapa: str = "boas_vindas"
        self.nome: str | None = None
        self.status_paciente: str | None = None   # "novo" | "retorno"
        self.objetivo: str | None = None
        self.plano_escolhido: str | None = None
        self.modalidade: str | None = None        # "presencial" | "online"
        self.upsell_oferecido: bool = False
        self.slot_escolhido: dict | None = None
        self.forma_pagamento: str | None = None   # "pix" | "cartao"
        self.pagamento_confirmado: bool = False
        self.id_paciente_dietbox: int | None = None
        self.id_agenda_dietbox: str | None = None
        self.historico: list[dict] = []

    # ── entrada de mensagem ───────────────────────────────────────────────────

    def processar(self, mensagem_usuario: str) -> list[str]:
        """
        Recebe a mensagem do usuário e retorna lista de respostas a enviar.
        (Múltiplas mensagens = envio sequencial com pausas curtas no caller)
        """
        self.historico.append({"role": "user", "content": mensagem_usuario})
        respostas = self._despachar(mensagem_usuario)
        for r in respostas:
            self.historico.append({"role": "assistant", "content": r})
        return respostas

    def _despachar(self, msg: str) -> list[str]:
        etapa = self.etapa
        msg_lower = msg.lower().strip()

        if etapa == "boas_vindas":
            return self._etapa_boas_vindas(msg)

        if etapa == "qualificacao":
            return self._etapa_qualificacao(msg)

        if etapa == "apresentacao_planos":
            return self._etapa_apresentacao_planos(msg)

        if etapa == "escolha_plano":
            return self._etapa_escolha_plano(msg)

        if etapa == "agendamento":
            return self._etapa_agendamento(msg)

        if etapa == "forma_pagamento":
            return self._etapa_forma_pagamento(msg)

        if etapa == "pagamento":
            return self._etapa_pagamento(msg)

        if etapa == "cadastro_dietbox":
            return self._etapa_cadastro_dietbox(msg)

        if etapa == "confirmacao":
            return self._etapa_confirmacao(msg)

        if etapa == "formulario":
            return self._etapa_formulario_pagamento(msg)

        if etapa == "finalizacao":
            return [MSG_FINALIZACAO.format(nome=self.nome or "")]

        # fallback LLM
        return [_gerar_resposta_llm(self.historico, etapa)]

    # ── etapas ───────────────────────────────────────────────────────────────

    def _etapa_boas_vindas(self, msg: str) -> list[str]:
        """Primeiro contato: envia boas-vindas e aguarda nome."""
        # Tenta extrair nome da mensagem atual
        nome = _extrair_nome(msg)
        if nome:
            self.nome = nome
            status = "retorno" if any(
                w in msg.lower() for w in ["já sou", "já fui", "retorno", "segunda vez", "paciente"]
            ) else "novo"
            self.status_paciente = status
            self.etapa = "qualificacao"
            # Se é a primeira mensagem E tem nome, inclui boas-vindas + pergunta objetivo
            if len(self.historico) <= 1:
                return [MSG_BOAS_VINDAS, MSG_OBJETIVOS.format(nome=self.nome)]
            return [MSG_OBJETIVOS.format(nome=self.nome)]

        # Primeira mensagem sem nome — responde com boas-vindas (pede nome)
        if len(self.historico) <= 1:
            return [MSG_BOAS_VINDAS]

        return [_gerar_resposta_llm(self.historico, "boas_vindas",
                                     "Ainda precisa coletar o nome do paciente.")]

    def _etapa_qualificacao(self, msg: str) -> list[str]:
        self.objetivo = msg[:200]  # salva objetivo bruto
        self.etapa = "apresentacao_planos"
        # Envia: confirmação + [PDF seria enviado aqui] + mensagem sobre planos
        return [
            MSG_PLANOS_INTRO,
            {"media_type": "document", "media_key": "pdf_thaynara", "caption": "Nosso midia kit completo"},
            MSG_PLANOS_RESUMO,
        ]

    def _etapa_apresentacao_planos(self, msg: str) -> list[str]:
        """Identifica o plano de interesse e pergunta modalidade."""
        msg_lower = msg.lower()

        # Captura modalidade mesmo sem plano escolhido
        if "online" in msg_lower:
            self.modalidade = "online"
        elif any(w in msg_lower for w in ["presencial", "pessoal", "clínica", "clinica", "vespasiano"]):
            self.modalidade = "presencial"

        plano = _identificar_plano(msg)
        if plano:
            self.plano_escolhido = plano
            if plano == "formulario":
                self.etapa = "formulario"
                return self._etapa_formulario_explicacao()
            # Se modalidade já conhecida, avança direto
            if self.modalidade:
                self.etapa = "escolha_plano"
                return self._etapa_escolha_plano(msg)
            # Pergunta modalidade
            return [
                f"Ótima escolha! Prefere o atendimento *presencial* (Vespasiano/MG — Aura Clinic) "
                f"ou *online* (videochamada pelo WhatsApp)? 😊"
            ]

        return [_gerar_resposta_llm(self.historico, "apresentacao_planos")]

    def _etapa_formulario_explicacao(self) -> list[str]:
        return [
            "Vou te explicar direitinho como funciona, tá bom? 💚\n\n"
            "A *Dieta por Formulário* é uma opção mais acessível e prática. "
            "Você recebe um plano alimentar personalizado baseado em um formulário bem completo: "
            "rotina, hábitos, preferências e objetivos.\n\n"
            "Além disso:\n"
            "• Pode enviar fotos para análise visual da nutri\n"
            "• Em até 5 dias úteis recebe tudo por e-mail\n"
            "• Pode solicitar ajustes no plano em até 5 dias\n\n"
            "Se você sente que precisa de acompanhamento mais próximo, avaliações detalhadas "
            "e suporte contínuo, a consulta completa (presencial ou online) faz toda a diferença. "
            "A nutri avalia comportamento alimentar, sinais físicos, histórico clínico e acompanha "
            "sua evolução com app exclusivo + check-ins personalizados.\n\n"
            "Hoje você sente que qual plano se encaixa melhor na sua realidade?"
        ]

    def _etapa_escolha_plano(self, msg: str) -> list[str]:
        """Captura modalidade e tenta upsell único."""
        if self.modalidade is None:
            if "online" in msg.lower():
                self.modalidade = "online"
            elif any(w in msg.lower() for w in ["presencial", "pessoal", "clínica", "clinica"]):
                self.modalidade = "presencial"
            else:
                return ["Só confirmando: você prefere *presencial* ou *online*? 😊"]

        # upsell (apenas uma vez)
        if not self.upsell_oferecido and self.plano_escolhido in MSG_UPSELL:
            self.upsell_oferecido = True
            plano = self.plano_escolhido
            modal = self.modalidade

            if plano == "unica":
                msg_up = MSG_UPSELL["unica"].format(
                    valor_upgrade=kb.get_valor("ouro", "presencial"),
                    valor_upgrade_online=kb.get_valor("ouro", "online"),
                )
            elif plano == "com_retorno":
                diff = kb.get_valor("ouro", modal) - kb.get_valor("com_retorno", modal)
                msg_up = MSG_UPSELL["com_retorno"].format(diff=diff)
            else:  # ouro
                msg_up = MSG_UPSELL["ouro"].format(
                    valor_upgrade=kb.get_valor("premium", "presencial"),
                )

            return [msg_up]

        # se upsell foi oferecido, verifica se paciente aceitou upgrade
        if self.upsell_oferecido:
            if any(w in msg.lower() for w in ["premium", "sim", "pode", "vamos", "upgrade", "esse"]):
                upgrades = {"unica": "ouro", "com_retorno": "ouro", "ouro": "premium"}
                self.plano_escolhido = upgrades.get(self.plano_escolhido, self.plano_escolhido)

        self.etapa = "agendamento"
        return self._iniciar_agendamento()

    def _iniciar_agendamento(self) -> list[str]:
        # D-21: waiting indicator antes de chamar Dietbox
        waiting = random.choice(_WAITING_MESSAGES)

        try:
            slots = consultar_slots_disponiveis(
                modalidade=self.modalidade or "presencial",
                dias_a_frente=14,
            )
        except Exception as e:
            logger.error("Erro ao consultar slots: %s", e)
            return [MSG_SEM_HORARIOS]

        if not slots:
            return [MSG_SEM_HORARIOS]

        # D-19: NUNCA oferecer horário no mesmo dia
        hoje_fmt = date.today().strftime("%d/%m/%Y")

        # guarda 3 slots em dias DIFERENTES (excluindo hoje) para o paciente escolher
        dias_usados: set[str] = set()
        selecionados: list[dict] = []
        for slot in slots:
            dia = slot.get("data_fmt", "")
            if dia == hoje_fmt:
                continue  # D-19: não oferecer o dia atual
            if dia not in dias_usados:
                selecionados.append(slot)
                dias_usados.add(dia)
            if len(selecionados) >= 3:
                break

        if not selecionados:
            return [MSG_SEM_HORARIOS]

        self._slots_oferecidos = selecionados
        opcoes = "\n".join(
            f"{i+1}. {s['data_fmt']} às {s['hora']}"
            for i, s in enumerate(self._slots_oferecidos)
        )
        return [
            waiting,
            MSG_AGENDAMENTO_OPCOES.format(
                modalidade=self.modalidade,
                opcoes=opcoes,
            ),
        ]

    def _etapa_agendamento(self, msg: str) -> list[str]:
        slots = getattr(self, "_slots_oferecidos", [])

        # tenta identificar a escolha (1, 2 ou 3)
        escolha = None
        for i, word in enumerate(["1", "primeiro", "2", "segundo", "3", "terceiro"]):
            if word in msg.lower():
                idx = i // 2
                if idx < len(slots):
                    escolha = slots[idx]
                    break

        # se não reconheceu, tenta encontrar data/hora mencionada
        if not escolha and slots:
            for s in slots:
                if s["hora"] in msg or s["data_fmt"] in msg:
                    escolha = s
                    break

        if not escolha:
            if slots:
                opcoes = "\n".join(
                    f"{i+1}. {s['data_fmt']} às {s['hora']}"
                    for i, s in enumerate(slots)
                )
                return [f"Pode me dizer qual horário prefere? 😊\n\n{opcoes}"]
            return [MSG_SEM_HORARIOS]

        self.slot_escolhido = escolha
        self.etapa = "forma_pagamento"

        plano_dados = kb.get_plano(self.plano_escolhido or "unica")
        modal = self.modalidade or "presencial"
        valor = kb.get_valor(self.plano_escolhido or "unica", modal)
        parcelas = kb.get_parcelas(self.plano_escolhido or "unica")
        parcela_key = f"parcela_{modal}"
        parcela = plano_dados.get(parcela_key, valor / parcelas) if plano_dados else valor / parcelas

        return [MSG_FORMA_PAGAMENTO.format(
            nome=self.nome or "",
            plano_nome=plano_dados["nome"] if plano_dados else self.plano_escolhido,
            modalidade=modal,
            valor=valor,
            sinal=valor * 0.5,
            parcelas=parcelas,
            parcela=parcela,
        )]

    def _etapa_forma_pagamento(self, msg: str) -> list[str]:
        msg_lower = msg.lower()
        if "pix" in msg_lower or "transferência" in msg_lower or "transferencia" in msg_lower:
            self.forma_pagamento = "pix"
        elif any(w in msg_lower for w in ["cartão", "cartao", "crédito", "credito", "link"]):
            self.forma_pagamento = "cartao"
        else:
            return ["Pode pagar via *PIX* ou *cartão de crédito* — qual prefere? 😊"]

        self.etapa = "pagamento"
        valor = kb.get_valor(self.plano_escolhido or "unica", self.modalidade or "presencial")

        if self.forma_pagamento == "pix":
            return [
                MSG_PIX_1,
                MSG_PIX_2.format(chave_pix=kb.contatos["pix_chave"]),
                MSG_PIX_3.format(sinal=valor * 0.5),
            ]

        # cartão — D-21: waiting indicator antes de gerar link (operação demorada)
        waiting = random.choice(_WAITING_MESSAGES)
        link_result = gerar_link_pagamento(
            plano=self.plano_escolhido or "unica",
            modalidade=self.modalidade or "presencial",
            referencia=f"{self.phone_hash[:12]}-{datetime.now(BRT).strftime('%Y%m%d%H%M')}",
        )
        if not link_result.sucesso or not link_result.url:
            logger.error("Falha ao gerar link de pagamento: %s", link_result.erro)
            self.forma_pagamento = "pix"
            return [MSG_ERRO_PAGAMENTO]

        return [
            waiting,
            MSG_CARTAO.format(
                link=link_result.url,
                parcelas=link_result.parcelas,
                parcela=link_result.parcela_valor,
            ),
        ]

    def _etapa_pagamento(self, msg: str) -> list[str]:
        """Aguarda confirmação de pagamento (comprovante ou confirmação verbal)."""
        msg_lower = msg.lower()
        confirmado = any(w in msg_lower for w in [
            "paguei", "pago", "feito", "fiz", "enviei", "transferi",
            "confirmado", "ok", "sim", "já paguei",
        ])

        if confirmado or len(msg) > 30:   # comprovante geralmente tem conteúdo
            self.pagamento_confirmado = True
            self.etapa = "cadastro_dietbox"
            return self._etapa_cadastro_dietbox(msg)

        return ["Aguardo o comprovante de pagamento para confirmar sua consulta 😊"]

    def _etapa_cadastro_dietbox(self, _msg: str) -> list[str]:
        """Cadastra paciente e agenda no Dietbox. D-21: waiting indicator antes da operação."""
        if not self.slot_escolhido:
            self.etapa = "agendamento"
            return self._iniciar_agendamento()

        # D-21: waiting indicator antes de chamar Dietbox (operação demorada)
        waiting = random.choice(_WAITING_MESSAGES)

        try:
            dt_str = self.slot_escolhido["datetime"]
            # parse ISO 8601 (ex: "2026-04-10T09:00")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BRT)

            resultado = processar_agendamento(
                dados_paciente={
                    "nome": self.nome or "Paciente",
                    "telefone": self.telefone,
                    "email": "",
                },
                dt_consulta=dt,
                modalidade=self.modalidade or "presencial",
                plano=self.plano_escolhido or "unica",
                valor_sinal=kb.get_valor(self.plano_escolhido or "unica", self.modalidade or "presencial"),
                forma_pagamento=self.forma_pagamento or "pix",
            )

            if resultado["sucesso"]:
                self.id_paciente_dietbox = resultado["id_paciente"]
                self.id_agenda_dietbox = resultado["id_agenda"]
            else:
                logger.error("Dietbox falhou: %s", resultado.get("erro"))

        except Exception as e:
            logger.error("Erro no cadastro Dietbox: %s", e)

        self.etapa = "confirmacao"
        confirmacao = self._etapa_confirmacao(_msg)
        # Prepend waiting indicator (D-21)
        return [waiting] + confirmacao

    def _etapa_confirmacao(self, _msg: str) -> list[str]:
        slot = self.slot_escolhido or {}

        self.etapa = "finalizacao"

        if self.modalidade == "online":
            msgs = [
                MSG_CONFIRMACAO_ONLINE.format(
                    nome=self.nome or "",
                    data=slot.get("data_fmt", ""),
                    hora=slot.get("hora", ""),
                ),
                {"media_type": "image", "media_key": "img_preparo_online", "caption": "Como se preparar para a consulta online"},
                {"media_type": "document", "media_key": "pdf_guia_circunf_mulher", "caption": "Guia de medidas corporais"},
                f"Contato da nutricionista: {kb.contatos['numero_nutri_publico']}",
                MSG_CONFIRMACAO_ONLINE_MEDIDAS,
            ]
        else:
            msgs = [
                MSG_CONFIRMACAO_PRESENCIAL.format(
                    nome=self.nome or "",
                    data=slot.get("data_fmt", ""),
                    hora=slot.get("hora", ""),
                ),
                {"media_type": "image", "media_key": "img_preparo_presencial", "caption": "Como se preparar para a consulta presencial"},
            ]

        return msgs


    def _etapa_formulario_pagamento(self, msg: str) -> list[str]:
        """Fluxo do formulário: aguarda confirmação e envia link."""
        msg_lower = msg.lower()
        confirmado = any(w in msg_lower for w in [
            "paguei", "pago", "feito", "fiz", "enviei", "transferi", "confirmado", "ok", "sim",
        ])
        if confirmado or len(msg) > 30:
            self.pagamento_confirmado = True
            self.etapa = "finalizacao"
            return [
                f"Aqui está o link para preencher o formulário 💚\n\n"
                f"{kb.contatos['formulario_link']}\n\n"
                "Responda todas as perguntas com atenção e sinceridade — elas são a base do seu plano alimentar.\n\n"
                "Por favor, envie no número da nutri fotos de short/top de treino ou biquíni (feminino) "
                "ou bermuda sem camisa (masculino), nas posições de frente, costas e laterais, da cabeça aos pés.\n\n"
                "Assim que recebermos o formulário preenchido, sua dieta será enviada em até 5 dias úteis 💪",
                f"Contato da nutricionista para enviar as fotos: {kb.contatos['numero_nutri_publico']}",
            ]

        # ainda não confirmou — envia dados de pagamento
        return [
            "Para garantir o compromisso, o formulário só é enviado após o pagamento 😊\n\n"
            f"R$ 100 — Chave PIX (CPF): *{kb.contatos['pix_chave']}*\n\n"
            "Feito, me manda o comprovante que retorno com a confirmação e orientações! 👈✅"
        ]


    # ── serialização ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serializa o estado do agente para dict armazenável no Redis."""
        return {
            "_tipo": "atendimento",
            "telefone": self.telefone,
            "phone_hash": self.phone_hash,
            "etapa": self.etapa,
            "nome": self.nome,
            "status_paciente": self.status_paciente,
            "objetivo": self.objetivo,
            "plano_escolhido": self.plano_escolhido,
            "modalidade": self.modalidade,
            "upsell_oferecido": self.upsell_oferecido,
            "slot_escolhido": self.slot_escolhido,
            "forma_pagamento": self.forma_pagamento,
            "pagamento_confirmado": self.pagamento_confirmado,
            "id_paciente_dietbox": self.id_paciente_dietbox,
            "id_agenda_dietbox": self.id_agenda_dietbox,
            "historico": self.historico[-20:],  # T-01-01: máx 20 entradas
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgenteAtendimento":
        """Restaura instância a partir de dict serializado."""
        agent = cls(telefone=data["telefone"], phone_hash=data["phone_hash"])
        agent.etapa = data.get("etapa", "boas_vindas")
        agent.nome = data.get("nome")
        agent.status_paciente = data.get("status_paciente")
        agent.objetivo = data.get("objetivo")
        agent.plano_escolhido = data.get("plano_escolhido")
        agent.modalidade = data.get("modalidade")
        agent.upsell_oferecido = data.get("upsell_oferecido", False)
        agent.slot_escolhido = data.get("slot_escolhido")
        agent.forma_pagamento = data.get("forma_pagamento")
        agent.pagamento_confirmado = data.get("pagamento_confirmado", False)
        agent.id_paciente_dietbox = data.get("id_paciente_dietbox")
        agent.id_agenda_dietbox = data.get("id_agenda_dietbox")
        agent.historico = data.get("historico", [])
        return agent


# ── helpers ───────────────────────────────────────────────────────────────────

def _extrair_nome(msg: str) -> str | None:
    """Extrai primeiro(s) nome(s) da mensagem (heurística simples)."""
    import re
    # Remove saudações comuns
    limpo = re.sub(
        r"^(oi|olá|ola|bom dia|boa tarde|boa noite|tudo bem|tudo bom|meu nome [eé]|me chamo|sou o|sou a|sou)[,!.]*\s*",
        "",
        msg.strip(),
        flags=re.IGNORECASE,
    )
    # Pega palavras capitalizadas no início
    tokens = limpo.strip().split()
    nome_partes = []
    for t in tokens[:3]:
        if t.replace(",", "").replace(".", "").istitle() and len(t) > 2:
            nome_partes.append(t.strip(",.!"))
        else:
            break
    if nome_partes:
        return " ".join(nome_partes)

    # fallback: primeira palavra ORIGINALMENTE capitalizada no texto (nome próprio)
    _NAO_NOMES = {
        "tenho", "quero", "gostaria", "preciso", "estou", "sou", "minha", "meu",
        "para", "sobre", "posso", "fazer", "qual", "como", "quando", "onde",
        "primeira", "segunda", "nova", "nova", "boa", "bom", "tudo", "bem",
    }
    for t in msg.strip().split():
        t_clean = t.strip(",.!?")
        if (len(t_clean) > 2 and t_clean.isalpha()
                and t_clean[0].isupper()
                and t_clean.lower() not in _NAO_NOMES):
            return t_clean
    return None


def _identificar_plano(msg: str) -> str | None:
    """Identifica qual plano o paciente mencionou."""
    msg_lower = msg.lower()
    if "premium" in msg_lower:
        return "premium"
    if "ouro" in msg_lower:
        return "ouro"
    if "retorno" in msg_lower:
        return "com_retorno"
    if "única" in msg_lower or "unica" in msg_lower or "avuls" in msg_lower:
        return "unica"
    if "formulário" in msg_lower or "formulario" in msg_lower:
        return "formulario"
    return None
