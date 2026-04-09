"""
Agente 2 — Retenção

Responsável por:
  1. Sequência de remarketing (24h / 7d / 30d após silêncio)
  2. Lembrete 24h antes da consulta (disparado pelo APScheduler)
  3. Fluxo de remarcação (consulta Dietbox, prazo 7 dias)
  4. Fluxo de cancelamento
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import anthropic

from app.agents.dietbox_worker import consultar_slots_disponiveis
from app.knowledge_base import kb

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))

# ── Sequência de remarketing ──────────────────────────────────────────────────

REMARKETING_SEQ: list[dict] = [
    {
        "posicao": 1,
        "delay_horas": 24,
        "mensagem": (
            "Oi {nome}! 💚 Aqui é a Ana, da nutricionista Thaynara Teixeira.\n\n"
            "Notei que você ainda não agendou sua consulta. "
            "Será que ficou alguma dúvida? Me conta, posso te ajudar!"
        ),
    },
    {
        "posicao": 2,
        "delay_horas": 24 * 7,
        "mensagem": (
            "Olá, {nome}! 🌿\n\n"
            "Passaram alguns dias desde nosso último contato. "
            "A Thaynara ainda tem horários disponíveis e adoraria te receber.\n\n"
            "Que tal a gente encontrar um horário que funcione pra você? 😊"
        ),
    },
    {
        "posicao": 3,
        "delay_horas": 24 * 30,
        "mensagem": (
            "Oi {nome}! 💚\n\n"
            "Faz um tempo que não nos falamos. "
            "Qualquer que seja o seu objetivo — perda de peso, saúde, energia — "
            "a Thaynara pode te ajudar a chegar lá com segurança.\n\n"
            "Quando quiser retomar, é só me chamar aqui! 🌱"
        ),
    },
]

# ── Mensagens de lembrete ─────────────────────────────────────────────────────

MSG_LEMBRETE_24H = (
    "Oi {nome}! 💚 Lembrete: sua consulta com a Thaynara é *amanhã*!\n\n"
    "📅 *Data:* {data}\n"
    "🕐 *Horário:* {hora}\n"
    "📍 *Modalidade:* {modalidade}\n\n"
    "{complemento}\n\n"
    "Qualquer imprevisto, me avisa com antecedência 😊"
)

_COMPLEMENTO_PRESENCIAL = (
    "Lembra de chegar com 10 minutos de antecedência e trazer seus últimos exames (se tiver) 📋"
)
_COMPLEMENTO_ONLINE = (
    "O link da videochamada será enviado 30 minutos antes da consulta 🎥"
)

# ── Mensagens de remarcação / cancelamento ────────────────────────────────────

MSG_INICIO_REMARCACAO = (
    "Sem problemas, {nome}! Vou verificar os horários disponíveis para você remarcar 📅"
)

MSG_OPCOES_REMARCACAO = (
    "Tenho estas opções disponíveis nos próximos dias:\n\n"
    "{opcoes}\n\n"
    "Qual horário funciona melhor?"
)

MSG_CONFIRMACAO_REMARCACAO = (
    "✅ Consulta remarcada!\n\n"
    "Nova data: *{data}* às *{hora}*\n"
    "Modalidade: {modalidade}\n\n"
    "Pode contar comigo para qualquer dúvida 💚"
)

MSG_INICIO_CANCELAMENTO = (
    "Tudo bem, {nome}. Vou registrar o cancelamento da sua consulta.\n\n"
    "Só para saber: o que aconteceu? Ficou alguma dúvida ou podemos ajudar de outra forma?"
)

MSG_CANCELAMENTO_CONFIRMADO = (
    "Consulta cancelada com sucesso ✅\n\n"
    "Quando quiser retomar o acompanhamento, é só me chamar aqui! "
    "A Thaynara vai adorar te receber 💚"
)

MSG_POLITICA_CANCELAMENTO = kb.get_politica("cancelamento")


# ── Classe principal do Agente 2 ──────────────────────────────────────────────

class AgenteRetencao:
    """
    Gerencia remarcação e cancelamento dentro de uma conversa.
    Instanciado quando o Orquestrador detecta intenção "remarcar" ou "cancelar".
    """

    def __init__(self, telefone: str, nome: str | None, modalidade: str = "presencial") -> None:
        self.telefone = telefone
        self.nome = nome or "paciente"
        self.modalidade = modalidade
        self.etapa: str = "inicio"
        self.motivo: str | None = None
        self.consulta_atual: dict | None = None
        self.novo_slot: dict | None = None
        self._slots_oferecidos: list[dict] = []
        self.historico: list[dict] = []

    # ── serialização ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serializa o estado do agente para dict armazenável no Redis."""
        return {
            "_tipo": "retencao",
            "telefone": self.telefone,
            "nome": self.nome,
            "modalidade": self.modalidade,
            "etapa": self.etapa,
            "motivo": self.motivo,
            "consulta_atual": self.consulta_atual,
            "novo_slot": self.novo_slot,
            "historico": self.historico[-20:],  # T-01-01: máx 20 entradas
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgenteRetencao":
        """Restaura instância a partir de dict serializado."""
        agent = cls(
            telefone=data["telefone"],
            nome=data.get("nome"),
            modalidade=data.get("modalidade", "presencial"),
        )
        agent.etapa = data.get("etapa", "inicio")
        agent.motivo = data.get("motivo")
        agent.consulta_atual = data.get("consulta_atual")
        agent.novo_slot = data.get("novo_slot")
        agent.historico = data.get("historico", [])
        return agent

    def processar_remarcacao(self, mensagem: str) -> list[str]:
        self.historico.append({"role": "user", "content": mensagem})
        respostas = self._fluxo_remarcacao(mensagem)
        for r in respostas:
            self.historico.append({"role": "assistant", "content": r})
        return respostas

    def processar_cancelamento(self, mensagem: str) -> list[str]:
        self.historico.append({"role": "user", "content": mensagem})
        respostas = self._fluxo_cancelamento(mensagem)
        for r in respostas:
            self.historico.append({"role": "assistant", "content": r})
        return respostas

    # ── remarcação ────────────────────────────────────────────────────────────

    def _fluxo_remarcacao(self, msg: str) -> list[str]:
        if self.etapa == "inicio":
            self.etapa = "oferecendo_slots"
            try:
                slots = consultar_slots_disponiveis(
                    modalidade=self.modalidade,
                    dias_a_frente=7,
                )
            except Exception as e:
                logger.error("Erro ao consultar slots para remarcação: %s", e)
                slots = []

            if not slots:
                return [
                    MSG_INICIO_REMARCACAO.format(nome=self.nome),
                    "Infelizmente não encontrei horários nos próximos 7 dias. "
                    "Vou verificar com a Thaynara e te retorno em breve 🔍",
                ]

            self._slots_oferecidos = slots[:3]
            opcoes = "\n".join(
                f"{i+1}. {s['data_fmt']} às {s['hora']}"
                for i, s in enumerate(self._slots_oferecidos)
            )
            return [
                MSG_INICIO_REMARCACAO.format(nome=self.nome),
                MSG_OPCOES_REMARCACAO.format(opcoes=opcoes),
            ]

        if self.etapa == "oferecendo_slots":
            slot = _extrair_escolha_slot(msg, self._slots_oferecidos)
            if slot:
                self.etapa = "concluido"
                return [MSG_CONFIRMACAO_REMARCACAO.format(
                    data=slot["data_fmt"],
                    hora=slot["hora"],
                    modalidade=self.modalidade,
                )]
            opcoes = "\n".join(
                f"{i+1}. {s['data_fmt']} às {s['hora']}"
                for i, s in enumerate(self._slots_oferecidos)
            )
            return [f"Pode escolher uma das opções:\n{opcoes}"]

        return [_gerar_resposta_llm_retencao(self.historico, self.etapa)]

    # ── cancelamento ──────────────────────────────────────────────────────────

    def _fluxo_cancelamento(self, msg: str) -> list[str]:
        if self.etapa == "inicio":
            self.etapa = "aguardando_motivo"
            return [
                MSG_INICIO_CANCELAMENTO.format(nome=self.nome),
                f"_Política de cancelamento: {MSG_POLITICA_CANCELAMENTO}_",
            ]

        if self.etapa == "aguardando_motivo":
            self.etapa = "concluido"
            return [MSG_CANCELAMENTO_CONFIRMADO]

        return [MSG_CANCELAMENTO_CONFIRMADO]


# ── Funções de remarketing (chamadas pelo scheduler) ─────────────────────────

def montar_mensagem_remarketing(posicao: int, nome: str | None) -> str:
    """Retorna o texto da mensagem de remarketing para a posição dada."""
    seq = next((s for s in REMARKETING_SEQ if s["posicao"] == posicao), None)
    if not seq:
        return ""
    return seq["mensagem"].format(nome=nome or "")


def montar_lembrete_consulta(
    nome: str | None,
    data: str,
    hora: str,
    modalidade: str,
) -> str:
    """Monta a mensagem de lembrete 24h antes da consulta."""
    complemento = _COMPLEMENTO_ONLINE if modalidade == "online" else _COMPLEMENTO_PRESENCIAL
    return MSG_LEMBRETE_24H.format(
        nome=nome or "",
        data=data,
        hora=hora,
        modalidade=modalidade,
        complemento=complemento,
    )


# ── helpers internos ──────────────────────────────────────────────────────────

def _extrair_escolha_slot(msg: str, slots: list[dict]) -> dict | None:
    msg_lower = msg.lower()
    for i, word in enumerate(["1", "primeiro", "2", "segundo", "3", "terceiro"]):
        if word in msg_lower:
            idx = i // 2
            if idx < len(slots):
                return slots[idx]
    for s in slots:
        if s["hora"] in msg or s["data_fmt"] in msg:
            return s
    return None


def _gerar_resposta_llm_retencao(historico: list[dict], etapa: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    system = kb.system_prompt() + f"\n\n## Etapa atual: {etapa} (fluxo de retenção)"
    msgs = [{"role": m["role"], "content": m["content"]} for m in historico[-8:]]
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=system,
            messages=msgs,
        )
        return response.content[0].text.strip()
    except Exception as e:
        logger.error("Erro LLM retenção: %s", e)
        return "Posso te ajudar com mais alguma coisa? 💚"
