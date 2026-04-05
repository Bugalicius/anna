"""
Base de conhecimento estática + dados gerados na Fase 1.

Carregada uma vez na inicialização e servida como dict/texto para os Agentes 1 e 2.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_KB_DIR = Path(__file__).parent.parent / "knowledge_base"

# ── Dados estáticos (documentação V2.0) ──────────────────────────────────────

PLANOS: dict[str, dict] = {
    "premium": {
        "nome": "Plano Premium",
        "descricao": "Acompanhamento completo mensal com retorno e suporte contínuo",
        "presencial": 1200.00,
        "online": 1080.00,
        "parcelas": 10,
        "inclui": [
            "Consulta inicial (60 min)",
            "Retorno quinzenal",
            "Plano alimentar personalizado",
            "Suporte via WhatsApp 5 dias/semana",
            "Análise de exames",
            "Cálculo de composição corporal",
        ],
    },
    "ouro": {
        "nome": "Plano Ouro",
        "descricao": "Acompanhamento mensal com retorno",
        "presencial": 690.00,
        "online": 570.00,
        "parcelas": 6,
        "inclui": [
            "Consulta inicial (60 min)",
            "Retorno mensal",
            "Plano alimentar personalizado",
            "Suporte via WhatsApp 3 dias/semana",
        ],
    },
    "com_retorno": {
        "nome": "Consulta com Retorno",
        "descricao": "Consulta inicial + 1 retorno em até 30 dias",
        "presencial": 480.00,
        "online": 400.00,
        "parcelas": 4,
        "inclui": [
            "Consulta inicial (60 min)",
            "1 retorno em até 30 dias",
            "Plano alimentar personalizado",
        ],
    },
    "unica": {
        "nome": "Consulta Única",
        "descricao": "Consulta avulsa sem retorno incluso",
        "presencial": 260.00,
        "online": 220.00,
        "parcelas": 3,
        "inclui": [
            "Consulta (60 min)",
            "Plano alimentar personalizado",
        ],
    },
    "formulario": {
        "nome": "Formulário / Avaliação Online",
        "descricao": "Avaliação nutricional por formulário sem consulta ao vivo",
        "presencial": 100.00,
        "online": 100.00,
        "parcelas": 2,
        "inclui": [
            "Formulário de anamnese detalhado",
            "Plano alimentar personalizado enviado em até 72h",
        ],
        "observacao": "Não oferecer proativamente — apenas se paciente perguntar",
    },
}

POLITICAS: dict[str, str] = {
    "pagamento": (
        "O pagamento deve ser realizado antes ou no dia da consulta. "
        "Aceitamos PIX (chave CPF: 14994735670) e cartão de crédito via link de pagamento. "
        "Para cartão, o link é gerado e enviado pelo WhatsApp."
    ),
    "cancelamento": (
        "Cancelamentos com aviso de até 24h de antecedência não geram cobrança. "
        "Cancelamentos com menos de 24h ou no-show podem ser cobrados como consulta avulsa."
    ),
    "tolerancia": (
        "A consulta aguarda até 15 minutos de atraso. "
        "Após 15 minutos sem aviso, a consulta pode ser reagendada e cobrada normalmente."
    ),
    "remarcacao": (
        "Remarcações devem ser feitas com no mínimo 4h de antecedência. "
        "Disponível até 7 dias antes da consulta original."
    ),
    "horarios": (
        "Atendimento de segunda a sexta, das 08h às 19h. "
        "Sexta-feira: apenas até 17h. Sábados e domingos sem atendimento."
    ),
    "modalidades": (
        "Presencial: Clínica em BH/MG. "
        "Online: videochamada via Google Meet ou WhatsApp Video — link enviado no dia."
    ),
}

CONTATOS: dict[str, str] = {
    "pix_chave": "14994735670",
    "numero_nutri_publico": "5531991394759",  # enviar ao paciente se solicitar contato direto
    # NUNCA expor ao paciente:
    "_numero_interno": "3199205-9211",
}

REGRAS_UPSELL: list[str] = [
    "Se paciente escolher 'unica', apresentar 'com_retorno' como upgrade (só +R$220/R$180 online)",
    "Se paciente escolher 'com_retorno', apresentar 'ouro' como upgrade (mais suporte)",
    "Nunca rebaixar: se paciente escolheu plano maior, não sugerir plano menor",
    "Oferecer upsell apenas UMA vez — se paciente recusar, aceitar a escolha",
    "Formulário: NUNCA oferecer proativamente; só confirmar se paciente perguntar diretamente",
]

FAQ_ESTATICO: list[dict[str, str]] = [
    {
        "pergunta": "Atende sábado?",
        "resposta": "Não, o atendimento é de segunda a sexta, das 08h às 17h às sextas e até 19h nos outros dias.",
    },
    {
        "pergunta": "Quanto custa a consulta?",
        "resposta": (
            "Temos quatro planos: Consulta Única (R$260 presencial / R$220 online), "
            "Consulta com Retorno (R$480 / R$400), Plano Ouro (R$690 / R$570) e "
            "Plano Premium (R$1.200 / R$1.080). Posso te enviar os detalhes de cada um?"
        ),
    },
    {
        "pergunta": "Aceita plano de saúde?",
        "resposta": "No momento o atendimento é particular. Mas temos parcelamento em até 10x no cartão 💚",
    },
    {
        "pergunta": "Quanto tempo dura a consulta?",
        "resposta": "A consulta inicial dura em torno de 60 minutos.",
    },
    {
        "pergunta": "Como funciona a consulta online?",
        "resposta": (
            "É feita por videochamada (Google Meet ou WhatsApp Video). "
            "O link é enviado no dia da consulta. Funciona exatamente como a presencial!"
        ),
    },
    {
        "pergunta": "Como pago?",
        "resposta": (
            "Aceitamos PIX (chave CPF 14994735670) ou cartão de crédito via link de pagamento. "
            "No cartão, parcelamos em até 10x dependendo do plano."
        ),
    },
    {
        "pergunta": "Posso remarcar?",
        "resposta": (
            "Sim! Remarcações com pelo menos 4h de antecedência não têm custo. "
            "Me avisa aqui pelo WhatsApp e a gente encontra um horário melhor."
        ),
    },
    {
        "pergunta": "Onde fica a clínica?",
        "resposta": "A Thaynara atende em BH/MG. Após o agendamento envio o endereço completo 😊",
    },
]


# ── Carregamento dos arquivos gerados na Fase 1 ───────────────────────────────

def _load_json(filename: str) -> Any:
    path = _KB_DIR / filename
    if not path.exists():
        logger.warning("knowledge_base/%s não encontrado — ignorando", filename)
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("Erro ao carregar knowledge_base/%s: %s", filename, e)
        return []


def _load_text(filename: str) -> str:
    path = _KB_DIR / filename
    if not path.exists():
        logger.warning("knowledge_base/%s não encontrado — ignorando", filename)
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Erro ao carregar knowledge_base/%s: %s", filename, e)
        return ""


# ── Interface pública ─────────────────────────────────────────────────────────

class KnowledgeBase:
    """Singleton carregado uma vez na inicialização do app."""

    def __init__(self) -> None:
        self.planos = PLANOS
        self.politicas = POLITICAS
        self.contatos = CONTATOS
        self.regras_upsell = REGRAS_UPSELL
        self.faq_estatico = FAQ_ESTATICO

        # Dados gerados na Fase 1
        self.faq_minerado: list[dict] = _load_json("faq.json")
        self.objections: list[dict] = _load_json("objections.json")
        self.remarketing: list[dict] = _load_json("remarketing.json")
        self.tone_guide: str = _load_text("tone_guide.md")
        self.system_prompt_base: str = _load_text("system_prompt.md")

    # ── helpers ──────────────────────────────────────────────────────────────

    def get_plano(self, nome: str) -> dict | None:
        """Retorna dados completos do plano ou None se não existir."""
        return self.planos.get(nome.lower())

    def get_valor(self, plano: str, modalidade: str) -> float:
        """Retorna valor do plano na modalidade ou 0.0 se não encontrado."""
        p = self.get_plano(plano)
        if not p:
            return 0.0
        return p.get(modalidade.lower(), 0.0)

    def get_parcelas(self, plano: str) -> int:
        return self.planos.get(plano.lower(), {}).get("parcelas", 1)

    def get_politica(self, chave: str) -> str:
        return self.politicas.get(chave, "")

    def resumo_planos_texto(self) -> str:
        """Texto compacto com todos os planos para incluir no prompt dos agentes."""
        linhas = []
        for k, p in self.planos.items():
            if k == "formulario":
                continue  # não exibir proativamente
            linhas.append(
                f"- {p['nome']}: R${p['presencial']:.0f} presencial / R${p['online']:.0f} online"
                f" (até {p['parcelas']}x no cartão)"
            )
        return "\n".join(linhas)

    def faq_combinado(self) -> list[dict[str, str]]:
        """FAQ estático + perguntas mineradas com frequência > 1."""
        resultado = list(self.faq_estatico)
        for item in self.faq_minerado:
            if item.get("frequency", 0) > 1 and item.get("suggested_answer"):
                resultado.append({
                    "pergunta": item["question"],
                    "resposta": item["suggested_answer"],
                })
        return resultado

    def system_prompt(self) -> str:
        """Prompt de sistema completo para o Agente 1."""
        planos_txt = self.resumo_planos_texto()
        politicas_txt = "\n".join(f"- **{k}**: {v}" for k, v in self.politicas.items())

        return f"""Você é Ana, assistente virtual da nutricionista Thaynara Teixeira.
Seu objetivo é agendar consultas com empatia, clareza e naturalidade em português brasileiro informal.

## Planos disponíveis
{planos_txt}

## Políticas
{politicas_txt}

## Pagamento
- PIX: chave CPF {self.contatos['pix_chave']}
- Cartão: link de pagamento enviado pelo WhatsApp (até {self.planos['premium']['parcelas']}x sem juros no Premium)

## Regras importantes
- NUNCA mencione o número interno da clínica
- Nunca prometa resultados clínicos específicos
- Ao detectar objeção: reconheça antes de apresentar solução
- Ofereça no máximo 3 opções de horário por vez
- Confirme o nome antes de avançar para pagamento
- Formulário (R$100): NÃO oferecer proativamente — apenas confirmar se perguntarem

## Tom
{self.tone_guide or 'Empático, profissional mas descontraído. Use emojis com moderação (💚).'}
"""


# Instância global (inicializada na primeira importação)
kb = KnowledgeBase()
