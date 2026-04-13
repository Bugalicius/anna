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
from datetime import date, datetime, timedelta, timezone

import anthropic

from app.agents.dietbox_worker import (
    alterar_agendamento,
    buscar_paciente_por_telefone,
    consultar_agendamento_ativo,
    consultar_slots_disponiveis,
    verificar_lancamento_financeiro,
)
from app.knowledge_base import kb

logger = logging.getLogger(__name__)

BRT = timezone(timedelta(hours=-3))


# ── Cálculo de janela de remarcação ───────────────────────────────────────────

def calcular_fim_janela(data_consulta: date) -> date:
    """
    Retorna a sexta-feira da semana SEGUINTE à semana do agendamento original.

    Algoritmo (per D-05):
      - Semana começa na segunda (weekday 0).
      - "Semana seguinte" = adiciona 7 dias à data, depois ajusta para a segunda dessa semana.
      - Ex: qualquer dia da semana 13-17/abr → prox segunda = 20/abr → sexta = 24/abr.
    """
    dia_da_semana = data_consulta.weekday()  # 0=seg … 6=dom
    # Dias até a próxima segunda: se já for segunda, avança 7 (força semana seguinte)
    dias_ate_prox_segunda = (7 - dia_da_semana) % 7 or 7
    prox_segunda = data_consulta + timedelta(days=dias_ate_prox_segunda)
    return prox_segunda + timedelta(days=4)  # segunda + 4 = sexta

# ── Sequência de remarketing ──────────────────────────────────────────────────

REMARKETING_SEQ: list[dict] = [
    {
        "posicao": 1,
        "delay_horas": 24,
        "mensagem": (
            "Oi, {nome}! Tudo bem? 💚\n\n"
            "Sei que decidir investir em saúde às vezes gera aquele frio na barriga... "
            "será que é o momento certo? Será que vai funcionar pra mim? É completamente normal.\n\n"
            "Mas vou te falar uma coisa: a maioria das pacientes da Thaynara já pensaram assim antes de começar. "
            "Me conta com sinceridade: o que está travando sua decisão? "
            "Preço, horário, dúvida sobre o método? Me fala pra gente tentar resolver 💚"
        ),
    },
    {
        "posicao": 2,
        "delay_horas": 24 * 7,
        "mensagem": (
            "Oi, {nome}! Tudo bem?\n\n"
            "Passando só pra saber se você conseguiu ver as informações que te enviei "
            "sobre os atendimentos com a Nutri Thaynara 💚\n\n"
            "Se ficou alguma dúvida ou quiser conversar melhor sobre o que se encaixa no seu momento, "
            "estou por aqui pra te ajudar. "
            "Você gostaria que eu te lembrasse mais pra frente ou prefere já garantir sua vaga agora?"
        ),
    },
    {
        "posicao": 3,
        "delay_horas": 24 * 30,
        "mensagem": (
            "Oi, {nome}!\n\n"
            "No mês passado você fez contato comigo e percebi que nossa conversa ficou em aberto "
            "e queria entender se ainda posso te ajudar com o agendamento. "
            "Só me avisa pra eu não te incomodar, tá bom?"
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
    "Tudo bem, {nome}. Podemos remarcar sim, sem problema 😊\n\n"
    "Só queria te orientar que no momento a agenda da Thaynara está bem cheia. "
    "Se você conseguir fazer um esforço para manter o horário agendado, "
    "seria ótimo para não prejudicar seu acompanhamento.\n\n"
    "Caso realmente não consiga, conseguimos realizar o agendamento dentro dos próximos 7 dias, "
    "que é o prazo máximo para a remarcação.\n\n"
    "Quais são os melhores horários e dias para você? 📅"
)

MSG_OPCOES_REMARCACAO = (
    "Ótimo! Encontrei estas opções disponíveis:\n\n"
    "{opcoes}\n\n"
    "Qual funciona melhor pra você?"
)

MSG_CONFIRMACAO_REMARCACAO = (
    "✅ *Consulta remarcada com sucesso!*\n\n"
    "📅 *Nova data:* {data} às {hora}\n"
    "📍 *Modalidade:* {modalidade}\n\n"
    "Qualquer dúvida, é só me chamar aqui 💚"
)

MSG_ERRO_REMARCACAO_DIETBOX = (
    "Ops! Tive um problema técnico ao tentar confirmar a remarcação no sistema 😔\n\n"
    "Vou acionar a Thaynara para resolver isso manualmente. "
    "Você receberá uma confirmação assim que estiver tudo certo 💚"
)

MSG_ERRO_REMARCACAO_RETRY = (
    "Ainda estou com dificuldade técnica para confirmar no sistema 😔\n\n"
    "Por favor, entre em contato diretamente com a Thaynara para garantir sua remarcação. "
    "Me desculpe o inconveniente! 💚"
)

MSG_SEGUNDA_RODADA = (
    "Entendo 😊 Vou buscar mais opções pra você:\n\n"
    "{opcoes}\n\n"
    "Alguma dessas funciona?"
)

MSG_PERDA_RETORNO = (
    "Infelizmente não conseguimos encontrar um horário que funcione para você "
    "dentro do prazo de remarcação 😔\n\n"
    "Como o prazo se encerra em breve, o retorno não poderá mais ser remarcado.\n\n"
    "Mas posso te ajudar a agendar uma consulta nova! Quer que eu verifique os "
    "planos disponíveis para você? 💚"
)

MSG_SEM_MAIS_SLOTS = (
    "Não há mais horários disponíveis na janela de remarcação 😔\n\n"
    "Como o prazo se encerra em breve, o retorno não poderá mais ser remarcado.\n\n"
    "Mas posso te ajudar a agendar uma consulta nova! Quer que eu verifique os "
    "planos disponíveis para você? 💚"
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
        self.nome = nome  # pode ser None — vamos perguntar se necessário
        self.modalidade = modalidade
        self.etapa: str = "inicio"
        self.motivo: str | None = None
        self.consulta_atual: dict | None = None
        self.novo_slot: dict | None = None
        self._slots_oferecidos: list[dict] = []
        self._preferencia_horario: str = ""
        self.historico: list[dict] = []
        # ── Campos Phase 2 ────────────────────────────────────────────────────
        self.tipo_remarcacao: str | None = None      # "retorno" | "nova_consulta"
        self.id_agenda_original: str | None = None
        self.fim_janela: date | None = None          # sexta da semana seguinte ao agendamento
        self.rodada_negociacao: int = 0
        self._slots_pool: list[dict] = []            # pool completo (não apenas os 3 oferecidos)

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
            # ── Phase 2 ──────────────────────────────────────────────────────
            "tipo_remarcacao": self.tipo_remarcacao,
            "id_agenda_original": self.id_agenda_original,
            "fim_janela": self.fim_janela.isoformat() if self.fim_janela else None,
            "rodada_negociacao": self.rodada_negociacao,
            "_slots_pool": self._slots_pool,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgenteRetencao":
        """Restaura instância a partir de dict serializado.

        Usa .get(campo, default) para todos os campos — compatível com estados
        Phase 1 que não possuem os campos novos (T-02-01-01).
        """
        agent = cls(
            telefone=data["telefone"],
            nome=data.get("nome"),
            modalidade=data.get("modalidade", "presencial"),
        )
        agent.etapa = data.get("etapa", "inicio")
        agent.motivo = data.get("motivo")
        agent.consulta_atual = data.get("consulta_atual")
        agent.novo_slot = data.get("novo_slot")
        agent._slots_oferecidos = data.get("_slots_oferecidos", [])
        agent._preferencia_horario = data.get("_preferencia_horario", "")
        agent.historico = data.get("historico", [])
        # ── Phase 2 — default seguro para estados Phase 1 ────────────────────
        agent.tipo_remarcacao = data.get("tipo_remarcacao")
        agent.id_agenda_original = data.get("id_agenda_original")
        fim_janela_str = data.get("fim_janela")
        agent.fim_janela = date.fromisoformat(fim_janela_str) if fim_janela_str else None
        agent.rodada_negociacao = data.get("rodada_negociacao", 0)
        agent._slots_pool = data.get("_slots_pool", [])
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

    # ── detecção retorno / nova consulta ──────────────────────────────────────

    def _detectar_tipo_remarcacao(self) -> str:
        """
        Determina se o paciente está fazendo remarcação de retorno (já pagou) ou
        nova consulta (sem agendamento/lançamento ativo).

        Retorna "retorno" | "nova_consulta" e salva self.tipo_remarcacao.
        Per D-03, D-04, D-25.
        """
        paciente = buscar_paciente_por_telefone(self.telefone)
        if not paciente:
            logger.info("Paciente não encontrado no Dietbox (%s) — nova_consulta", self.telefone[-4:])
            self.tipo_remarcacao = "nova_consulta"
            return "nova_consulta"

        id_paciente = paciente.get("id")
        agenda = consultar_agendamento_ativo(id_paciente=int(id_paciente))
        if not agenda:
            logger.info("Sem agendamento ativo para paciente %s — nova_consulta", self.telefone[-4:])
            self.tipo_remarcacao = "nova_consulta"
            return "nova_consulta"

        tem_lancamento = verificar_lancamento_financeiro(id_agenda=agenda["id"])
        if not tem_lancamento:
            logger.info("Agendamento sem lançamento financeiro (%s) — nova_consulta", agenda["id"])
            self.tipo_remarcacao = "nova_consulta"
            return "nova_consulta"

        # Retorno confirmado: salva estado
        self.tipo_remarcacao = "retorno"
        self.id_agenda_original = agenda["id"]
        # Calcula janela a partir da data do agendamento original (per D-05)
        try:
            dt_consulta = date.fromisoformat(agenda["inicio"][:10])
            self.fim_janela = calcular_fim_janela(dt_consulta)
        except Exception as e:
            logger.error("Erro ao calcular fim_janela: %s", e)
            self.fim_janela = calcular_fim_janela(date.today())

        logger.info("Tipo remarcação detectado: retorno (agenda=%s)", agenda["id"])
        return "retorno"

    # ── remarcação ────────────────────────────────────────────────────────────

    def _fluxo_remarcacao(self, msg: str) -> list[str]:
        # Etapa 0: se não temos o nome, pedir primeiro
        if self.etapa == "inicio" and not self.nome:
            self.etapa = "coletando_nome"
            return ["Claro! Para eu verificar seu agendamento, pode me informar seu nome completo? 😊"]

        if self.etapa == "coletando_nome":
            self.nome = _extrair_nome_simples(msg)
            self.etapa = "inicio"
            # cai no próximo bloco

        # Etapa 1: detecta tipo de remarcação e apresenta política
        if self.etapa == "inicio":
            tipo = self._detectar_tipo_remarcacao()
            if tipo == "nova_consulta":
                self.etapa = "redirecionando_atendimento"
                return [
                    "Não localizei um agendamento já confirmado para você 😊\n"
                    "Vou te passar para o fluxo de agendamento normal — me conta o que você está procurando!"
                ]
            self.etapa = "coletando_preferencia"
            return [MSG_INICIO_REMARCACAO.format(nome=self.nome or "")]

        # Etapa 2: recebeu preferência → buscar slots compatíveis
        if self.etapa == "coletando_preferencia":
            self._preferencia_horario = msg
            self.etapa = "oferecendo_slots"

            msg_lower = msg.lower()

            # Parse do dia da semana preferido
            dia_preferido: int | None = None
            _DIAS = [
                ("segunda", 0), ("terça", 1), ("terca", 1),
                ("quarta", 2), ("quinta", 3), ("sexta", 4),
                ("sábado", 5), ("sabado", 5),
            ]
            for palavra, idx in _DIAS:
                if palavra in msg_lower:
                    dia_preferido = idx
                    break

            # Parse da hora preferida (aceita "8h", "8H", "8:00", "08", "9h", etc.)
            import re as _re
            hora_preferida: int | None = None
            m = _re.search(r'\b(\d{1,2})[hH:]', msg)
            if not m:
                m = _re.search(r'\b(\d{1,2})\b', msg)
            if m:
                h = int(m.group(1))
                if 6 <= h <= 20:
                    hora_preferida = h

            hoje_d = date.today()

            # Janela correta (per D-05, D-06):
            # - início: amanhã (nunca hoje)
            # - fim: sexta da semana seguinte ao agendamento original
            data_inicio_busca = hoje_d + timedelta(days=1)
            data_fim_janela = self.fim_janela or calcular_fim_janela(hoje_d)
            dias_a_frente = max(1, (data_fim_janela - hoje_d).days)

            try:
                todos_slots = consultar_slots_disponiveis(
                    modalidade=self.modalidade,
                    dias_a_frente=dias_a_frente,
                    data_inicio=data_inicio_busca,
                )
            except Exception as e:
                logger.error("Erro ao consultar slots: %s", e)
                todos_slots = []

            # Salva pool completo para uso futuro (negociação de rodadas)
            self._slots_pool = todos_slots

            if not todos_slots:
                self.etapa = "sem_horarios"
                return [
                    "Infelizmente não encontrei horários disponíveis nos próximos 7 dias. "
                    "Vou verificar com a Thaynara e te retorno em breve 🔍"
                ]

            # ── Aviso se a preferência de dia não está disponível (per D-12) ──
            aviso: str | None = None
            _NOMES_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

            if dia_preferido is not None:
                dia_nome = _NOMES_DIAS[dia_preferido]
                slots_dia = [
                    s for s in todos_slots
                    if datetime.fromisoformat(s["datetime"]).weekday() == dia_preferido
                ]
                if not slots_dia:
                    aviso = (
                        f"Não tenho {dia_nome}-feira disponível nos próximos 7 dias, "
                        f"mas veja o que temos:"
                    )

            # _priorizar_slots faz toda a seleção com preferência embutida
            self._slots_oferecidos = _priorizar_slots(todos_slots, dia_preferido, hora_preferida)

            opcoes = "\n".join(
                f"{i+1}. {s['data_fmt']} às {s['hora']}"
                for i, s in enumerate(self._slots_oferecidos)
            )

            msgs_ret = []
            if aviso:
                msgs_ret.append(aviso)
            msgs_ret.append(MSG_OPCOES_REMARCACAO.format(opcoes=opcoes))
            return msgs_ret

        # Etapa 3: paciente escolheu um slot (com negociação em 2 rodadas — T-02-02-02)
        if self.etapa == "oferecendo_slots":
            slot = _extrair_escolha_slot(msg, self._slots_oferecidos)
            if slot:
                self.novo_slot = slot
                self.etapa = "aguardando_confirmacao_dietbox"
                # Indicador de espera antes de chamar Dietbox (per comportamento Fase 1)
                return ["Um instante, por favor 💚"]

            # Rejeição: calcula próximo batch
            slots_oferecidos_dts = {s["datetime"] for s in self._slots_oferecidos}
            next_batch = [s for s in self._slots_pool if s["datetime"] not in slots_oferecidos_dts]

            # Condição de perda: sem mais slots OU já na rodada 1 (máx 2 rodadas)
            if not next_batch or self.rodada_negociacao >= 1:
                self.etapa = "perda_retorno"
                msg_perda = MSG_SEM_MAIS_SLOTS if not next_batch else MSG_PERDA_RETORNO
                return [msg_perda]

            # Segunda rodada: oferece mais 3 do pool restante
            self.rodada_negociacao += 1
            self._slots_oferecidos = _priorizar_slots(next_batch, None, None)
            opcoes = "\n".join(
                f"{i+1}. {s['data_fmt']} às {s['hora']}"
                for i, s in enumerate(self._slots_oferecidos)
            )
            return [MSG_SEGUNDA_RODADA.format(opcoes=opcoes)]

        # Etapa 4: chamar Dietbox para alterar agendamento e confirmar ao paciente (per D-20/D-21)
        if self.etapa == "aguardando_confirmacao_dietbox":
            if not self.novo_slot:
                # Estado inconsistente — não deveria acontecer
                logger.error(
                    "aguardando_confirmacao_dietbox sem novo_slot: telefone=%s",
                    self.telefone[-4:],
                )
                self.etapa = "erro_remarcacao"
                return [MSG_ERRO_REMARCACAO_DIETBOX]

            from datetime import datetime as _dt
            novo_dt = _dt.fromisoformat(self.novo_slot["datetime"])

            # Monta observação per D-23
            data_original = ""
            if self.consulta_atual:
                inicio_original = self.consulta_atual.get("inicio", "")
                if inicio_original:
                    try:
                        dt_orig = _dt.fromisoformat(inicio_original)
                        data_original = dt_orig.strftime("%d/%m/%Y")
                    except ValueError:
                        data_original = inicio_original[:10]
            data_nova = novo_dt.strftime("%d/%m/%Y")
            observacao = (
                f"Remarcado do dia {data_original} para {data_nova}"
                if data_original
                else f"Remarcado para {data_nova}"
            )

            id_agenda = self.id_agenda_original or ""
            sucesso = alterar_agendamento(id_agenda, novo_dt, observacao)

            if sucesso:
                self.etapa = "concluido"
                return [MSG_CONFIRMACAO_REMARCACAO.format(
                    data=self.novo_slot["data_fmt"],
                    hora=self.novo_slot["hora"],
                    modalidade=self.modalidade,
                )]
            else:
                self.etapa = "erro_remarcacao"
                return [MSG_ERRO_REMARCACAO_DIETBOX]

        # Etapa 5: erro técnico — orientar paciente a contatar a Thaynara
        if self.etapa == "erro_remarcacao":
            return [MSG_ERRO_REMARCACAO_RETRY]

        # Etapa 6: perda de retorno — qualquer mensagem redireciona para atendimento
        if self.etapa == "perda_retorno":
            self.etapa = "redirecionando_atendimento"
            return ["Claro! Vou te encaminhar para o fluxo de agendamento normal 💚"]

        return [_gerar_resposta_llm_retencao(self.historico, self.etapa)]

    # ── cancelamento ──────────────────────────────────────────────────────────

    def _fluxo_cancelamento(self, msg: str) -> list[str]:
        # Pede nome se não temos
        if self.etapa == "inicio" and not self.nome:
            self.etapa = "coletando_nome_cancel"
            return ["Claro! Para eu localizar seu agendamento, pode me informar seu nome completo? 😊"]

        if self.etapa == "coletando_nome_cancel":
            self.nome = _extrair_nome_simples(msg)
            self.etapa = "inicio"
            # cai no próximo bloco

        if self.etapa == "inicio":
            self.etapa = "aguardando_motivo"
            return [
                MSG_INICIO_CANCELAMENTO.format(nome=self.nome or ""),
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

def _hora_int(slot: dict) -> int:
    """Extrai a hora do slot como inteiro (ex: '9h' → 9, '14:00' → 14)."""
    import re as _re
    hora_str = slot.get("hora", "0")
    m = _re.search(r'(\d{1,2})', hora_str)
    return int(m.group(1)) if m else 0


def _priorizar_slots(
    pool: list[dict],
    dia_preferido: int | None,
    hora_preferida: int | None,
) -> list[dict]:
    """
    Seleciona até 3 slots com priorização (per D-09 a D-13):
      - Opção 1: slot que melhor corresponde à preferência (dia + hora)
      - Opções 2 e 3: próximos disponíveis em dias diferentes da opção 1
      - Se sem preferência: 3 primeiros em dias diferentes
      - D-13: slots em dias diferentes são preferidos — nunca 3 no mesmo dia se houver alternativa

    Valida que cada slot tem chave 'datetime' antes de usar (T-02-02-01).
    """
    # T-02-02-01: filtrar slots inválidos
    pool = [s for s in pool if s.get("datetime")]

    if not pool:
        return []

    selecionados: list[dict] = []

    if dia_preferido is not None:
        # Tenta encontrar slot correspondente à preferência
        slots_dia_pref = [
            s for s in pool
            if datetime.fromisoformat(s["datetime"]).weekday() == dia_preferido
        ]

        slot_escolhido: dict | None = None
        if slots_dia_pref:
            if hora_preferida is not None:
                slots_exatos = [s for s in slots_dia_pref if _hora_int(s) == hora_preferida]
                slot_escolhido = slots_exatos[0] if slots_exatos else slots_dia_pref[0]
            else:
                slot_escolhido = slots_dia_pref[0]

        if slot_escolhido:
            selecionados = [slot_escolhido]
            dia_slot_escolhido = datetime.fromisoformat(slot_escolhido["datetime"]).weekday()
            dias_usados: set[int] = {dia_slot_escolhido}

            # Preencher posições 2 e 3 com dias diferentes do slot escolhido
            for s in pool:
                if s is slot_escolhido:
                    continue
                dia_s = datetime.fromisoformat(s["datetime"]).weekday()
                if dia_s not in dias_usados:
                    selecionados.append(s)
                    dias_usados.add(dia_s)
                if len(selecionados) >= 3:
                    break

            # Se ainda faltam slots (pool com só 1-2 dias diferentes), completa com qualquer slot
            if len(selecionados) < 3:
                for s in pool:
                    if s not in selecionados:
                        selecionados.append(s)
                    if len(selecionados) >= 3:
                        break

            return selecionados

    # Modo sem preferência (ou preferência não encontrada):
    # Percorrer pool priorizando dias diferentes
    dias_usados_nd: set[int] = set()
    resultado: list[dict] = []
    restantes: list[dict] = []

    for s in pool:
        dia_s = datetime.fromisoformat(s["datetime"]).weekday()
        if dia_s not in dias_usados_nd and len(resultado) < 3:
            resultado.append(s)
            dias_usados_nd.add(dia_s)
        else:
            restantes.append(s)
        if len(resultado) >= 3:
            break

    # Se não há 3 dias diferentes, completa com próximos slots
    if len(resultado) < 3:
        for s in restantes:
            resultado.append(s)
            if len(resultado) >= 3:
                break

    return resultado[:3]


def _extrair_nome_simples(msg: str) -> str:
    """Extrai o primeiro nome da mensagem."""
    import re
    limpo = re.sub(r"^(oi|olá|ola|bom dia|boa tarde|sou|me chamo|meu nome é|meu nome e)[,!.\s]*",
                   "", msg.strip(), flags=re.IGNORECASE)
    partes = [p.strip(",.!?") for p in limpo.split() if len(p.strip(",.!?")) > 2]
    return partes[0].capitalize() if partes else msg.split()[0].capitalize()


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
