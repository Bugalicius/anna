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
from datetime import datetime, timedelta, timezone

import anthropic

from app.agents.dietbox_worker import (
    consultar_slots_disponiveis,
    processar_agendamento,
)
from app.agents.rede_worker import gerar_link_pagamento
from app.knowledge_base import kb
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
    "Olá! Sou a Ana, assistente virtual da nutricionista Thaynara Teixeira 💚\n\n"
    "É um prazer ter você aqui! Antes de começar, pode me dizer seu nome "
    "e se é sua primeira consulta com a Thaynara ou se já é paciente?"
)

MSG_OBJETIVOS = (
    "Que ótimo, {nome}! 😊\n\n"
    "Para te ajudar melhor, qual é o seu principal objetivo agora?\n\n"
    "• Perda de peso\n"
    "• Ganho de massa muscular\n"
    "• Reeducação alimentar\n"
    "• Tratamento de condição específica (diabetes, hipertensão etc.)\n"
    "• Outro objetivo"
)

MSG_PLANOS_RESUMO = (
    "Perfeito! A Thaynara tem planos para diferentes momentos e objetivos 💚\n\n"
    "{planos}\n\n"
    "Posso te enviar o material completo com todos os detalhes. "
    "Qual dessas opções te chamou mais atenção?"
)

MSG_UPSELL = {
    "unica": (
        "Que boa escolha! Só pra você comparar: a *Consulta com Retorno* "
        "inclui um acompanhamento em até 30 dias por apenas +R${diff:.0f} "
        "(R${valor_upgrade:.0f} presencial / R${valor_upgrade_online:.0f} online). "
        "Costuma fazer muita diferença no resultado! Prefere manter a Consulta Única "
        "ou faz sentido investir no retorno?"
    ),
    "com_retorno": (
        "Ótima escolha! Vale mencionar que o *Plano Ouro* inclui suporte via WhatsApp "
        "3x/semana e retorno mensal por +R${diff:.0f}. "
        "Muitas pacientes preferem porque dá muito mais suporte no dia a dia. "
        "Prefere manter a Consulta com Retorno ou o Plano Ouro faz mais sentido?"
    ),
}

MSG_AGENDAMENTO_OPCOES = (
    "Ótimo! Vou verificar os horários disponíveis agora... 📅\n\n"
    "Tenho essas opções para {modalidade}:\n\n"
    "{opcoes}\n\n"
    "Qual horário funciona melhor pra você?"
)

MSG_FORMA_PAGAMENTO = (
    "Show! Vou reservar esse horário para você 😊\n\n"
    "O valor do *{plano_nome}* ({modalidade}) é *R${valor:.2f}* "
    "({parcelas}x de R${parcela:.2f} no cartão).\n\n"
    "Como prefere pagar?\n\n"
    "• *PIX* (aprovação na hora)\n"
    "• *Cartão de crédito* (link de pagamento)"
)

MSG_PIX = (
    "Perfeito! 💚\n\n"
    "Chave PIX (CPF): *{chave_pix}*\n"
    "Valor: *R${valor:.2f}*\n\n"
    "Após o pagamento, me manda o comprovante aqui mesmo e eu confirmo tudo!"
)

MSG_CARTAO = (
    "Claro! Segue o link para pagamento seguro via cartão 💳\n\n"
    "{link}\n\n"
    "Parcele em até {parcelas}x sem juros. "
    "Após confirmar o pagamento, a consulta fica garantida!"
)

MSG_CONFIRMACAO_PRESENCIAL = (
    "🎉 *Consulta confirmada!*\n\n"
    "*Paciente:* {nome}\n"
    "*Data:* {data}\n"
    "*Horário:* {hora}\n"
    "*Modalidade:* Presencial\n"
    "*Plano:* {plano_nome}\n\n"
    "Vou te enviar agora o guia de como se preparar para a consulta presencial 📄"
)

MSG_CONFIRMACAO_ONLINE = (
    "🎉 *Consulta confirmada!*\n\n"
    "*Paciente:* {nome}\n"
    "*Data:* {data}\n"
    "*Horário:* {hora}\n"
    "*Modalidade:* Online (videochamada)\n"
    "*Plano:* {plano_nome}\n\n"
    "Vou te enviar o guia de preparação para consulta online 📄\n"
    "O link da videochamada será enviado no dia da consulta 😊"
)

MSG_FINALIZACAO = (
    "Pronto! Tudo certo, {nome} 💚\n\n"
    "Você receberá uma mensagem de lembrete 24h antes da consulta.\n"
    "Qualquer dúvida, é só me chamar aqui. Até lá! 🌿"
)

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

    msgs = [{"role": m["role"], "content": m["content"]} for m in historico[-10:]]

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

        if etapa == "finalizacao":
            return [MSG_FINALIZACAO.format(nome=self.nome or "")]

        # fallback LLM
        return [_gerar_resposta_llm(self.historico, etapa)]

    # ── etapas ───────────────────────────────────────────────────────────────

    def _etapa_boas_vindas(self, msg: str) -> list[str]:
        """Primeiro contato: envia boas-vindas e aguarda nome."""
        if not self.historico or len(self.historico) <= 1:
            # primeira mensagem — responde com boas-vindas
            return [MSG_BOAS_VINDAS]

        # segunda mensagem — extrai nome
        nome = _extrair_nome(msg)
        if nome:
            self.nome = nome
            status = "retorno" if any(
                w in msg.lower() for w in ["já sou", "já fui", "retorno", "segunda vez", "paciente"]
            ) else "novo"
            self.status_paciente = status
            self.etapa = "qualificacao"
            return [MSG_OBJETIVOS.format(nome=self.nome)]

        return [_gerar_resposta_llm(self.historico, "boas_vindas",
                                     "Ainda precisa coletar o nome do paciente.")]

    def _etapa_qualificacao(self, msg: str) -> list[str]:
        self.objetivo = msg[:200]  # salva objetivo bruto
        self.etapa = "apresentacao_planos"
        planos_txt = kb.resumo_planos_texto()
        resposta = MSG_PLANOS_RESUMO.format(planos=planos_txt)
        return [resposta]

    def _etapa_apresentacao_planos(self, msg: str) -> list[str]:
        """Identifica o plano de interesse e pergunta modalidade."""
        plano = _identificar_plano(msg)
        if plano:
            self.plano_escolhido = plano
            # pergunta modalidade se não foi mencionada
            if "online" in msg.lower():
                self.modalidade = "online"
                self.etapa = "escolha_plano"
                return self._etapa_escolha_plano(msg)
            if any(w in msg.lower() for w in ["presencial", "pessoal", "clínica", "clinica"]):
                self.modalidade = "presencial"
                self.etapa = "escolha_plano"
                return self._etapa_escolha_plano(msg)
            return [
                f"Ótima escolha! Prefere o atendimento *presencial* (Belo Horizonte/MG) "
                f"ou *online* (videochamada)? 😊"
            ]

        return [_gerar_resposta_llm(self.historico, "apresentacao_planos")]

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
                diff = kb.get_valor("com_retorno", modal) - kb.get_valor("unica", modal)
                msg_up = MSG_UPSELL["unica"].format(
                    diff=diff,
                    valor_upgrade=kb.get_valor("com_retorno", "presencial"),
                    valor_upgrade_online=kb.get_valor("com_retorno", "online"),
                )
            else:  # com_retorno
                diff = kb.get_valor("ouro", modal) - kb.get_valor("com_retorno", modal)
                msg_up = MSG_UPSELL["com_retorno"].format(diff=diff)

            return [msg_up]

        # se upsell foi oferecido, verifica se paciente aceitou upgrade
        if self.upsell_oferecido and self.plano_escolhido in ("unica", "com_retorno"):
            if any(w in msg.lower() for w in ["ouro", "retorno", "sim", "pode", "vamos", "upgrade"]):
                self.plano_escolhido = "ouro" if self.plano_escolhido == "com_retorno" else "com_retorno"

        self.etapa = "agendamento"
        return self._iniciar_agendamento()

    def _iniciar_agendamento(self) -> list[str]:
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

        # guarda os 3 primeiros para o paciente escolher
        self._slots_oferecidos = slots[:3]
        opcoes = "\n".join(
            f"{i+1}. {s['data_fmt']} às {s['hora']}"
            for i, s in enumerate(self._slots_oferecidos)
        )
        return [MSG_AGENDAMENTO_OPCOES.format(
            modalidade=self.modalidade,
            opcoes=opcoes,
        )]

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
        valor = kb.get_valor(self.plano_escolhido or "unica", self.modalidade or "presencial")
        parcelas = kb.get_parcelas(self.plano_escolhido or "unica")

        return [MSG_FORMA_PAGAMENTO.format(
            plano_nome=plano_dados["nome"] if plano_dados else self.plano_escolhido,
            modalidade=self.modalidade,
            valor=valor,
            parcelas=parcelas,
            parcela=valor / parcelas,
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
            return [MSG_PIX.format(chave_pix=kb.contatos["pix_chave"], valor=valor)]

        # cartão — gera link
        link_result = gerar_link_pagamento(
            plano=self.plano_escolhido or "unica",
            modalidade=self.modalidade or "presencial",
            referencia=f"{self.phone_hash[:12]}-{datetime.now(BRT).strftime('%Y%m%d%H%M')}",
        )
        if not link_result.sucesso or not link_result.url:
            logger.error("Falha ao gerar link de pagamento: %s", link_result.erro)
            self.forma_pagamento = "pix"
            return [MSG_ERRO_PAGAMENTO]

        return [MSG_CARTAO.format(
            link=link_result.url,
            parcelas=link_result.parcelas,
        )]

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
        """Cadastra paciente e agenda no Dietbox."""
        if not self.slot_escolhido:
            self.etapa = "agendamento"
            return self._iniciar_agendamento()

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
        return self._etapa_confirmacao(_msg)

    def _etapa_confirmacao(self, _msg: str) -> list[str]:
        slot = self.slot_escolhido or {}
        plano_dados = kb.get_plano(self.plano_escolhido or "unica")
        plano_nome = plano_dados["nome"] if plano_dados else (self.plano_escolhido or "")

        template = MSG_CONFIRMACAO_PRESENCIAL if self.modalidade != "online" else MSG_CONFIRMACAO_ONLINE
        confirmacao = template.format(
            nome=self.nome or "",
            data=slot.get("data_fmt", ""),
            hora=slot.get("hora", ""),
            plano_nome=plano_nome,
        )

        self.etapa = "finalizacao"
        return [confirmacao]


# ── helpers ───────────────────────────────────────────────────────────────────

def _extrair_nome(msg: str) -> str | None:
    """Extrai primeiro(s) nome(s) da mensagem (heurística simples)."""
    import re
    # Remove saudações comuns
    limpo = re.sub(
        r"^(oi|olá|ola|bom dia|boa tarde|boa noite|tudo bem|tudo bom)[,!.]*\s*",
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

    # fallback: primeira palavra com mais de 2 chars
    for t in tokens:
        t_clean = t.strip(",.!?")
        if len(t_clean) > 2 and t_clean.isalpha():
            return t_clean.capitalize()
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
