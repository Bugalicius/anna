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

import json
import logging
import os
import random
import re
from datetime import datetime, date, timedelta, timezone

import anthropic

from app.agents.dietbox_worker import (
    confirmar_pagamento,
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
    "preferencia_horario",
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
        "Ótima escolha! Mas posso te dar uma dica? 💚\n\n"
        "O *Plano Ouro* sai por R${valor_upgrade:.0f} presencial (ou R${valor_upgrade_online:.0f} online) "
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
        "encontros coletivos e a Lilly — nossa assistente que te ajuda com "
        "substituições de alimentos na hora, mantendo seu plano sempre ajustado. "
        "Fica por R${valor_upgrade:.0f} presencial.\n\n"
        "Quer manter o Ouro ou prefere o Premium?"
    ),
}

MSG_PREFERENCIA_HORARIO = (
    "Para seguirmos com o agendamento, me informe qual horário atende melhor à sua rotina:\n\n"
    "Segunda a Sexta-feira:\n"
    "Manhã: 08h, 09h e 10h\n"
    "Tarde: 15h, 16h e 17h\n"
    "Noite: 18h e 19h (exceto sexta à noite)\n\n"
    "Importante: só realizamos o agendamento do dia e horário da consulta mediante a "
    "confirmação do pagamento. Quanto antes o sinal for enviado, maior a chance de "
    "garantir o horário de sua preferência."
)

MSG_AGENDAMENTO_OPCOES = (
    "Tenho essas opções disponíveis para {modalidade}:\n\n"
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

HORAS_MANHA = {"8h", "9h", "10h"}
HORAS_TARDE = {"15h", "16h", "17h"}
HORAS_NOITE = {"18h", "19h"}
DIAS_MAP = {
    "segunda": 0, "seg": 0,
    "terça": 1, "terca": 1, "ter": 1,
    "quarta": 2, "qua": 2,
    "quinta": 3, "qui": 3,
    "sexta": 4, "sex": 4,
}
DIAS_PT_LOCAL = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

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

MSG_ERRO_AGENDAMENTO_DIETBOX = (
    "Ops! Tive um problema técnico ao confirmar seu agendamento no sistema 😔\n\n"
    "Seu horário ainda não foi confirmado. Vou tentar novamente assim que você me responder aqui, "
    "ou, se preferir, posso pedir para a Thaynara verificar manualmente 💚"
)


_PROMPT_INTERPRETACAO_ETAPA = """\
Você está ajudando a interpretar a mensagem de uma paciente dentro de um fluxo comercial de agendamento nutricional.

Retorne APENAS JSON válido com os campos:
  "acao": string
  "plano": string|null
  "modalidade": string|null
  "forma_pagamento": string|null
  "aceita_upgrade": boolean
  "manter_plano": boolean
  "resposta_sugerida": string|null

Valores válidos de "acao":
- informar_plano
- informar_modalidade
- informar_plano_modalidade
- tirar_duvida
- aceitar_upgrade
- manter_escolha
- escolher_pagamento
- resposta_livre
- indefinido

Planos válidos:
- premium
- ouro
- com_retorno
- unica
- formulario

Modalidades válidas:
- presencial
- online

Formas de pagamento válidas:
- pix
- cartao

Etapa atual: {etapa}
Estado atual: {estado}

Histórico recente:
{historico}

Mensagem da paciente:
{mensagem}
"""


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


def _interpretar_mensagem_etapa(
    historico: list[dict],
    etapa: str,
    mensagem: str,
    estado: dict,
) -> dict:
    """
    Interpreta a mensagem do paciente dentro de uma etapa específica.

    Retorna dict estruturado para o FSM decidir se avança, responde dúvida ou
    mantém a etapa atual.
    """
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    historico_limpo = sanitize_historico(historico[-8:])
    historico_txt = "\n".join(
        f"{m['role']}: {m['content']}" for m in historico_limpo
    ) or "(sem histórico)"
    prompt = _PROMPT_INTERPRETACAO_ETAPA.format(
        etapa=etapa,
        estado=json.dumps(estado, ensure_ascii=False),
        historico=historico_txt,
        mensagem=mensagem,
    )

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=kb.system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return {
            "acao": data.get("acao", "indefinido"),
            "plano": data.get("plano"),
            "modalidade": data.get("modalidade"),
            "forma_pagamento": data.get("forma_pagamento"),
            "aceita_upgrade": bool(data.get("aceita_upgrade", False)),
            "manter_plano": bool(data.get("manter_plano", False)),
            "resposta_sugerida": data.get("resposta_sugerida"),
        }
    except Exception as e:
        logger.error("Erro ao interpretar mensagem na etapa %s: %s", etapa, e)
        return {
            "acao": "indefinido",
            "plano": None,
            "modalidade": None,
            "forma_pagamento": None,
            "aceita_upgrade": False,
            "manter_plano": False,
            "resposta_sugerida": None,
        }


def _resumo_pagamento_plano(plano: str, modalidade: str) -> str:
    plano_dados = kb.get_plano(plano) or {}
    nome = plano_dados.get("nome", plano)
    valor_pix = kb.get_valor(plano, modalidade)
    parcelas = kb.get_parcelas(plano)
    parcela = plano_dados.get(f"parcela_{modalidade}", 0)
    return (
        f"*{nome}* ({modalidade}): PIX de R${valor_pix:.0f} "
        f"ou {parcelas}x de R${parcela:.0f} no cartão"
    )


def _responder_duvida_pagamento(plano_atual: str, modalidade: str, plano_upgrade: str | None = None) -> str:
    linhas = [_resumo_pagamento_plano(plano_atual, modalidade)]
    if plano_upgrade and plano_upgrade != plano_atual:
        linhas.append(_resumo_pagamento_plano(plano_upgrade, modalidade))
    return (
        "Sim! No cartão dá pra parcelar 😊\n\n"
        + "\n".join(f"• {linha}" for linha in linhas)
    )


def _detectar_modalidade(msg: str) -> str | None:
    msg_lower = msg.lower()
    if "online" in msg_lower:
        return "online"
    if any(w in msg_lower for w in ["presencial", "pessoal", "clínica", "clinica", "vespasiano"]):
        return "presencial"
    return None


def _detectar_forma_pagamento(msg: str) -> str | None:
    msg_lower = msg.lower()
    if "pix" in msg_lower or "transferência" in msg_lower or "transferencia" in msg_lower:
        return "pix"
    if any(w in msg_lower for w in ["cartão", "cartao", "crédito", "credito", "link"]):
        return "cartao"
    return None


def _detectar_status_paciente(msg: str) -> str | None:
    msg_lower = msg.lower()
    if any(w in msg_lower for w in ["já sou paciente", "sou paciente", "retorno", "segunda vez", "já fui"]):
        return "retorno"
    if any(w in msg_lower for w in ["primeira consulta", "primeira vez", "nova paciente", "sou nova"]):
        return "novo"
    return None


def _eh_afirmacao(msg: str) -> bool:
    msg_lower = msg.lower()
    return any(w in msg_lower for w in ["sim", "pode", "vamos", "fechado", "quero", "prefiro esse", "pode ser"])


def _eh_negacao(msg: str) -> bool:
    msg_lower = msg.lower()
    return any(w in msg_lower for w in ["não", "nao", "prefiro manter", "quero manter", "deixa", "melhor não", "melhor nao"])


def _detectar_topico_duvida(msg: str) -> str | None:
    msg_lower = msg.lower()
    if any(w in msg_lower for w in ["pix", "cartão", "cartao", "parcela", "parcel", "desconto", "pagar", "pagamento", "sinal", "valor", "preço", "preco"]):
        return "pagamento"
    if any(w in msg_lower for w in ["online", "presencial", "videochamada", "vídeo", "whatsapp", "endereço", "endereco", "local"]):
        return "modalidade"
    if any(w in msg_lower for w in ["plano", "consulta", "retorno", "premium", "ouro", "formulário", "formulario"]):
        return "planos"
    if any(w in msg_lower for w in ["remarcar", "cancelar", "antecedência", "antecedencia", "política", "politica"]):
        return "politica"
    return None


def _compreender_turno_atendimento(etapa: str, msg: str) -> dict:
    """Extrai intenção operacional do turno antes da etapa reagir."""
    topico_duvida = _detectar_topico_duvida(msg) if "?" in msg or any(w in msg.lower() for w in ["como", "qual", "quanto", "posso", "funciona", "divide", "parcel"]) else None
    return {
        "nome": _extrair_nome(msg),
        "status_paciente": _detectar_status_paciente(msg),
        "plano": _identificar_plano(msg),
        "modalidade": _detectar_modalidade(msg),
        "forma_pagamento": _detectar_forma_pagamento(msg),
        "topico_duvida": topico_duvida,
        "afirmacao": _eh_afirmacao(msg),
        "negacao": _eh_negacao(msg),
        "quer_agendar": any(w in msg.lower() for w in ["agendar", "marcar consulta", "marcar uma consulta"]),
        "quer_remarcar": "remarcar" in msg.lower(),
        "quer_cancelar": "cancelar" in msg.lower(),
    }


def _resposta_contextual_topico(topico: str, plano: str | None, modalidade: str | None) -> str:
    if topico == "pagamento":
        if plano and modalidade:
            return (
                f"{_resumo_pagamento_plano(plano, modalidade)}\n\n"
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
    return ""


def _descrever_preferencia_horario(horas_preferidas: set[str] | None, dia_preferido: int | None) -> str:
    partes: list[str] = []
    if dia_preferido is not None:
        partes.append(f"na {DIAS_PT_LOCAL[dia_preferido]}")

    if horas_preferidas:
        if horas_preferidas == HORAS_MANHA:
            partes.append("de manhã")
        elif horas_preferidas == HORAS_TARDE:
            partes.append("à tarde")
        elif horas_preferidas == HORAS_NOITE:
            partes.append("à noite")
        elif len(horas_preferidas) == 1:
            partes.append(f"às {next(iter(horas_preferidas))}")
        else:
            horas_txt = ", ".join(sorted(horas_preferidas))
            partes.append(f"nos horários {horas_txt}")

    return " ".join(partes).strip()


def _interpretar_preferencia_horario(msg: str) -> dict:
    """Interpreta preferência de agenda de forma estruturada antes de consultar o Dietbox."""
    msg_lower = msg.lower().strip()
    prioridade_proximidade = any(
        trecho in msg_lower
        for trecho in [
            "mais perto",
            "mais próximo",
            "mais proximo",
            "horário mais próximo",
            "horario mais proximo",
            "o mais próximo",
            "o mais proximo",
        ]
    )

    dia_preferido: int | None = None
    for palavra, weekday in DIAS_MAP.items():
        if re.search(rf"\b{re.escape(palavra)}\b", msg_lower):
            dia_preferido = weekday
            break

    horas_preferidas: set[str] | None = None
    horas_explicitas = {
        f"{int(hora)}h"
        for hora in re.findall(r"\b([01]?\d|2[0-3])\s*h\b", msg_lower)
    }
    horas_grade = {h for h in horas_explicitas if h in (HORAS_MANHA | HORAS_TARDE | HORAS_NOITE)}
    if horas_grade:
        horas_preferidas = horas_grade
    elif any(w in msg_lower for w in ["manhã", "manha", "cedo", "de manhã", "pela manhã", "pela manha"]):
        horas_preferidas = set(HORAS_MANHA)
    elif any(w in msg_lower for w in ["tarde", "de tarde", "à tarde", "a tarde"]):
        horas_preferidas = set(HORAS_TARDE)
    elif any(w in msg_lower for w in ["noite", "à noite", "a noite", "de noite"]):
        horas_preferidas = set(HORAS_NOITE)

    aceita_qualquer_turno = any(
        trecho in msg_lower
        for trecho in [
            "qualquer horário",
            "qualquer horario",
            "qualquer turno",
            "tanto faz",
            "indiferente",
        ]
    ) or prioridade_proximidade

    acao = "buscar"
    if not prioridade_proximidade and dia_preferido is None and horas_preferidas is None and not aceita_qualquer_turno:
        acao = "esclarecer"

    return {
        "acao": acao,
        "modo_busca": "proximidade" if prioridade_proximidade else "preferencia",
        "horas_preferidas": None if aceita_qualquer_turno else horas_preferidas,
        "dia_preferido": dia_preferido,
        "descricao_preferencia": _descrever_preferencia_horario(
            None if aceita_qualquer_turno else horas_preferidas,
            dia_preferido,
        ),
        "aceita_qualquer_turno": aceita_qualquer_turno,
    }


def _selecionar_slots_agendamento(
    slots: list[dict],
    horas_preferidas: set[str] | None,
    dia_preferido: int | None,
    modo_busca: str,
) -> tuple[list[dict], str | None]:
    """Seleciona slots e retorna aviso se a preferência não puder ser atendida."""
    if not slots:
        return [], None

    if modo_busca == "proximidade":
        return slots[:3], None

    def _match_preferencia(s: dict) -> bool:
        dia_ok = dia_preferido is None or s["data_fmt"].startswith(DIAS_PT_LOCAL[dia_preferido])
        hora_ok = not horas_preferidas or s["hora"] in horas_preferidas
        return dia_ok and hora_ok

    matches = [s for s in slots if _match_preferencia(s)]
    if not matches and (horas_preferidas or dia_preferido is not None):
        descricao = _descrever_preferencia_horario(horas_preferidas, dia_preferido)
        aviso = (
            f"Não encontrei opções {descricao} nos próximos dias úteis.\n\n"
            "Para te ajudar sem te deixar travada, separei os 3 horários mais próximos disponíveis:"
        ).replace("opções  nos", "opções nos")
        return slots[:3], aviso

    base = matches if matches else slots
    slot1 = base[0]
    selecionados: list[dict] = [slot1]
    dias_usados: set[str] = {slot1["datetime"][:10]}

    candidatos = [s for s in base[1:] if s["datetime"][:10] not in dias_usados]
    ordenados = sorted(
        candidatos,
        key=lambda s: (0 if (horas_preferidas and s["hora"] in horas_preferidas) else 1, s["datetime"]),
    )
    for s in ordenados:
        dia = s["datetime"][:10]
        if dia not in dias_usados:
            selecionados.append(s)
            dias_usados.add(dia)
        if len(selecionados) >= 3:
            break

    if len(selecionados) < 3:
        for s in base[1:]:
            if s not in selecionados:
                selecionados.append(s)
            if len(selecionados) >= 3:
                break

    return selecionados[:3], None


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
        self.id_transacao_dietbox: str | None = None
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

        if etapa == "preferencia_horario":
            return self._etapa_preferencia_horario(msg)

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
        compreensao = _compreender_turno_atendimento("boas_vindas", msg)
        # Tenta extrair nome da mensagem atual
        nome = compreensao["nome"]
        if nome:
            self.nome = nome
            status = compreensao["status_paciente"] or "novo"
            self.status_paciente = status
            self.etapa = "qualificacao"

            # Paciente de retorno: não exibir fluxo de novo paciente
            if status == "retorno":
                resp_retorno = (
                    f"Que bom te ver de volta, {self.nome}! 💚\n\n"
                    "Como posso te ajudar hoje?\n"
                    "👉 Remarcar consulta\n"
                    "👉 Cancelar consulta\n"
                    "👉 Tirar uma dúvida"
                )
                if len(self.historico) <= 1:
                    return [MSG_BOAS_VINDAS, resp_retorno]
                return [resp_retorno]

            # Novo paciente: pede objetivo
            if len(self.historico) <= 1:
                return [MSG_BOAS_VINDAS, MSG_OBJETIVOS.format(nome=self.nome)]
            return [MSG_OBJETIVOS.format(nome=self.nome)]

        # Primeira mensagem sem nome — responde com boas-vindas (pede nome)
        if len(self.historico) <= 1:
            return [MSG_BOAS_VINDAS]

        if compreensao["topico_duvida"] or compreensao["plano"] or compreensao["modalidade"]:
            return [
                "Consigo te explicar isso sim 💚\n\n"
                "Antes de avançar, só preciso confirmar seu *nome e sobrenome* "
                "e se é sua *primeira consulta* ou se você *já é paciente*, combinado?"
            ]

        return [_gerar_resposta_llm(self.historico, "boas_vindas",
                                     "Ainda precisa coletar o nome do paciente.")]

    def _etapa_qualificacao(self, msg: str) -> list[str]:
        msg_lower = msg.lower()
        compreensao = _compreender_turno_atendimento("qualificacao", msg)
        # Paciente informa que é de retorno — não exibir fluxo de novo paciente
        _KEYWORDS_RETORNO = {"já sou paciente", "sou paciente", "já sou", "paciente", "retorno", "segunda vez"}
        if any(w in msg_lower for w in _KEYWORDS_RETORNO):
            self.status_paciente = "retorno"
            # Não avança a etapa — próxima mensagem será classificada pelo orquestrador
            # e pode acionar interrupt para remarcar/cancelar (D-02)
            return [
                f"Entendido{', ' + self.nome if self.nome else ''}! 😊 Como posso te ajudar?\n\n"
                "👉 Remarcar consulta\n"
                "👉 Cancelar consulta\n"
                "👉 Tirar uma dúvida"
            ]

        if compreensao["topico_duvida"]:
            resposta = _resposta_contextual_topico(
                compreensao["topico_duvida"],
                self.plano_escolhido,
                self.modalidade,
            )
            if resposta:
                return [
                    f"{resposta}\n\n"
                    "E para eu te orientar da melhor forma, me conta: qual é o seu principal objetivo com o acompanhamento?"
                ]

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
        compreensao = _compreender_turno_atendimento("apresentacao_planos", msg)

        # Captura modalidade mesmo sem plano escolhido
        modalidade = compreensao["modalidade"]
        if modalidade:
            self.modalidade = modalidade

        plano = compreensao["plano"]
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

        if self.modalidade:
            return [
                f"Perfeito, {self.modalidade}! 😊\n\n"
                "Agora me conta qual plano faz mais sentido pra você:\n"
                "👉 Consulta única\n"
                "👉 Consulta com retorno\n"
                "👉 Plano Ouro\n"
                "👉 Plano Premium\n"
                "👉 Dieta por formulário"
            ]

        if compreensao["topico_duvida"]:
            resposta = _resposta_contextual_topico(
                compreensao["topico_duvida"],
                self.plano_escolhido,
                self.modalidade,
            )
            if resposta:
                return [
                    f"{resposta}\n\n"
                    "Agora me conta qual plano e modalidade fazem mais sentido pra você."
                ]

        interpretacao = _interpretar_mensagem_etapa(
            self.historico,
            "apresentacao_planos",
            msg,
            {
                "plano_escolhido": self.plano_escolhido,
                "modalidade": self.modalidade,
            },
        )

        plano_interp = interpretacao.get("plano")
        modalidade_interp = interpretacao.get("modalidade")
        if plano_interp:
            self.plano_escolhido = plano_interp
        if modalidade_interp:
            self.modalidade = modalidade_interp

        if self.plano_escolhido and self.modalidade:
            self.etapa = "escolha_plano"
            return self._etapa_escolha_plano(msg)

        if self.plano_escolhido and not self.modalidade:
            return [
                f"Perfeito! Para esse plano, você prefere *presencial* ou *online*? 😊"
            ]

        if self.modalidade and not self.plano_escolhido:
            return [
                f"Perfeito, {self.modalidade}! 😊\n\n"
                "Agora me conta qual plano faz mais sentido pra você:\n"
                "👉 Consulta única\n"
                "👉 Consulta com retorno\n"
                "👉 Plano Ouro\n"
                "👉 Plano Premium\n"
                "👉 Dieta por formulário"
            ]

        if interpretacao.get("acao") in {"tirar_duvida", "resposta_livre"} and interpretacao.get("resposta_sugerida"):
            return [interpretacao["resposta_sugerida"]]

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
        compreensao = _compreender_turno_atendimento("escolha_plano", msg)
        if self.modalidade is None:
            if compreensao["modalidade"]:
                self.modalidade = compreensao["modalidade"]
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
            upgrades = {"unica": "ouro", "com_retorno": "ouro", "ouro": "premium"}
            plano_atual = self.plano_escolhido or "unica"
            plano_upgrade = upgrades.get(plano_atual, plano_atual)
            modal = self.modalidade or "presencial"

            # Dúvidas sobre comparação/parcelamento devem manter o paciente na etapa
            # em vez de avançar direto para agendamento.
            if compreensao["topico_duvida"] in {"pagamento", "planos"} or any(w in msg.lower() for w in [
                "duvida", "dúvida", "não sei", "nao sei", "?",
            ]):
                return [
                    _responder_duvida_pagamento(plano_atual, modal, plano_upgrade)
                    + f"\n\nPrefere seguir com o *{kb.get_plano(plano_atual)['nome']}* "
                    f"ou o *{kb.get_plano(plano_upgrade)['nome']}* faz mais sentido pra você?"
                ]

            interpretacao = _interpretar_mensagem_etapa(
                self.historico,
                "escolha_plano",
                msg,
                {
                    "plano_atual": plano_atual,
                    "plano_upgrade": plano_upgrade,
                    "modalidade": modal,
                    "upsell_oferecido": self.upsell_oferecido,
                },
            )

            if interpretacao.get("plano") in upgrades:
                self.plano_escolhido = interpretacao["plano"]
                plano_atual = self.plano_escolhido
                plano_upgrade = upgrades.get(plano_atual, plano_atual)

            if interpretacao.get("acao") in {"tirar_duvida", "resposta_livre"} and interpretacao.get("resposta_sugerida"):
                return [interpretacao["resposta_sugerida"]]

            if interpretacao.get("aceita_upgrade") or (compreensao["afirmacao"] and not compreensao["negacao"]) or "premium" in msg.lower():
                self.plano_escolhido = upgrades.get(self.plano_escolhido, self.plano_escolhido)
            elif interpretacao.get("manter_plano") or compreensao["negacao"]:
                pass

        self.etapa = "preferencia_horario"
        return [MSG_PREFERENCIA_HORARIO]

    def _etapa_preferencia_horario(self, msg: str) -> list[str]:
        """Interpreta a necessidade da paciente e só então consulta a agenda."""
        interpretacao = _interpretar_preferencia_horario(msg)
        if interpretacao["acao"] != "buscar":
            return [
                "Me diz do jeito que for mais fácil 😊\n\n"
                "Pode ser, por exemplo:\n"
                "• quarta à tarde\n"
                "• qualquer dia às 19h\n"
                "• o horário mais próximo"
            ]

        self._preferencia_horas = interpretacao["horas_preferidas"]
        self._preferencia_dia = interpretacao["dia_preferido"]
        self._agendamento_modo = interpretacao["modo_busca"]
        self._preferencia_texto = interpretacao["descricao_preferencia"]
        self.etapa = "agendamento"
        return self._iniciar_agendamento()

    def _iniciar_agendamento(self) -> list[str]:
        horas_preferidas: set[str] | None = getattr(self, "_preferencia_horas", None)
        dia_preferido: int | None = getattr(self, "_preferencia_dia", None)
        modo_busca: str = getattr(self, "_agendamento_modo", "preferencia")
        hoje_iso = date.today().isoformat()  # "2026-04-20"

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

        # D-19: nunca oferecer slot do dia atual
        slots = [s for s in slots if not s.get("datetime", "").startswith(hoje_iso)]

        if not slots:
            return [MSG_SEM_HORARIOS]

        selecionados, aviso_preferencia = _selecionar_slots_agendamento(
            slots=slots,
            horas_preferidas=horas_preferidas,
            dia_preferido=dia_preferido,
            modo_busca=modo_busca,
        )

        if not selecionados:
            return [MSG_SEM_HORARIOS]

        self._slots_oferecidos = selecionados
        opcoes = "\n".join(
            f"{i+1}. {s['data_fmt']} às {s['hora']}"
            for i, s in enumerate(self._slots_oferecidos)
        )
        mensagem_opcoes = MSG_AGENDAMENTO_OPCOES.format(
            modalidade=self.modalidade,
            opcoes=opcoes,
        )
        if aviso_preferencia:
            mensagem_opcoes = f"{aviso_preferencia}\n\n{opcoes}\n\nQual horário funciona melhor pra você?"
        return [
            waiting,
            mensagem_opcoes,
        ]

    def _etapa_agendamento(self, msg: str) -> list[str]:
        slots = getattr(self, "_slots_oferecidos", [])
        interpretacao = _interpretar_preferencia_horario(msg)
        msg_lower = msg.lower()

        if interpretacao["acao"] == "buscar":
            self._preferencia_horas = interpretacao["horas_preferidas"]
            self._preferencia_dia = interpretacao["dia_preferido"]
            self._agendamento_modo = interpretacao["modo_busca"]
            self._preferencia_texto = interpretacao["descricao_preferencia"]
            return self._iniciar_agendamento()

        # tenta identificar a escolha (1, 2 ou 3)
        escolha = None
        for i, word in enumerate(["1", "primeiro", "2", "segundo", "3", "terceiro"]):
            if word in msg_lower:
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
        compreensao = _compreender_turno_atendimento("forma_pagamento", msg)
        if compreensao["forma_pagamento"] == "pix":
            self.forma_pagamento = "pix"
        elif compreensao["forma_pagamento"] == "cartao":
            self.forma_pagamento = "cartao"
        else:
            if compreensao["topico_duvida"] in {"pagamento", "politica"}:
                plano = self.plano_escolhido or "unica"
                modal = self.modalidade or "presencial"
                return [
                    f"{_resposta_contextual_topico('pagamento', plano, modal)}\n\n"
                    "Qual opção prefere: *PIX* ou *cartão*?"
                ]
            interpretacao = _interpretar_mensagem_etapa(
                self.historico,
                "forma_pagamento",
                msg,
                {
                    "plano_escolhido": self.plano_escolhido,
                    "modalidade": self.modalidade,
                    "slot_escolhido": self.slot_escolhido,
                },
            )
            if interpretacao.get("forma_pagamento") == "pix":
                self.forma_pagamento = "pix"
            elif interpretacao.get("forma_pagamento") == "cartao":
                self.forma_pagamento = "cartao"
            elif interpretacao.get("acao") in {"tirar_duvida", "resposta_livre"} and interpretacao.get("resposta_sugerida"):
                return [interpretacao["resposta_sugerida"]]
            elif any(w in msg_lower for w in ["divide", "parcel", "cartão", "cartao", "pix", "desconto"]):
                plano = self.plano_escolhido or "unica"
                modal = self.modalidade or "presencial"
                return [
                    "Funciona assim 😊\n\n"
                    f"• {_resumo_pagamento_plano(plano, modal)}\n"
                    f"• No PIX você paga com desconto e no cartão o valor vai parcelado\n\n"
                    "Qual opção prefere: *PIX* ou *cartão*?"
                ]
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
        compreensao = _compreender_turno_atendimento("pagamento", msg)
        if compreensao["topico_duvida"] in {"pagamento", "politica"}:
            plano = self.plano_escolhido or "unica"
            modal = self.modalidade or "presencial"
            return [
                f"{_resposta_contextual_topico(compreensao['topico_duvida'], plano, modal)}\n\n"
                "Quando concluir, me manda o comprovante para eu confirmar sua consulta 😊"
            ]
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
                valor_sinal=round(kb.get_valor(self.plano_escolhido or "unica", self.modalidade or "presencial") * 0.5, 2),
                forma_pagamento=self.forma_pagamento or "pix",
            )

            if resultado["sucesso"]:
                self.id_paciente_dietbox = resultado["id_paciente"]
                self.id_agenda_dietbox = resultado["id_agenda"]
                self.id_transacao_dietbox = resultado.get("id_transacao")
                # Marca pagamento como pago no Dietbox (sinal ja recebido)
                if self.id_transacao_dietbox:
                    try:
                        confirmar_pagamento(self.id_transacao_dietbox)
                    except Exception as exc:
                        logger.warning("Falha ao confirmar pagamento no Dietbox: %s", exc)
            else:
                logger.error("Dietbox falhou: %s", resultado.get("erro"))
                return [waiting, MSG_ERRO_AGENDAMENTO_DIETBOX]

        except Exception as e:
            logger.error("Erro no cadastro Dietbox: %s", e)
            return [waiting, MSG_ERRO_AGENDAMENTO_DIETBOX]

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
            "_slots_oferecidos": getattr(self, "_slots_oferecidos", []),
            "_preferencia_horas": sorted(getattr(self, "_preferencia_horas", []) or []),
            "_preferencia_dia": getattr(self, "_preferencia_dia", None),
            "_agendamento_modo": getattr(self, "_agendamento_modo", "preferencia"),
            "_preferencia_texto": getattr(self, "_preferencia_texto", ""),
            "forma_pagamento": self.forma_pagamento,
            "pagamento_confirmado": self.pagamento_confirmado,
            "id_paciente_dietbox": self.id_paciente_dietbox,
            "id_agenda_dietbox": self.id_agenda_dietbox,
            "id_transacao_dietbox": self.id_transacao_dietbox,
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
        agent._slots_oferecidos = data.get("_slots_oferecidos", [])
        agent._preferencia_horas = set(data.get("_preferencia_horas", [])) or None
        agent._preferencia_dia = data.get("_preferencia_dia")
        agent._agendamento_modo = data.get("_agendamento_modo", "preferencia")
        agent._preferencia_texto = data.get("_preferencia_texto", "")
        agent.forma_pagamento = data.get("forma_pagamento")
        agent.pagamento_confirmado = data.get("pagamento_confirmado", False)
        agent.id_paciente_dietbox = data.get("id_paciente_dietbox")
        agent.id_agenda_dietbox = data.get("id_agenda_dietbox")
        agent.id_transacao_dietbox = data.get("id_transacao_dietbox")
        agent.historico = data.get("historico", [])
        return agent


# ── helpers ───────────────────────────────────────────────────────────────────

def _extrair_nome(msg: str) -> str | None:
    """Extrai primeiro(s) nome(s) da mensagem (heurística simples).

    Aceita nomes digitados em minúsculo (comum no WhatsApp).
    """
    import re

    _NAO_NOMES = {
        "tenho", "quero", "gostaria", "preciso", "estou", "sou", "minha", "meu",
        "para", "sobre", "posso", "fazer", "qual", "como", "quando", "onde",
        "primeira", "segunda", "nova", "boa", "bom", "tudo", "bem",
        "oi", "ola", "olá", "sim", "nao", "não", "ja", "já", "ok",
        "emagrecer", "ganhar", "massa", "lipedema", "outro", "objetivo",
        "consulta", "paciente", "retorno", "cancelar", "remarcar",
        "online", "presencial", "agendar", "marcar",
    }

    # Remove saudações comuns
    limpo = re.sub(
        r"^(oi|olá|ola|bom dia|boa tarde|boa noite|tudo bem|tudo bom|meu nome [eé]|me chamo|sou o|sou a|sou)[,!.]*\s*",
        "",
        msg.strip(),
        flags=re.IGNORECASE,
    )

    tokens = limpo.strip().split()
    nome_partes = []
    for t in tokens[:4]:
        t_clean = t.strip(",.!?")
        if not t_clean.isalpha() or len(t_clean) < 2:
            break
        if t_clean.lower() in _NAO_NOMES:
            break
        nome_partes.append(t_clean.capitalize())

    if len(nome_partes) >= 1:
        return " ".join(nome_partes)
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
