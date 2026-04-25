"""
Planner LLM-driven — decide a próxima ação com Claude Haiku.

Substitui o planner baseado em if/else por raciocínio do LLM.
O modelo recebe o estado completo + turno interpretado e decide sozinho
a próxima ação, tornando o sistema robusto a casos de borda.

Função pública:
  decidir_acao(turno, state) -> dict  (plano)
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime

import anthropic
from app.knowledge_base import kb

logger = logging.getLogger(__name__)

# ── Constantes de ação (usadas pelo engine e responder) ───────────────────────

ASK_FIELD                 = "ask_field"
SEND_PLANOS               = "send_planos"
OFFER_UPSELL              = "offer_upsell"
ASK_SLOT_CHOICE           = "ask_slot_choice"
ASK_FORMA_PAGAMENTO       = "ask_forma_pagamento"
AWAIT_PAYMENT             = "await_payment"
ANSWER_QUESTION           = "answer_question"
ESCALATE                  = "escalate"
REMARKETING_RECUSA        = "handle_remarketing_refusal"
FORA_DE_CONTEXTO          = "respond_fora_de_contexto"
EXECUTE_TOOL              = "execute_tool"
SEND_FORMULARIO           = "send_formulario_instrucoes"
ASK_MOTIVO_CANCEL         = "ask_motivo_cancelamento"
SEND_CONFIRMACAO          = "send_confirmacao"
SEND_CONFIRMACAO_REMARCAR = "send_confirmacao_remarcacao"
SEND_CONFIRMACAO_CANCEL   = "send_confirmacao_cancelamento"
ABANDON_PROCESS           = "abandon_process"

# Mantidos apenas para compatibilidade com imports externos
APPLY_UPGRADE        = "apply_upgrade"
SLOT_CONFIRMED       = "slot_confirmed"
PAGAMENTO_CONFIRMADO = "pagamento_confirmado"
REDIRECT_RETENCAO    = "redirect_retencao"
REDIRECT_ATENDIMENTO = "redirect_atendimento"

_VALID_ACTIONS = {
    ASK_FIELD, SEND_PLANOS, OFFER_UPSELL, ASK_SLOT_CHOICE, ASK_FORMA_PAGAMENTO,
    AWAIT_PAYMENT, ANSWER_QUESTION, ESCALATE, REMARKETING_RECUSA, FORA_DE_CONTEXTO,
    EXECUTE_TOOL, SEND_FORMULARIO, ASK_MOTIVO_CANCEL, SEND_CONFIRMACAO,
    SEND_CONFIRMACAO_REMARCAR, SEND_CONFIRMACAO_CANCEL, ABANDON_PROCESS,
    "answer_free", "send_formulario_link",
}

_VALID_TOOLS = {
    "consultar_slots", "consultar_slots_remarcar", "agendar", "remarcar_dietbox",
    "cancelar", "gerar_link_cartao", "detectar_tipo_remarcacao", "perda_retorno",
    "confirmar_pagamento_dietbox",
}


def _nome_completo(nome: str | None) -> bool:
    if not nome:
        return False
    partes = [p for p in str(nome).strip().split() if len(p) >= 2]
    return len(partes) >= 2


def _campos_cadastro_faltantes(cd: dict) -> list[str]:
    faltantes: list[str] = []
    if not _nome_completo(cd.get("nome")):
        faltantes.append("nome")
    if not _normalizar_data_nascimento(cd.get("data_nascimento")):
        faltantes.append("data_nascimento")
    if not _email_valido(cd.get("email")):
        faltantes.append("email")
    return faltantes


def stateful_value(value: str | None) -> bool:
    return bool(str(value).strip()) if value is not None else False


def _email_valido(value: str | None) -> bool:
    if not value:
        return False
    return bool(re.search(r"\b[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}\b", str(value), re.I))


def _normalizar_data_nascimento(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip().lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", raw)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})\b", raw)
    if m:
        dia, mes, ano = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if ano < 100:
            ano += 2000 if ano <= datetime.now().year % 100 else 1900
        try:
            return date(ano, mes, dia).isoformat()
        except ValueError:
            return None
    return None

# ── Prompt ────────────────────────────────────────────────────────────────────

_PROMPT = """\
Você é o Planner do assistente Ana (agendamentos — nutricionista Thaynara Teixeira, CRN9 31020).

Analise o estado atual e o turno do paciente. Decida a ÚNICA próxima ação.

## ESTADO ATUAL
phone: {phone}
phone_hash: {phone_hash}
goal: {goal}
status: {status}
tipo_remarcacao: {tipo_remarcacao}  (null | retorno | nova_consulta)
last_action: {last_action}

Dados coletados:
  nome: {nome}
  status_paciente: {status_paciente}  (null | novo | retorno)
  objetivo: {objetivo}
  plano: {plano}  (null | unica | com_retorno | ouro | premium | formulario)
  modalidade: {modalidade}  (null | presencial | online)
  preferencia_horario: {preferencia_horario}
  forma_pagamento: {forma_pagamento}  (null | pix | cartao)
  data_nascimento: {data_nascimento}
  email: {email}
  instagram: {instagram}
  profissao: {profissao}
  cep_endereco: {cep_endereco}
  indicacao_origem: {indicacao_origem}
  motivo_cancelamento: {motivo_cancelamento}

Flags:
  upsell_oferecido: {upsell_oferecido}
  planos_enviados: {planos_enviados}
  pagamento_confirmado: {pagamento_confirmado}
  aguardando_motivo_cancel: {aguardando_motivo_cancel}

Appointment:
  slot_escolhido: {slot_escolhido}
  id_agenda: {id_agenda}
  id_paciente: {id_paciente}
  consulta_atual: {consulta_atual}

Slots oferecidos (last_slots_offered):
{slots_summary}

## TURNO DO PACIENTE
intent: {intent}
nome extraído: {t_nome}
status_paciente extraído: {t_status}
objetivo extraído: {t_objetivo}
plano extraído: {t_plano}
modalidade extraída: {t_modalidade}
preferencia_horario extraída: {t_pref}
forma_pagamento extraída: {t_pagamento}
data_nascimento extraída: {t_data_nascimento}
email extraído: {t_email}
instagram extraído: {t_instagram}
profissao extraída: {t_profissao}
cep_endereco extraído: {t_cep_endereco}
indicacao_origem extraído: {t_indicacao_origem}
escolha_slot: {t_escolha}  (1, 2 ou 3 — índice nos slots oferecidos)
aceita_upgrade: {t_upgrade}  (true | false | null)
confirmou_pagamento: {t_confirmou}
tem_pergunta: {t_tem_pergunta}
topico_pergunta: {t_topico}

## REGRAS DE DECISÃO

### REGRAS GERAIS OBRIGATÓRIAS
- Siga a documentação operacional como prioridade: pagamento verificado antes de cadastro; cadastro obrigatório antes de agendar/confirmar.
- Dados obrigatórios de cadastro no Dietbox: nome completo, data de nascimento, WhatsApp, e-mail.
- Nunca confirme consulta antes do cadastro obrigatório estar completo.
- Nunca faça duas perguntas diferentes na mesma mensagem, exceto na mensagem inicial de boas-vindas.

### PRIORIDADES ABSOLUTAS (verificar antes de tudo):
1. intent=duvida_clinica E tem_pergunta=true → {{"action":"escalate"}}
2. intent=recusou_remarketing → {{"action":"handle_remarketing_refusal","new_status":"concluido"}}
3. tem_pergunta=true E topico_pergunta em [pagamento,planos,modalidade,politica]
   E status≠aguardando_pagamento E slot_escolhido=null
   → {{"action":"answer_question","ask_context":"<topico>"}}

### FLUXO CANCELAMENTO (intent=cancelar OU goal=cancelar):
a) aguardando_motivo_cancel=false
   → {{"action":"ask_motivo_cancelamento","update_flags":{{"aguardando_motivo_cancel":true}}}}
b) last_action≠cancelar
   → {{"action":"execute_tool","tool":"cancelar","params":{{"telefone":"{phone}","motivo":"<motivo_cancelamento ou mensagem>"}}}}
c) → {{"action":"send_confirmacao_cancelamento","new_status":"concluido"}}

### FLUXO NOVO PACIENTE / AGENDAMENTO (intent=agendar OU goal=agendar_consulta):
Percorra em ordem. Execute a PRIMEIRA etapa incompleta:

ETAPA 1 — Identificação:
  a) nome=null → {{"action":"ask_field","ask_context":"nome"}}
  b) status_paciente=null → {{"action":"ask_field","ask_context":"status_paciente"}}
  c) status_paciente=retorno E tipo_remarcacao=null
     → {{"action":"execute_tool","tool":"detectar_tipo_remarcacao","params":{{"telefone":"{phone}"}}}}
     (após resultado: se tipo=nova_consulta → continuar como novo com update_data status_paciente=novo;
      se tipo=retorno → ir para FLUXO REMARCAÇÃO)

ETAPA 2 — Objetivo:
  d) objetivo=null → {{"action":"ask_field","ask_context":"objetivo"}}

ETAPA 3 — Planos:
  e) planos_enviados=false → {{"action":"send_planos","update_flags":{{"planos_enviados":true}}}}
  f) plano=null → {{"action":"ask_field","ask_context":"plano"}}

  g) Upsell (plano em [unica,com_retorno,ouro] E upsell_oferecido=false):
     - aceita_upgrade=true → aplicar upgrade diretamente:
       plano_upgrade: unica→ouro, com_retorno→ouro, ouro→premium
       {{"action":"ask_field","ask_context":"modalidade","update_data":{{"plano":"<plano_upgrade>"}},"update_flags":{{"upsell_oferecido":true}}}}
       (ou próxima etapa incompleta se modalidade já preenchida)
     - caso contrário → {{"action":"offer_upsell","ask_context":"<plano_atual>","update_flags":{{"upsell_oferecido":true}}}}

ETAPA 4 — Modalidade:
  h) modalidade=null → {{"action":"ask_field","ask_context":"modalidade"}}

ETAPA 5 — Horário e slots:
  i) preferencia_horario=null E slots_oferecidos vazios
     → {{"action":"ask_field","ask_context":"preferencia_horario"}}
  j) slots_oferecidos vazios
     → {{"action":"execute_tool","tool":"consultar_slots","params":{{"modalidade":"<modalidade>","preferencia":<preferencia_horario_dict>}}}}
  k) slot_escolhido=null:
     - escolha_slot válida (1-3) E slot existe
       → {{"action":"ask_forma_pagamento","update_appointment":{{"slot_escolhido":<slot_objeto_completo>}}}}
     - caso contrário → {{"action":"ask_slot_choice"}}

ETAPA 6 — Pagamento:
  l) forma_pagamento=null → {{"action":"ask_forma_pagamento"}}
  m) forma_pagamento=cartao E last_action≠gerar_link_cartao
     → {{"action":"execute_tool","tool":"gerar_link_cartao","params":{{"plano":"<plano>","modalidade":"<modalidade>","phone_hash":"{phone_hash}"}}}}
  n) pagamento_confirmado=false:
     - confirmou_pagamento=true
       → {{"action":"ask_field","ask_context":"cadastro","update_flags":{{"pagamento_confirmado":true}}}}
     - caso contrário → {{"action":"await_payment","new_status":"aguardando_pagamento"}}

ETAPA 7 — Cadastro obrigatório:
  o) nome não for completo → {{"action":"ask_field","ask_context":"nome"}}
  p) data_nascimento=null → {{"action":"ask_field","ask_context":"data_nascimento"}}
  q) email=null → {{"action":"ask_field","ask_context":"email"}}
  r) id_agenda=null E pagamento_confirmado=true
     → {{"action":"execute_tool","tool":"agendar","params":{{"nome":"<nome>","telefone":"{phone}","plano":"<plano>","modalidade":"<modalidade>","slot":<slot_escolhido>,"forma_pagamento":"<forma_pagamento>","data_nascimento":"<data_nascimento>","email":"<email>","instagram":"<instagram>","profissao":"<profissao>","cep_endereco":"<cep_endereco>","indicacao_origem":"<indicacao_origem>"}}}}

ETAPA 8 — Confirmação:
  s) id_agenda≠null → {{"action":"send_confirmacao","new_status":"concluido"}}

### PLANO=FORMULÁRIO:
  a) status≠aguardando_pagamento → {{"action":"send_formulario_instrucoes","new_status":"aguardando_pagamento"}}
  b) confirmou_pagamento=true → {{"action":"send_formulario_link","new_status":"concluido"}}
  c) → {{"action":"await_payment"}}

### FLUXO REMARCAÇÃO (tipo_remarcacao=retorno OU intent=remarcar):
  a) tipo_remarcacao=null → {{"action":"execute_tool","tool":"detectar_tipo_remarcacao","params":{{"telefone":"{phone}"}}}}
  b) preferencia_horario=null → {{"action":"ask_field","ask_context":"preferencia_horario_remarcar"}}
  c) slots_oferecidos vazios
     → {{"action":"execute_tool","tool":"consultar_slots_remarcar","params":{{"modalidade":"<modalidade ou presencial>","preferencia":<pref>,"fim_janela":<fim_janela ou null>,"excluir":[]}}}}
  d) slot_escolhido=null:
     - escolha_slot válida
       → {{"action":"execute_tool","tool":"remarcar_dietbox","params":{{"id_agenda_original":"<id_agenda>","novo_slot":<slot_objeto>,"consulta_atual":<consulta_atual>}},"update_appointment":{{"slot_escolhido":<slot_objeto>}}}}
     - caso contrário → {{"action":"ask_slot_choice"}}
  e) last_action=remarcar_dietbox → {{"action":"send_confirmacao_remarcacao","new_status":"concluido"}}

### DÚVIDA / CONTEXTO DESCONHECIDO:
  - intent=tirar_duvida → answer_question se topico conhecido, senão respond_fora_de_contexto
  - intent=fora_de_contexto E goal=desconhecido → {{"action":"respond_fora_de_contexto"}}
  - intent=fora_de_contexto E goal ativo → continuar fluxo do goal (ignorar intent)

## FORMATO DE SAÍDA
JSON puro, sem markdown. Inclua apenas campos necessários:

{{"action":"<ação>","tool":null,"params":{{}},"ask_context":null,"new_status":null,"update_data":{{}},"update_appointment":{{}},"update_flags":{{}},"draft_message":null}}

## DRAFT_MESSAGE — mensagem que a Ana enviará ao paciente
Use para ações conversacionais: ask_field, answer_question, respond_fora_de_contexto, ask_motivo_cancelamento.
Regras:
- Se o paciente disse algo relevante (dúvida, condição médica, informação pessoal), reconheça brevemente antes de perguntar
- Pergunte/responda o que a ação requer de forma natural e acolhedora
- Tom informal, português brasileiro. Máx 4 linhas. Emojis com moderação.
- NÃO inclua valores financeiros, chaves PIX, links ou datas precisas (isso fica nos templates)
- Para execute_tool, send_planos, offer_upsell, await_payment, ask_forma_pagamento, send_confirmacao*, escalate → draft_message: null

Retorne SOMENTE o JSON. Nenhum texto antes ou depois.\
"""

# ── Prompt V2 (simplificado — regras cobertas por override removidas) ─────────
#
# Removidas do _PROMPT original porque já cobertas deterministicamente:
#   ETAPA 3e  → override Regra 1 (send_planos)
#   ETAPA 3g-offer → override Regra 2 (offer_upsell)
#   ETAPA 5i  → override Regra 3 (ask preferencia_horario)
#   ETAPA 5j  → override Regra 4 (consultar_slots)
#   ETAPA 5k-válida → override Regra 5 (ask_forma_pagamento após slot)
#   ETAPA 6m  → override Regra 6 (gerar_link_cartao)
#   ETAPA 6n  → override Regra 6+7 (await_payment / pagamento confirmado)
#   ETAPA 7o-r → override Regra 7 + bloco pós-pagamento (cadastro + agendar)
#
# Mantidas todas as 20 sub-regras não cobertas por override.

_PROMPT_V2 = """\
Você é o Planner do assistente Ana (agendamentos — nutricionista Thaynara Teixeira, CRN9 31020).

Analise o estado atual e o turno do paciente. Decida a ÚNICA próxima ação.

Atenção: as regras de envio de planos, upsell, consulta de slots, confirmação de slot, \
link de cartão, await_payment e agendamento pós-comprovante são executadas deterministicamente \
antes deste prompt. Foque apenas nos casos abaixo.

## ESTADO ATUAL
phone: {phone}
phone_hash: {phone_hash}
goal: {goal}
status: {status}
tipo_remarcacao: {tipo_remarcacao}  (null | retorno | nova_consulta)
last_action: {last_action}

Dados coletados:
  nome: {nome}
  status_paciente: {status_paciente}  (null | novo | retorno)
  objetivo: {objetivo}
  plano: {plano}  (null | unica | com_retorno | ouro | premium | formulario)
  modalidade: {modalidade}  (null | presencial | online)
  preferencia_horario: {preferencia_horario}
  forma_pagamento: {forma_pagamento}  (null | pix | cartao)
  data_nascimento: {data_nascimento}
  email: {email}
  instagram: {instagram}
  profissao: {profissao}
  cep_endereco: {cep_endereco}
  indicacao_origem: {indicacao_origem}
  motivo_cancelamento: {motivo_cancelamento}

Flags:
  upsell_oferecido: {upsell_oferecido}
  planos_enviados: {planos_enviados}
  pagamento_confirmado: {pagamento_confirmado}
  aguardando_motivo_cancel: {aguardando_motivo_cancel}

Appointment:
  slot_escolhido: {slot_escolhido}
  id_agenda: {id_agenda}
  id_paciente: {id_paciente}
  consulta_atual: {consulta_atual}

Slots oferecidos (last_slots_offered):
{slots_summary}

## TURNO DO PACIENTE
intent: {intent}
nome extraído: {t_nome}
status_paciente extraído: {t_status}
objetivo extraído: {t_objetivo}
plano extraído: {t_plano}
modalidade extraída: {t_modalidade}
preferencia_horario extraída: {t_pref}
forma_pagamento extraída: {t_pagamento}
data_nascimento extraída: {t_data_nascimento}
email extraído: {t_email}
instagram extraído: {t_instagram}
profissao extraída: {t_profissao}
cep_endereco extraído: {t_cep_endereco}
indicacao_origem extraído: {t_indicacao_origem}
escolha_slot: {t_escolha}  (1, 2 ou 3 — índice nos slots oferecidos)
aceita_upgrade: {t_upgrade}  (true | false | null)
confirmou_pagamento: {t_confirmou}
tem_pergunta: {t_tem_pergunta}
topico_pergunta: {t_topico}

## REGRAS DE DECISÃO

### PRIORIDADES ABSOLUTAS (verificar antes de tudo):
1. intent=duvida_clinica E tem_pergunta=true → {{"action":"escalate"}}
2. intent=recusou_remarketing → {{"action":"handle_remarketing_refusal","new_status":"concluido"}}
3. tem_pergunta=true E topico_pergunta em [pagamento,planos,modalidade,politica]
   E status≠aguardando_pagamento E slot_escolhido=null
   → {{"action":"answer_question","ask_context":"<topico>"}}

### FLUXO CANCELAMENTO (intent=cancelar OU goal=cancelar):
a) aguardando_motivo_cancel=false
   → {{"action":"ask_motivo_cancelamento","update_flags":{{"aguardando_motivo_cancel":true}}}}
b) last_action≠cancelar
   → {{"action":"execute_tool","tool":"cancelar","params":{{"telefone":"{phone}","motivo":"<motivo_cancelamento ou mensagem>"}}}}
c) → {{"action":"send_confirmacao_cancelamento","new_status":"concluido"}}

### FLUXO NOVO PACIENTE / AGENDAMENTO (intent=agendar OU goal=agendar_consulta):
Percorra em ordem. Execute a PRIMEIRA etapa incompleta:

ETAPA 1 — Identificação:
  a) nome=null → {{"action":"ask_field","ask_context":"nome"}}
  b) status_paciente=null → {{"action":"ask_field","ask_context":"status_paciente"}}
  c) status_paciente=retorno E tipo_remarcacao=null
     → {{"action":"execute_tool","tool":"detectar_tipo_remarcacao","params":{{"telefone":"{phone}"}}}}
     (resultado: tipo=nova_consulta → continuar como novo; tipo=retorno → FLUXO REMARCAÇÃO)

ETAPA 2 — Objetivo:
  d) objetivo=null → {{"action":"ask_field","ask_context":"objetivo"}}

ETAPA 3 — Planos:
  f) plano=null → {{"action":"ask_field","ask_context":"plano"}}
  g) aceita_upgrade=true → aplicar upgrade (unica→ouro, com_retorno→ouro, ouro→premium):
     {{"action":"ask_field","ask_context":"modalidade","update_data":{{"plano":"<plano_upgrade>"}},"update_flags":{{"upsell_oferecido":true}}}}

ETAPA 4 — Modalidade:
  h) modalidade=null → {{"action":"ask_field","ask_context":"modalidade"}}

ETAPA 5 — Slots:
  k) slot_escolhido=null E sem escolha_slot válida nos slots oferecidos
     → {{"action":"ask_slot_choice"}}

ETAPA 6 — Pagamento:
  l) forma_pagamento=null → {{"action":"ask_forma_pagamento"}}

ETAPA 8 — Confirmação:
  s) id_agenda≠null → {{"action":"send_confirmacao","new_status":"concluido"}}

### PLANO=FORMULÁRIO:
  a) status≠aguardando_pagamento → {{"action":"send_formulario_instrucoes","new_status":"aguardando_pagamento"}}
  b) confirmou_pagamento=true → {{"action":"send_formulario_link","new_status":"concluido"}}
  c) → {{"action":"await_payment"}}

### FLUXO REMARCAÇÃO (tipo_remarcacao=retorno OU intent=remarcar):
  a) tipo_remarcacao=null → {{"action":"execute_tool","tool":"detectar_tipo_remarcacao","params":{{"telefone":"{phone}"}}}}
  b) preferencia_horario=null → {{"action":"ask_field","ask_context":"preferencia_horario_remarcar"}}
  c) slots_oferecidos vazios
     → {{"action":"execute_tool","tool":"consultar_slots_remarcar","params":{{"modalidade":"<modalidade ou presencial>","preferencia":<pref>,"fim_janela":<fim_janela ou null>,"excluir":[]}}}}
  d) slot_escolhido=null:
     - escolha_slot válida
       → {{"action":"execute_tool","tool":"remarcar_dietbox","params":{{"id_agenda_original":"<id_agenda>","novo_slot":<slot_objeto>,"consulta_atual":<consulta_atual>}},"update_appointment":{{"slot_escolhido":<slot_objeto>}}}}
     - caso contrário → {{"action":"ask_slot_choice"}}
  e) last_action=remarcar_dietbox → {{"action":"send_confirmacao_remarcacao","new_status":"concluido"}}

### DÚVIDA / CONTEXTO DESCONHECIDO:
  - intent=tirar_duvida → answer_question se topico conhecido, senão respond_fora_de_contexto
  - intent=fora_de_contexto E goal=desconhecido → {{"action":"respond_fora_de_contexto"}}
  - intent=fora_de_contexto E goal ativo → continuar fluxo do goal (ignorar intent)

## FORMATO DE SAÍDA
JSON puro, sem markdown. Inclua apenas campos necessários:

{{"action":"<ação>","tool":null,"params":{{}},"ask_context":null,"new_status":null,"update_data":{{}},"update_appointment":{{}},"update_flags":{{}},"draft_message":null}}

Actions válidas: ask_field, send_planos, offer_upsell, ask_slot_choice, ask_forma_pagamento, \
await_payment, answer_question, escalate, handle_remarketing_refusal, respond_fora_de_contexto, \
execute_tool, send_formulario_instrucoes, ask_motivo_cancelamento, send_confirmacao, \
send_confirmacao_remarcacao, send_confirmacao_cancelamento, answer_free, send_formulario_link

Tools válidas: consultar_slots, consultar_slots_remarcar, agendar, remarcar_dietbox, cancelar, \
gerar_link_cartao, detectar_tipo_remarcacao, perda_retorno, confirmar_pagamento_dietbox

## DRAFT_MESSAGE — mensagem que a Ana enviará ao paciente
Use para ações conversacionais: ask_field, answer_question, respond_fora_de_contexto, ask_motivo_cancelamento.
Regras:
- Se o paciente disse algo relevante, reconheça brevemente antes de perguntar
- Tom informal, português brasileiro. Máx 4 linhas. Emojis com moderação.
- NÃO inclua valores financeiros, chaves PIX, links ou datas precisas (isso fica nos templates)
- Para execute_tool, send_planos, offer_upsell, await_payment, ask_forma_pagamento, send_confirmacao*, escalate → draft_message: null

Retorne SOMENTE o JSON. Nenhum texto antes ou depois.\
"""


# ── Função pública ─────────────────────────────────────────────────────────────


_SAUDACAO = re.compile(
    r"^\s*(oi|ol[áa]|hey|eai|e a[ií]|bom dia|boa tarde|boa noite|opa|fala)\s*[!.,]?\s*$",
    re.IGNORECASE,
)


def _override_cancelamento(turno: dict, state: dict) -> dict | None:
    """
    Regras determinísticas para cancelamento/desistência.

    Distingue dois cenários:
      A) Paciente SEM consulta agendada → "abandonar processo" (encerrar graciosamente)
      B) Paciente COM consulta agendada → fluxo completo de cancelamento

    Exceção: se o paciente envia saudação e o intent NÃO é cancelar,
    ele está tentando recomeçar — não aplicar fluxo de cancelamento.
    """
    cd = state["collected_data"]
    flags = state["flags"]
    appt = state.get("appointment", {})
    goal = state.get("goal", "desconhecido")
    intent = turno.get("intent", "fora_de_contexto")

    # Saudação ou intent diferente de cancelar quando goal=cancelar → resetar
    # O paciente quer recomeçar, não continuar cancelando.
    raw_msg = turno.get("_raw_message", "")
    if goal == "cancelar" and intent != "cancelar":
        if _SAUDACAO.match(raw_msg) or intent == "agendar":
            # Resetar goal para que o fluxo de agendamento recomece
            state["goal"] = "desconhecido"
            state["flags"]["aguardando_motivo_cancel"] = False
            return None  # Deixar o fluxo normal do planner lidar

    tem_consulta = bool(appt.get("id_agenda") or appt.get("consulta_atual"))

    # ── Cenário A: paciente sem consulta quer desistir do processo ──────
    if not tem_consulta:
        return _plano(
            ABANDON_PROCESS,
            new_status="concluido",
            draft_message=(
                "Tudo bem, sem problemas! 😊\n\n"
                "Se mudar de ideia ou tiver alguma dúvida, "
                "é só me chamar aqui. A Thaynara vai adorar te receber 💚"
            ),
        )

    # ── Cenário B: paciente com consulta — fluxo completo ──────────────
    # B1: Ainda não pediu motivo
    if not flags.get("aguardando_motivo_cancel"):
        return _plano(
            ASK_MOTIVO_CANCEL,
            update_flags={"aguardando_motivo_cancel": True},
        )

    # B2: Já pediu motivo, paciente respondeu — executar cancelamento
    # Captura a mensagem como motivo se o motivo não está no collected_data
    if not cd.get("motivo_cancelamento"):
        # A mensagem atual do paciente é o motivo
        last_user = next(
            (m["content"] for m in reversed(state.get("history", []))
             if m["role"] == "user"),
            "não informado",
        )
        motivo = last_user
    else:
        motivo = cd["motivo_cancelamento"]

    if state.get("last_action") != "cancelar":
        return _plano(
            EXECUTE_TOOL,
            tool="cancelar",
            params={"telefone": state.get("phone", ""), "motivo": motivo},
            update_data={"motivo_cancelamento": motivo},
        )

    # B3: Cancelamento já executado — confirmar
    return _plano(SEND_CONFIRMACAO_CANCEL, new_status="concluido")


def _override_deterministic(turno: dict, state: dict) -> dict | None:
    """
    Regras determinísticas que o LLM não pode pular — executadas ANTES do LLM.

    Cobre dois casos críticos onde o LLM tende a ser inconsistente:
      1. Enviar o PDF de planos antes de perguntar qual plano o paciente quer.
      2. Oferecer upsell antes de perguntar a modalidade (quando plano é elegível).
    """
    cd = state["collected_data"]
    flags = state["flags"]
    goal = state.get("goal", "desconhecido")
    intent = turno.get("intent", "fora_de_contexto")

    # ── Fluxo de cancelamento/desistência determinístico ──────────────────
    if intent == "cancelar" or goal == "cancelar":
        override_cancel = _override_cancelamento(turno, state)
        if override_cancel:
            return override_cancel

    # Aplica apenas no fluxo de agendamento
    if goal not in ("agendar_consulta", "desconhecido"):
        return None
    if intent in ("remarcar", "cancelar", "tirar_duvida", "duvida_clinica",
                  "fora_de_contexto", "recusou_remarketing"):
        return None

    # ── Regra 1: send_planos antes de ask_field plano ──────────────────────
    # Ativa quando: objetivo preenchido, planos ainda não enviados, plano não
    # escolhido nem nesta mensagem.
    if (
        cd.get("objetivo")
        and not flags.get("planos_enviados")
        and not cd.get("plano")
        and not turno.get("plano")       # paciente não mencionou plano já
    ):
        return _plano(SEND_PLANOS, update_flags={"planos_enviados": True})

    # ── Regra 2: offer_upsell antes de ask_field modalidade ────────────────
    # Ativa quando: plano elegível escolhido, upsell ainda não oferecido,
    # modalidade não preenchida e paciente não respondeu sobre upgrade nesta msg.
    plano_atual = turno.get("plano") or cd.get("plano")
    if (
        plano_atual in ("unica", "com_retorno", "ouro")
        and not flags.get("upsell_oferecido")
        and not cd.get("modalidade")
        and turno.get("aceita_upgrade") is None  # não respondeu upgrade nesta msg
    ):
        return _plano(OFFER_UPSELL, ask_context=plano_atual,
                      update_flags={"upsell_oferecido": True})

    # ── Regra 2.5: início de conversa nunca cai em saudação genérica repetida ─
    if intent in ("agendar", "fora_de_contexto", "tirar_duvida") and not _nome_completo(cd.get("nome")):
        return _plano(ASK_FIELD, ask_context="nome")
    if intent in ("agendar", "fora_de_contexto", "tirar_duvida") and not cd.get("status_paciente"):
        return _plano(ASK_FIELD, ask_context="status_paciente")

    appt = state.get("appointment", {})
    slots = state.get("last_slots_offered", [])

    # ── Regra 3: ask preferencia_horario antes de consultar slots ──────────
    # O LLM tende a pular para ask_forma_pagamento; este override impede isso.
    if (
        cd.get("plano") and cd.get("modalidade")
        and not cd.get("preferencia_horario")
        and not slots
        and not appt.get("slot_escolhido")
        and state.get("tipo_remarcacao") != "retorno"
    ):
        return _plano(ASK_FIELD, ask_context="preferencia_horario")

    # ── Regra 4: consultar_slots quando preferencia preenchida mas sem slots ─
    if (
        cd.get("plano") and cd.get("modalidade")
        and cd.get("preferencia_horario")
        and not slots
        and not appt.get("slot_escolhido")
        and state.get("last_action") != "consultar_slots"
        and state.get("tipo_remarcacao") != "retorno"
    ):
        return _plano(
            EXECUTE_TOOL, tool="consultar_slots",
            params={"modalidade": cd["modalidade"],
                    "preferencia": cd["preferencia_horario"]},
        )

    # ── Regra 5: confirmar slot quando escolha_slot válida ─────────────────
    # O LLM tende a ignorar escolha_slot e repetir ask_slot_choice.
    # Este override captura a escolha e avança para pagamento deterministicamente.
    escolha = turno.get("escolha_slot")
    if (
        escolha and 1 <= int(escolha) <= len(slots)
        and not appt.get("slot_escolhido")
    ):
        slot_obj = slots[int(escolha) - 1]
        return _plano(ASK_FORMA_PAGAMENTO, update_appointment={"slot_escolhido": slot_obj})

    # ── Regra 6: forma_pagamento capturada deterministicamente ─────────────
    # Após ask_forma_pagamento o LLM às vezes ignora t_pagamento e retorna
    # respond_fora_de_contexto. Este override captura pix/cartao diretamente,
    # inclusive quando o paciente troca de cartão para PIX no meio da etapa.
    t_pagamento = turno.get("forma_pagamento")
    contexto_pagamento_ativo = (
        appt.get("slot_escolhido")
        or state.get("status") == "aguardando_pagamento"
        or state.get("last_action") in ("ask_forma_pagamento", "gerar_link_cartao", "await_payment")
    )

    # ── Regra 6a: "pagar no consultório" / "acertar depois" ─────────────
    _PAGAR_CONSULTORIO = re.compile(
        r"(consult[oó]rio|pessoalmente|l[áa] na hora|na cl[ií]nica|"
        r"acert[oa]r?\s+(o\s+rest|l[áa]|depois|no\s+dia))",
        re.IGNORECASE,
    )
    if (
        contexto_pagamento_ativo
        and _PAGAR_CONSULTORIO.search(turno.get("_raw_message", ""))
        and not turno.get("confirmou_pagamento")
        and not flags.get("pagamento_confirmado")
    ):
        return _plano(
            ANSWER_QUESTION,
            ask_context="pagamento",
            draft_message=(
                "Entendo! 😊 Mas a política da clínica exige o pagamento "
                "antecipado para garantir a reserva do horário.\n\n"
                "Essa é uma forma de assegurar que seu horário fique "
                "exclusivamente reservado pra você 💚\n\n"
                "Pode enviar o comprovante assim que conseguir!"
            ),
        )

    if (
        t_pagamento in ("pix", "cartao")
        and not turno.get("confirmou_pagamento")
        and contexto_pagamento_ativo
        and cd.get("plano")
        and cd.get("modalidade")
        and not flags.get("pagamento_confirmado")
    ):
        if t_pagamento == "cartao":
            return _plano(
                EXECUTE_TOOL, tool="gerar_link_cartao",
                params={
                    "plano": cd.get("plano", "unica"),
                    "modalidade": cd.get("modalidade", "presencial"),
                    "phone_hash": state.get("phone_hash", ""),
                },
                update_data={"forma_pagamento": "cartao"},
            )
        return _plano(
            AWAIT_PAYMENT,
            update_data={"forma_pagamento": "pix"},
            new_status="aguardando_pagamento",
        )

    # ── Regra 7: comprovante em contexto de pagamento avança sem depender do LLM ─
    if (
        turno.get("confirmou_pagamento")
        and contexto_pagamento_ativo
        and cd.get("plano")
        and cd.get("modalidade")
        and appt.get("slot_escolhido")
        and not flags.get("pagamento_confirmado")
    ):
        valor_esperado = kb.get_valor(cd.get("plano"), cd.get("modalidade")) * 0.5
        valor_recebido = turno.get("valor_comprovante")
        if valor_recebido is None:
            return _plano(
                ANSWER_QUESTION,
                ask_context="pagamento",
                draft_message=(
                    "Recebi o comprovante, mas não consegui identificar o valor com segurança. "
                    "Pode me enviar uma imagem mais nítida ou confirmar o valor pago? 😊"
                ),
            )
        if abs(float(valor_recebido) - float(valor_esperado)) > 0.01:
            return _plano(
                ANSWER_QUESTION,
                ask_context="pagamento",
                draft_message=(
                    f"Recebi o comprovante, mas o valor identificado foi R${valor_recebido:.2f} "
                    f"e o sinal dessa opção é R${valor_esperado:.2f}. "
                    "Confere pra mim e, se precisar, me envie o comprovante novamente 😊"
                ),
            )
        id_transacao = appt.get("id_transacao")
        if id_transacao:
            return _plano(
                EXECUTE_TOOL,
                tool="confirmar_pagamento_dietbox",
                params={"id_transacao": id_transacao},
                update_flags={"pagamento_confirmado": True},
            )
        faltantes = _campos_cadastro_faltantes(cd)
        if faltantes:
            ask_context = "cadastro" if len(faltantes) > 1 else faltantes[0]
            return _plano(
                ASK_FIELD,
                ask_context=ask_context,
                update_flags={"pagamento_confirmado": True},
            )
        return _plano(
            EXECUTE_TOOL,
            tool="agendar",
            params={
                "nome": cd.get("nome", ""),
                "telefone": state.get("phone", ""),
                "plano": cd.get("plano"),
                "modalidade": cd.get("modalidade"),
                "slot": appt.get("slot_escolhido"),
                "forma_pagamento": cd.get("forma_pagamento") or "pix",
                "data_nascimento": cd.get("data_nascimento"),
                "email": cd.get("email"),
                "instagram": cd.get("instagram"),
                "profissao": cd.get("profissao"),
                "cep_endereco": cd.get("cep_endereco"),
                "indicacao_origem": cd.get("indicacao_origem"),
            },
            update_flags={"pagamento_confirmado": True},
        )

    if (
        flags.get("pagamento_confirmado")
        and cd.get("plano")
        and cd.get("modalidade")
        and appt.get("slot_escolhido")
        and not appt.get("id_agenda")
    ):
        faltantes = _campos_cadastro_faltantes(cd)
        if faltantes:
            ask_context = "cadastro" if len(faltantes) > 1 else faltantes[0]
            return _plano(ASK_FIELD, ask_context=ask_context)
        return _plano(
            EXECUTE_TOOL,
            tool="agendar",
            params={
                "nome": cd.get("nome", ""),
                "telefone": state.get("phone", ""),
                "plano": cd.get("plano"),
                "modalidade": cd.get("modalidade"),
                "slot": appt.get("slot_escolhido"),
                "forma_pagamento": cd.get("forma_pagamento") or "pix",
                "data_nascimento": cd.get("data_nascimento"),
                "email": cd.get("email"),
                "instagram": cd.get("instagram"),
                "profissao": cd.get("profissao"),
                "cep_endereco": cd.get("cep_endereco"),
                "indicacao_origem": cd.get("indicacao_origem"),
            },
        )

    return None


async def decidir_acao(turno: dict, state: dict) -> dict:
    """
    Chama Claude Haiku para decidir a próxima ação.

    Recebe o estado completo + turno interpretado.
    Retorna um plano com action, tool, params, mutations (update_data, etc.).
    """
    # Regras determinísticas têm prioridade sobre o LLM
    override = _override_deterministic(turno, state)
    if override:
        logger.info("Planner (override): action=%s", override["action"])
        return override

    prompt = _build_prompt(turno, state)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        plano = _parse_plano(data, state)
        logger.info("Planner: action=%s tool=%s", plano["action"], plano.get("tool"))
        return plano

    except Exception as e:
        logger.error("Planner LLM error: %s", e)
        return _fallback(turno, state)


# ── Builders ──────────────────────────────────────────────────────────────────


def _build_prompt(turno: dict, state: dict) -> str:
    cd = state["collected_data"]
    flags = state["flags"]
    appt = state["appointment"]
    slots = state.get("last_slots_offered", [])

    slots_summary = "\n".join(
        f"  {i+1}. {s.get('data_fmt','?')} às {s.get('hora','?')} [{s.get('datetime','?')}]"
        for i, s in enumerate(slots)
    ) or "  (nenhum)"

    version = os.environ.get("PLANNER_PROMPT_VERSION", "v1")
    template = _PROMPT_V2 if version == "v2" else _PROMPT
    logger.debug("Planner usando prompt version=%s", version)
    return template.format(
        phone=state.get("phone", ""),
        phone_hash=state.get("phone_hash", ""),
        goal=state.get("goal", "desconhecido"),
        status=state.get("status", "coletando"),
        tipo_remarcacao=state.get("tipo_remarcacao"),
        last_action=state.get("last_action"),
        nome=cd.get("nome"),
        status_paciente=cd.get("status_paciente"),
        objetivo=cd.get("objetivo"),
        plano=cd.get("plano"),
        modalidade=cd.get("modalidade"),
        preferencia_horario=cd.get("preferencia_horario"),
        forma_pagamento=cd.get("forma_pagamento"),
        data_nascimento=cd.get("data_nascimento"),
        email=cd.get("email"),
        instagram=cd.get("instagram"),
        profissao=cd.get("profissao"),
        cep_endereco=cd.get("cep_endereco"),
        indicacao_origem=cd.get("indicacao_origem"),
        motivo_cancelamento=cd.get("motivo_cancelamento"),
        upsell_oferecido=flags.get("upsell_oferecido", False),
        planos_enviados=flags.get("planos_enviados", False),
        pagamento_confirmado=flags.get("pagamento_confirmado", False),
        aguardando_motivo_cancel=flags.get("aguardando_motivo_cancel", False),
        slot_escolhido=appt.get("slot_escolhido"),
        id_agenda=appt.get("id_agenda"),
        id_paciente=appt.get("id_paciente"),
        consulta_atual=appt.get("consulta_atual"),
        slots_summary=slots_summary,
        intent=turno.get("intent", "fora_de_contexto"),
        t_nome=turno.get("nome"),
        t_status=turno.get("status_paciente"),
        t_objetivo=turno.get("objetivo"),
        t_plano=turno.get("plano"),
        t_modalidade=turno.get("modalidade"),
        t_pref=turno.get("preferencia_horario"),
        t_pagamento=turno.get("forma_pagamento"),
        t_data_nascimento=turno.get("data_nascimento"),
        t_email=turno.get("email"),
        t_instagram=turno.get("instagram"),
        t_profissao=turno.get("profissao"),
        t_cep_endereco=turno.get("cep_endereco"),
        t_indicacao_origem=turno.get("indicacao_origem"),
        t_escolha=turno.get("escolha_slot"),
        t_upgrade=turno.get("aceita_upgrade"),
        t_confirmou=turno.get("confirmou_pagamento", False),
        t_tem_pergunta=turno.get("tem_pergunta", False),
        t_topico=turno.get("topico_pergunta"),
    )


def _parse_plano(data: dict, state: dict) -> dict:
    """Valida e normaliza o plano retornado pelo LLM."""
    action = data.get("action", FORA_DE_CONTEXTO)
    if action not in _VALID_ACTIONS:
        logger.warning("Planner retornou action inválida: %s", action)
        action = FORA_DE_CONTEXTO

    tool = data.get("tool")
    if tool and tool not in _VALID_TOOLS:
        logger.warning("Planner retornou tool inválida: %s", tool)
        tool = None

    if action == EXECUTE_TOOL and not tool:
        action = FORA_DE_CONTEXTO

    draft = data.get("draft_message")
    return {
        "action":           action,
        "tool":             tool,
        "params":           data.get("params") or {},
        "ask_context":      data.get("ask_context"),
        "new_status":       data.get("new_status"),
        "update_data":      data.get("update_data") or {},
        "update_appointment": data.get("update_appointment") or {},
        "update_flags":     data.get("update_flags") or {},
        "meta":             data.get("meta") or {},
        "draft_message":    str(draft).strip() if draft and str(draft).strip() else None,
    }


def _plano(action: str, **kwargs) -> dict:
    """Helper para criar plano com defaults."""
    return {
        "action": action,
        "tool": kwargs.get("tool"),
        "params": kwargs.get("params", {}),
        "ask_context": kwargs.get("ask_context"),
        "new_status": kwargs.get("new_status"),
        "update_data": kwargs.get("update_data", {}),
        "update_appointment": kwargs.get("update_appointment", {}),
        "update_flags": kwargs.get("update_flags", {}),
        "meta": kwargs.get("meta", {}),
        "draft_message": kwargs.get("draft_message"),
    }


def _fallback(turno: dict, state: dict) -> dict:
    """
    Fallback determinístico mínimo quando o LLM falha.
    Garante que o paciente sempre recebe uma resposta.
    """
    cd = state["collected_data"]
    intent = turno.get("intent", "fora_de_contexto")

    if intent in ("duvida_clinica",) and turno.get("tem_pergunta"):
        return _plano(ESCALATE)
    if intent == "recusou_remarketing":
        return _plano(REMARKETING_RECUSA, new_status="concluido")
    if not cd.get("nome"):
        return _plano(ASK_FIELD, ask_context="nome")
    if not cd.get("status_paciente"):
        return _plano(ASK_FIELD, ask_context="status_paciente")

    return _plano(FORA_DE_CONTEXTO)
