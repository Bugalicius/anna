"""
Base de conhecimento estática + dados gerados na Fase 1.

Carregada uma vez na inicialização e servida como dict/texto para os Agentes 1 e 2.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BRT = timezone(timedelta(hours=-3))

logger = logging.getLogger(__name__)

_KB_DIR = Path(__file__).parent.parent / "knowledge_base"

# ── Dados estáticos (documentação V2.0) ──────────────────────────────────────

PLANOS: dict[str, dict] = {
    "premium": {
        "nome": "Plano Premium",
        "descricao": "O mais indicado. 6 consultas + 270 dias de acompanhamento",
        "presencial": 1200.00,
        "online": 1080.00,
        "parcela_presencial": 140.00,
        "parcela_online": 126.00,
        "parcelas": 10,
        "inclui": [
            "6 consultas + 270 dias de acompanhamento",
            "Plano alimentar personalizado (montado junto com a paciente)",
            "Ajustes e check-ins semanais",
            "Lilly (assistente virtual nutricional)",
            "Grupo exclusivo no WhatsApp",
            "#NossoMomentoEmMovimento (encontros coletivos)",
            "Galão de água 950ml personalizado",
            "Mochilinha personalizada + brindes exclusivos",
            "Guia 'Do mercado ao prato'",
            "Guia 'Contenção de danos no fds'",
            "E-book '100 doces saudáveis'",
            "E-book 'Receitas para fazer na Airfryer'",
            "Avaliação física + anamnese completa",
            "Aplicativo de acompanhamento",
            "Suporte por WhatsApp",
            "Desconto especial na renovação",
        ],
    },
    "ouro": {
        "nome": "Plano Ouro",
        "descricao": "O mais procurado. 3 consultas + 130 dias de acompanhamento",
        "presencial": 690.00,
        "online": 570.00,
        "parcela_presencial": 128.00,
        "parcela_online": 106.00,
        "parcelas": 6,
        "inclui": [
            "3 consultas + 130 dias de acompanhamento",
            "Plano alimentar personalizado",
            "Ajustes e check-ins semanais",
            "Lilly (assistente virtual nutricional)",
            "Galão de água 950ml personalizado",
            "Guia 'Do mercado ao prato'",
            "Guia 'Contenção de danos no fds'",
            "E-book '100 doces saudáveis'",
            "Avaliação física + anamnese completa",
            "Aplicativo de acompanhamento",
            "Suporte por WhatsApp",
        ],
    },
    "com_retorno": {
        "nome": "Consulta com Retorno",
        "descricao": "Consulta inicial + 1 retorno em até 45 dias",
        "presencial": 480.00,
        "online": 400.00,
        "parcela_presencial": 130.00,
        "parcela_online": 109.00,
        "parcelas": 4,
        "inclui": [
            "Consulta inicial (60 min)",
            "1 retorno em até 45 dias",
            "Plano alimentar personalizado",
            "Guia 'Do mercado ao prato'",
            "Guia 'Contenção de danos no fds'",
            "Avaliação física + anamnese completa",
            "Aplicativo de acompanhamento",
            "Suporte por WhatsApp",
        ],
    },
    "unica": {
        "nome": "Consulta Única",
        "descricao": "Consulta avulsa sem retorno incluso",
        "presencial": 260.00,
        "online": 220.00,
        "parcela_presencial": 93.00,
        "parcela_online": 79.00,
        "parcelas": 3,
        "inclui": [
            "Consulta (60 min)",
            "Plano alimentar personalizado",
            "Guia 'Do mercado ao prato'",
            "Guia 'Contenção de danos no fds'",
            "Avaliação física + anamnese completa",
            "Aplicativo de acompanhamento",
            "Suporte por WhatsApp",
        ],
    },
    "formulario": {
        "nome": "Dieta por Formulário",
        "descricao": "Plano alimentar personalizado sem consulta ao vivo",
        "presencial": 100.00,
        "online": 100.00,
        "parcela_presencial": 53.00,
        "parcela_online": 53.00,
        "parcelas": 2,
        "inclui": [
            "Formulário de anamnese detalhado",
            "Plano alimentar personalizado enviado em até 5 dias úteis",
            "Avaliação física por fotos",
        ],
        "observacao": "Não oferecer proativamente — apenas se paciente perguntar",
    },
}

POLITICAS: dict[str, str] = {
    "pagamento": (
        "O agendamento só é confirmado após o pagamento antecipado. "
        "PIX: sinal de 50% do valor escolhido. Chave PIX (CPF): 14994735670. "
        "Cartão: pagamento integral via link da Rede (parcelamento disponível)."
    ),
    "cancelamento": (
        "Cancelamentos/remarcações devem ser feitos com pelo menos 24h de antecedência. "
        "Consulta remarcada deve ser realizada em até 7 dias corridos da data original. "
        "Não comparecimento ou desistência: consulta considerada realizada, sem reembolso."
    ),
    "tolerancia": (
        "Tolerância máxima de 10 minutos de atraso. "
        "Após 10 minutos sem aviso, a consulta pode ser reagendada e cobrada normalmente."
    ),
    "remarcacao": (
        "Remarcações devem ser feitas com pelo menos 24h de antecedência. "
        "Consulta remarcada deve ser realizada em até 7 dias corridos da data original."
    ),
    "horarios": (
        "Segunda a quinta: manhã (08h, 09h, 10h), tarde (15h, 16h, 17h), noite (18h, 19h). "
        "Sexta: manhã (08h, 09h, 10h), tarde (15h, 16h, 17h). Sexta à noite: sem atendimento. "
        "Sábados e domingos: sem atendimento em hipótese alguma."
    ),
    "modalidades": (
        "Presencial: Aura Clinic & Beauty, Rua Melo Franco 204/Sala 103, Jardim da Glória, Vespasiano/MG. "
        "Online: videochamada pelo WhatsApp — a nutricionista liga para o número cadastrado. "
        "Avaliação física online é feita por fotos."
    ),
    "restricoes": (
        "Não atendemos gestantes ou menores de 16 anos."
    ),
}

CONTATOS: dict[str, str] = {
    "pix_chave": "14994735670",
    "numero_nutri_publico": "5531991394759",  # enviar ao paciente se solicitar contato direto
    "clinica_nome": "Aura Clinic & Beauty",
    "clinica_endereco": "Rua Melo Franco, 204, Sala 103, Jardim da Glória, Vespasiano/MG",
    "clinica_referencia": "Ao lado da loja de móveis, na rua da academia Pratique Fitness. A 350m da Linha Verde.",
    "clinica_maps": "https://maps.app.goo.gl/XxHgHxHh7aCxitDs8",
    "formulario_link": "https://forms.gle/CsBmdxq9FLHJYJuZA",
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

REGRAS_DOCUMENTO: dict[str, list[str] | dict[str, str]] = {
    "comunicacao": [
        "Sempre responder em português brasileiro, linguagem informal e acolhedora.",
        "Sempre tratar o paciente pelo primeiro nome assim que souber.",
        "Nunca enviar mensagens excessivamente longas.",
        "Nunca enviar duas perguntas na mesma mensagem, exceto na abertura guiada do fluxo.",
        "Aguardar a resposta do paciente antes de avançar para a próxima etapa.",
    ],
    "lgpd": [
        "Nunca compartilhar dados de um paciente com outro.",
        "Nunca armazenar dados sensíveis de saúde fora do Dietbox.",
        "Comprovantes de pagamento devem ser encaminhados à Thaynara e não armazenados pelo agente.",
        "Número real do paciente nunca sai do servidor para LLM externo.",
    ],
    "cadastro_obrigatorio": {
        "nome": "Nome completo",
        "data_nascimento": "Data de nascimento",
        "whatsapp": "WhatsApp",
        "email": "E-mail",
    },
    "cadastro_opcional": {
        "instagram": "Instagram",
        "profissao": "Profissão",
        "cep_endereco": "CEP/endereço",
        "indicacao_origem": "Indicação/origem",
    },
}

FAQ_ESTATICO: list[dict[str, str]] = [
    {
        "pergunta": "Atende sábado?",
        "resposta": "Não, o atendimento é de segunda a sexta. Sexta à noite também não tem. Sábados e domingos sem atendimento em hipótese alguma 😊",
    },
    {
        "pergunta": "Quanto custa a consulta?",
        "resposta": (
            "Temos quatro opções: Consulta Única (R$260 presencial / R$220 online), "
            "Consulta com Retorno (R$480 / R$400), Plano Ouro (R$690 / R$570) e "
            "Plano Premium (R$1.200 / R$1.080). Posso te enviar nosso material completo com todos os detalhes? 💚"
        ),
    },
    {
        "pergunta": "Aceita plano de saúde?",
        "resposta": "No momento o atendimento é particular. Mas temos parcelamento em até 10x no cartão 💚",
    },
    {
        "pergunta": "Quanto tempo dura a consulta?",
        "resposta": "Em média 60 minutos, com abordagem detalhada e plano personalizado 😊",
    },
    {
        "pergunta": "Como funciona a consulta online?",
        "resposta": (
            "É feita por videochamada pelo próprio WhatsApp — a Thaynara liga no número que você cadastrar. "
            "A avaliação física é feita por fotos. Funciona exatamente como a presencial!"
        ),
    },
    {
        "pergunta": "Como pago?",
        "resposta": (
            "Via PIX (sinal de 50%: chave CPF 14994735670) ou cartão de crédito via link de pagamento. "
            "No cartão o valor é integral, parcelamos conforme o plano escolhido."
        ),
    },
    {
        "pergunta": "Posso remarcar?",
        "resposta": (
            "Sim! Com pelo menos 24h de antecedência, sem custo. "
            "A consulta remarcada precisa ser realizada em até 7 dias corridos da data original. "
            "Me avisa aqui e a gente acha um horário melhor 😊"
        ),
    },
    {
        "pergunta": "Onde fica a clínica?",
        "resposta": (
            "A Thaynara atende na Aura Clinic & Beauty, "
            "Rua Melo Franco, 204, Sala 103, Jardim da Glória, Vespasiano/MG. "
            "Fica ao lado da loja de móveis, na rua da academia Pratique Fitness, a 350m da Linha Verde 😊 "
            "https://maps.app.goo.gl/XxHgHxHh7aCxitDs8"
        ),
    },
    {
        "pergunta": "Faz bioimpedância?",
        "resposta": (
            "A Thaynara não usa bioimpedância porque ela pode apresentar muitas variações e precisa de preparo específico. "
            "No lugar, ela usa o adipômetro, que é bem mais preciso! Com ele identifica percentual de gordura e massa magra. "
            "Além disso avalia circunferências corporais e faz fotos para acompanhar sua evolução mês a mês! 📸💚"
        ),
    },
    {
        "pergunta": "Atende gestantes?",
        "resposta": "Não atendemos gestantes nem menores de 16 anos, tudo bem?",
    },
    {
        "pergunta": "O que é a Lilly?",
        "resposta": (
            "A Lilly é uma assistente virtual exclusiva dos Planos Ouro e Premium! "
            "Sempre que precisar trocar um alimento do plano, é só perguntar pra ela. "
            "Ela sugere substituições que mantêm o plano equilibrado 💚"
        ),
    },
    {
        "pergunta": "Tem desconto para família?",
        "resposta": (
            "Sim! Quando duas pessoas fecham juntas (casal, mãe e filha, irmãs etc.), "
            "damos 10% de desconto no valor total. "
            "As consultas são em horários sequenciais. Posso verificar a disponibilidade! 😊"
        ),
    },
]


# ── Expressões características (extraídas de 1.283 conversas reais) ──────────

EXPRESSOES_CONFIRMACAO: list[str] = [
    "Perfeitoooo. Obrigadaaa 💚🥰",
    "Confirmado então! Obrigadaaa 💚😉",
    "Perfeito! Tudo confirmado 💚",
]

EXPRESSAO_DISPONHA: str = "Por nada. Disponha! 💚🥰"
PERGUNTA_PLANO: str = "Qual será o plano e modalidade?"
PERGUNTA_TURNO: str = "Em qual turno?"


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
        self.regras_documento = REGRAS_DOCUMENTO
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
            parc_p = p.get("parcela_presencial", p["presencial"] / p["parcelas"])
            parc_o = p.get("parcela_online", p["online"] / p["parcelas"])
            linhas.append(
                f"- *{p['nome']}*: {p['parcelas']}x de R${parc_p:.0f} presencial "
                f"ou R${parc_o:.0f} online (ou R${p['presencial']:.0f}/R${p['online']:.0f} no PIX)"
            )
        return "\n".join(linhas)

    def faq_combinado(self) -> list[dict[str, str]]:
        """FAQ estático + perguntas mineradas com frequência > 1 + FAQ aprendido do Breno (D-11)."""
        resultado = list(self.faq_estatico)
        for item in self.faq_minerado:
            if item.get("frequency", 0) > 1 and item.get("suggested_answer"):
                resultado.append({
                    "pergunta": item["question"],
                    "resposta": item["suggested_answer"],
                })
        # FAQ aprendido (D-11)
        if _FAQ_APRENDIDO_FILE.exists():
            try:
                aprendido = json.loads(_FAQ_APRENDIDO_FILE.read_text(encoding="utf-8"))
                for item in aprendido:
                    resultado.append({
                        "pergunta": item["pergunta"],
                        "resposta": item["resposta"],
                    })
            except Exception as e:
                logger.error("Erro ao carregar FAQ aprendido: %s", e)
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
- Confirme pagamento antes de avançar para cadastro
- Nunca confirme consulta antes do cadastro obrigatório estar completo
- Cadastro obrigatório no Dietbox: nome completo, data de nascimento, WhatsApp e e-mail
- Formulário (R$100): NÃO oferecer proativamente — apenas confirmar se perguntarem

## Tom
{self.tone_guide or 'Empático, profissional mas descontraído. Use emojis com moderação (💚).'}
"""


# ── FAQ Aprendido — persistido em arquivo JSON (D-11) ─────────────────────────

_FAQ_APRENDIDO_FILE = _KB_DIR / "faq_aprendido.json"


def salvar_faq_aprendido(pergunta: str, resposta: str) -> None:
    """
    Salva par pergunta/resposta aprendido do Breno na knowledge base.
    Persiste em arquivo JSON para sobreviver a deploys (D-11).
    Evita duplicatas — atualiza resposta se mesma pergunta já existir.
    """
    faq_list: list[dict] = []
    if _FAQ_APRENDIDO_FILE.exists():
        try:
            faq_list = json.loads(_FAQ_APRENDIDO_FILE.read_text(encoding="utf-8"))
        except Exception:
            faq_list = []

    # Evitar duplicatas exatas — atualiza resposta existente
    for item in faq_list:
        if item.get("pergunta", "").lower().strip() == pergunta.lower().strip():
            item["resposta"] = resposta
            _FAQ_APRENDIDO_FILE.write_text(
                json.dumps(faq_list, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info("FAQ aprendido atualizado: %s", pergunta[:50])
            return

    faq_list.append({
        "pergunta": pergunta,
        "resposta": resposta,
        "source": "breno_relay",
        "created_at": datetime.now(BRT).isoformat(),
    })
    _FAQ_APRENDIDO_FILE.write_text(
        json.dumps(faq_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("FAQ aprendido salvo: %s", pergunta[:50])


# Instância global (inicializada na primeira importação)
kb = KnowledgeBase()
