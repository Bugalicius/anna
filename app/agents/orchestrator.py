"""
Agente 0 — Orquestrador

Classifica a intenção da mensagem via Claude Haiku e roteia para o agente correto.

Intenções reconhecidas:
  novo_lead          → Agente 1 (atendimento)
  tirar_duvida       → Agente 1
  agendar            → Agente 1
  pagar              → Agente 1
  remarcar           → Agente 2 (retenção)
  cancelar           → Agente 2
  lembrete           → Agente 2 (disparado pelo scheduler, não por mensagem)
  fora_de_contexto   → resposta padrão sem escalar
  duvida_clinica     → escalação para nutricionista
"""
from __future__ import annotations

import json
import logging
import os
from typing import Literal

import anthropic

logger = logging.getLogger(__name__)

IntencaoType = Literal[
    "novo_lead",
    "tirar_duvida",
    "agendar",
    "pagar",
    "remarcar",
    "cancelar",
    "fora_de_contexto",
    "duvida_clinica",
    "recusou_remarketing",
]

_INTENCOES_AGENTE1: set[str] = {"novo_lead", "tirar_duvida", "agendar", "pagar"}
_INTENCOES_AGENTE2: set[str] = {"remarcar", "cancelar"}

_PROMPT_CLASSIFICACAO = """\
Você é um classificador de intenções para uma assistente de agendamento nutricional.

Analise a mensagem do usuário e retorne JSON com os campos:
  "intencao": uma das opções abaixo
  "confianca": número entre 0.0 e 1.0

Opções de intenção:
- novo_lead: primeira interação ou busca por informações sobre consultas/planos
- tirar_duvida: dúvida sobre valores, horários, formas de pagamento, como funciona
- agendar: quer marcar uma consulta (já decidiu ou está pronto para decidir)
- pagar: quer efetuar pagamento, envia comprovante, pergunta sobre link de pagamento
- remarcar: quer mudar data/hora de consulta já agendada
- cancelar: quer cancelar consulta
- duvida_clinica: dúvida médica/nutricional (dieta, exames, sintomas, condições de saúde)
- recusou_remarketing: lead informa que não vai marcar consulta, não tem interesse, pede para parar de enviar mensagens, diz "deixa pra lá", "não vou marcar", "pode tirar meu número"
- fora_de_contexto: assunto não relacionado a consultas ou nutrição

Responda APENAS com JSON válido, sem explicações.

Mensagem: {mensagem}
"""

_MSG_FORA_CONTEXTO = (
    "Oi! Sou a Ana, assistente da nutricionista Thaynara Teixeira 💚 "
    "Posso te ajudar com agendamentos e informações sobre as consultas. "
    "Tem algo nesse sentido que posso te ajudar?"
)


def _classificar_intencao(mensagem: str, contexto: str = "") -> tuple[IntencaoType, float]:
    """
    Usa Claude Haiku para classificar a intenção da mensagem.

    Parâmetro contexto permite informar ao LLM que há um fluxo em andamento (D-01).

    Returns:
        (intencao, confianca)
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    mensagem_com_contexto = f"{contexto}\n\nMensagem: {mensagem}" if contexto else mensagem
    prompt = _PROMPT_CLASSIFICACAO.format(mensagem=mensagem_com_contexto)

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()

        # strip markdown code blocks if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        data = json.loads(raw)
        intencao: IntencaoType = data.get("intencao", "fora_de_contexto")
        confianca: float = float(data.get("confianca", 0.5))

        # validação
        validas = {
            "novo_lead", "tirar_duvida", "agendar", "pagar",
            "remarcar", "cancelar", "fora_de_contexto", "duvida_clinica",
            "recusou_remarketing",
        }
        if intencao not in validas:
            intencao = "fora_de_contexto"

        return intencao, confianca

    except Exception as e:
        logger.error("Erro ao classificar intenção: %s", e)
        return "novo_lead", 0.5   # fallback conservador para novos leads


def rotear(
    mensagem: str,
    stage_atual: str | None,
    primeiro_contato: bool = False,
    agente_ativo: str | None = None,  # "atendimento" | "retencao" | None
) -> dict:
    """
    Classifica a intenção e retorna instruções de roteamento.

    Parâmetro agente_ativo fornece contexto ao LLM quando há fluxo em andamento,
    garantindo que a intenção real da mensagem seja classificada mesmo assim (D-01).

    Returns:
        {
            "agente": "atendimento" | "retencao" | "escalacao" | "padrao",
            "intencao": str,
            "confianca": float,
            "resposta_padrao": str | None,   # preenchido apenas para fora_de_contexto
        }
    }
    """
    # Primeiro contato sempre vai para Agente 1
    # Exceção: se já há um agente ativo, classificar via LLM mesmo com stage "new"
    # (ex: paciente de retorno identificado durante boas_vindas ainda tem stage="new")
    if (primeiro_contato or stage_atual in (None, "cold_lead")) and agente_ativo is None:
        return {
            "agente": "atendimento",
            "intencao": "novo_lead",
            "confianca": 1.0,
            "resposta_padrao": None,
        }

    # Contexto para o LLM quando há fluxo em andamento (D-01)
    contexto_agente = (
        f"Contexto: o paciente está no meio de um fluxo de {agente_ativo}. "
        "Classifique a intenção real da mensagem mesmo assim."
        if agente_ativo else ""
    )

    try:
        intencao, confianca = _classificar_intencao(mensagem, contexto=contexto_agente)
    except Exception as e:
        logger.error("Falha ao classificar intenção: %s — fallback novo_lead", e)
        intencao, confianca = "novo_lead", 0.5
    logger.info("Intenção classificada: %s (%.2f) agente_ativo=%s", intencao, confianca, agente_ativo)

    if intencao in _INTENCOES_AGENTE1:
        return {"agente": "atendimento", "intencao": intencao, "confianca": confianca, "resposta_padrao": None}

    if intencao in _INTENCOES_AGENTE2:
        return {"agente": "retencao", "intencao": intencao, "confianca": confianca, "resposta_padrao": None}

    if intencao == "duvida_clinica":
        return {"agente": "escalacao", "intencao": intencao, "confianca": confianca, "resposta_padrao": None}

    # D-08: lead recusa remarketing — encaminha para handler dedicado
    if intencao == "recusou_remarketing":
        return {"agente": "remarketing_recusa", "intencao": intencao, "confianca": confianca, "resposta_padrao": None}

    # fora_de_contexto
    return {
        "agente": "padrao",
        "intencao": intencao,
        "confianca": confianca,
        "resposta_padrao": _MSG_FORA_CONTEXTO,
    }
