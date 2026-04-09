# Phase 2: Fluxo de Remarcação - Research

**Researched:** 2026-04-09
**Domain:** Remarcação de consultas — Dietbox API, FSM de negociação, cálculo de janela de prazo
**Confidence:** HIGH (codebase verificado diretamente), MEDIUM (Dietbox API endpoints inferidos do código existente)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Detecção: Retorno vs. Nova Consulta (REMC-03)**
- D-01: Ana verifica no Dietbox se o paciente tem consulta agendada E lançamento financeiro
- D-02: Tem consulta + lançamento financeiro → é retorno. Prazo e regras de remarcação de retorno se aplicam
- D-03: Tem consulta mas SEM lançamento financeiro → paciente ainda não pagou. Ana pergunta plano e modalidade e segue o fluxo normal de atendimento (nova consulta)
- D-04: Não tem consulta agendada → nova consulta, fluxo normal de atendimento

**Janela de Remarcação (REMC-01)**
- D-05: Prazo = sempre até a sexta-feira da semana APÓS a semana do agendamento original
- D-06: Início da janela de busca: amanhã (dia seguinte ao pedido de remarcação) — nunca o mesmo dia
- D-07: Slots oferecidos: apenas seg-sex. Sábado e domingo nunca aparecem
- D-08: A mensagem inicial comunica "prazo máximo para a remarcação" sem citar a data exata calculada internamente

**Priorização de Horários (REMC-02)**
- D-09: Sempre oferecer exatamente 3 opções
- D-10: Opção 1: slot mais próximo da preferência declarada do paciente (dia da semana + hora)
- D-11: Opções 2 e 3: próximos disponíveis na janela (qualquer horário)
- D-12: Se não houver slot compatível com a preferência: oferecer as 3 primeiras opções disponíveis na janela, sem mencionar preferência
- D-13: Slots de dias diferentes são preferidos — evitar oferecer 3 opções no mesmo dia

**Negociação Flexível (REMC-06)**
- D-14: Após paciente rejeitar os 3 slots oferecidos, Ana oferece mais 3 do pool restante
- D-15: Se paciente rejeitar a segunda rodada também → declarar "perda de retorno" (último recurso)
- D-16: Durante negociação, Ana pode sugerir horários próximos à preferência

**Fallback "Perda de Retorno" (REMC-05)**
- D-17: Só declarado após 2 rodadas de negociação sem acordo (D-14, D-15)
- D-18: Mensagem: informar que o prazo não comporta mais remarcação e que o retorno será perdido
- D-19: Após declarar perda do retorno, oferecer agendar como nova consulta (com cobrança normal)

**Dietbox: Sequência de Confirmação (REMC-04)**
- D-20: Sequência OBRIGATÓRIA: (1) atualiza Dietbox → (2) verifica sucesso → (3) envia confirmação ao paciente
- D-21: Nunca enviar confirmação antes de o Dietbox confirmar a atualização
- D-22: O agendamento original tem sua data/hora alterada para o novo slot (não cancela e recria)
- D-23: Adicionar observação no agendamento: "Remarcado do dia X para dia Y"
- D-24: Enviar confirmação similar ao agendamento novo (com data, hora, modalidade)
- D-25: Dietbox é a fonte de verdade

**Mensagens Fixas**
- D-26: Mensagens conforme `docs/regras_remarcacao.md`
- D-27: Tom: informal, acolhedor, com emojis moderados (💚, 😊, ✅, 📅)

### Claude's Discretion
- Implementação exata do cálculo da janela (sexta da semana seguinte ao agendamento)
- Estratégia de fallback quando o Dietbox não retorna o agendamento do paciente
- Formato exato da observação de remarcação no Dietbox
- Lógica de detecção de preferência de horário do paciente (parse de texto livre)

### Deferred Ideas (OUT OF SCOPE)
- Lembrete automático de remarcação após X dias sem resposta (v2)
- Sugestão proativa de horário com base no histórico do paciente (v2)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REMC-01 | Agente comunica "até 7 dias" ao paciente, mas oferece horários da semana seguinte inteira (seg-sex) | D-05/D-06: cálculo de janela a partir da semana do agendamento original; `consultar_slots_disponiveis()` já aceita `data_inicio` e `dias_a_frente` |
| REMC-02 | Horários seguem prioridade: 1) mais próximo da preferência, 2) próximo mais próximo, 3) mais distante | D-09 a D-13: nova função `_priorizar_slots()` substitui `_selecionar_slots_dias_diferentes()` atual |
| REMC-03 | Agente distingue retorno (já pagou) de nova consulta (sem restrição) | D-01 a D-04: nova função `consultar_agendamento_e_financeiro()` no dietbox_worker |
| REMC-04 | Ao confirmar remarcação, agente altera data/hora no Dietbox antes de enviar confirmação | D-20 a D-25: nova função `alterar_agendamento()` via `PATCH /agenda/{id}` |
| REMC-05 | Se nenhum horário encaixar após negociação, Ana informa que o retorno será perdido | D-17 a D-19: `rodada_negociacao` counter + etapa `perda_retorno` no FSM |
| REMC-06 | Agente pode sugerir outros horários e negociar flexivelmente | D-14 a D-16: `_slots_pool` completo mantido em estado, rodadas de 3 em 3 |
</phase_requirements>

---

## Summary

A Phase 2 implementa as regras corretas do fluxo de remarcação no `AgenteRetencao`. A implementação atual em `app/agents/retencao.py` tem três falhas críticas: (1) a janela de busca é calculada a partir de hoje, não do agendamento original; (2) não há detecção de retorno vs. nova consulta via Dietbox; (3) não existe a sequência de confirmação que escreve no Dietbox antes de confirmar ao paciente.

O `dietbox_worker.py` já possui `consultar_slots_disponiveis()`, `agendar_consulta()` e `lancar_financeiro()`, mas falta `alterar_agendamento()` (para update da data/hora + observação) e `consultar_agendamento_ativo()` com `verificar_lancamento_financeiro()` (para a detecção retorno vs. nova consulta).

A integração com o Redis state da Phase 1 está parcialmente pronta — `AgenteRetencao.to_dict()`/`from_dict()` já existem no código atual, mas precisam ser expandidos para incluir os novos campos de estado (`rodada_negociacao`, `_slots_pool`, `tipo_remarcacao`, `id_agenda_original`).

**Recomendação principal:** Implementar 3 planos sequenciais: (02-01) detecção e lógica de prazo em `retencao.py`; (02-02) priorização de slots e negociação em 2 rodadas; (02-03) sequência Dietbox write → verificação → confirmação, incluindo a nova função `alterar_agendamento()` no `dietbox_worker.py`.

---

## Standard Stack

### Core (já presente no projeto)
| Biblioteca | Versão | Propósito | Observação |
|-----------|--------|-----------|------------|
| requests | transitive | Chamadas HTTP síncronas ao Dietbox REST API | Padrão existente em `dietbox_worker.py` |
| anthropic | >= 0.50.0 | LLM fallback para resposta livre | Já usado em `_gerar_resposta_llm_retencao()` |
| redis (asyncio) | 5.0.8 | Persistência de estado do agente | Introduzido na Phase 1 via `RedisStateManager` |
| datetime (stdlib) | — | Cálculo da janela de remarcação | Já importado; precisa de lógica nova para "sexta da semana seguinte" |

**Sem novas dependências.** Esta fase trabalha sobre o stack existente.

---

## Architecture Patterns

### Estrutura de arquivos modificados
```
app/
├── agents/
│   ├── retencao.py          # FSM expandido (etapas, campos, lógica de prazo)
│   └── dietbox_worker.py    # +alterar_agendamento(), +consultar_agendamento_ativo(), +verificar_lancamento_financeiro()
└── router.py                # Pequenos ajustes para passar id_agenda ao AgenteRetencao
tests/
└── test_retencao.py         # Testes novos para os fluxos corrigidos
```

### Pattern 1: FSM expandido com counter de negociação

**O que é:** O FSM atual do `AgenteRetencao` tem etapas `inicio → coletando_preferencia → oferecendo_slots → concluido`. Para suportar 2 rodadas de negociação e distinção retorno/nova consulta, o FSM precisa de novas etapas e novos campos de estado.

**Etapas novas necessárias:**
```
identificando        — busca agendamento + lançamento financeiro no Dietbox
coletando_preferencia
oferecendo_slots_r1  — primeira rodada (3 slots)
oferecendo_slots_r2  — segunda rodada (próximos 3 do pool)
perda_retorno        — declaração de perda após 2 rodadas
confirmando          — aguardando Dietbox confirmar antes de enviar confirmação
concluido
```

**Novos campos de estado em `AgenteRetencao`:**
```python
# Novos campos (além dos existentes)
self.tipo_remarcacao: str | None = None        # "retorno" | "nova_consulta"
self.id_agenda_original: str | None = None     # UUID do agendamento no Dietbox
self.id_paciente_dietbox: int | None = None    # ID numérico do paciente
self.rodada_negociacao: int = 0                # 0 antes da primeira oferta, 1 após, 2 = perda
self._slots_pool: list[dict] = []              # pool completo de slots para as 2 rodadas
self._slots_oferecidos_r1: list[dict] = []     # 3 slots da rodada 1
self._slots_oferecidos_r2: list[dict] = []     # 3 slots da rodada 2
```

**Impacto no `to_dict()`/`from_dict()`:** Todos os novos campos precisam ser serializados para persistir corretamente no Redis entre mensagens. [VERIFIED: codebase — `to_dict()` já implementado em `retencao.py` linha 143-155, mas não inclui os novos campos]

### Pattern 2: Cálculo correto da janela de remarcação

**Decisão D-05:** Prazo = sexta-feira da semana APÓS a semana do agendamento original.

**Lógica correta (calculado a partir da `consulta_atual["datetime"]`):**

```python
# Source: lógica derivada da decisão D-05 no CONTEXT.md
from datetime import date, timedelta

def calcular_prazo_remarcacao(data_consulta_original: date) -> date:
    """
    Retorna a sexta-feira da semana seguinte à semana do agendamento original.
    Ex: consulta em seg 13/04 (semana 13-19/04) → prazo = sexta 25/04 (semana 20-26/04)
    Ex: consulta em sex 17/04 (semana 13-19/04) → prazo = sexta 25/04 (mesma semana seguinte)
    """
    # Acha a segunda-feira da semana do agendamento
    seg_da_semana = data_consulta_original - timedelta(days=data_consulta_original.weekday())
    # Semana seguinte começa na segunda seguinte
    seg_prox_semana = seg_da_semana + timedelta(weeks=1)
    # Sexta-feira da semana seguinte = segunda + 4 dias
    sexta_prox_semana = seg_prox_semana + timedelta(days=4)
    return sexta_prox_semana
```

**Janela de busca de slots:**
- `data_inicio` = amanhã (D-06)
- `data_fim` = `calcular_prazo_remarcacao(data_consulta_original)` — a sexta calculada acima
- `dias_a_frente` deve ser calculado como `(data_fim - date.today()).days`

**ATENÇÃO:** O código atual em `retencao.py` usa `dias_a_frente=7` a partir de hoje — isso está errado conforme D-05. A janela correta pode ser maior ou menor dependendo de quando o paciente pede a remarcação.

**Bug identificado no código atual:**
```python
# ERRADO (linha 255 de retencao.py atual):
todos_slots = consultar_slots_disponiveis(
    modalidade=self.modalidade,
    dias_a_frente=7,   # ← conta 7 dias a partir de HOJE, não da semana do agendamento
    data_inicio=data_inicio_busca,
)

# CORRETO:
prazo = calcular_prazo_remarcacao(data_consulta_original)
dias = (prazo - date.today()).days
todos_slots = consultar_slots_disponiveis(
    modalidade=self.modalidade,
    dias_a_frente=dias,
    data_inicio=date.today() + timedelta(days=1),  # D-06: nunca hoje
)
```

[VERIFIED: codebase — `consultar_slots_disponiveis()` linha 202-266 do `dietbox_worker.py` já aceita `data_inicio: date | None` e usa `hoje + timedelta(days=dias_a_frente)` como fim — compatível com a correção]

### Pattern 3: Priorização de slots (REMC-02)

**Algoritmo correto para oferecer exatamente 3 slots:**

```python
def _priorizar_slots(
    pool: list[dict],
    dia_preferido: int | None,     # 0=seg..4=sex
    hora_preferida: int | None,    # hora como int
) -> list[dict]:
    """
    Retorna exatamente 3 slots seguindo a prioridade:
    1. Slot mais próximo da preferência (dia + hora ou só dia ou só hora)
    2. Próximos disponíveis no pool (qualquer horário)
    3. Se pool < 3: repete da lista disponível sem repetir dias se possível
    """
    if not pool:
        return []

    # Ordena pool por proximidade à preferência
    def score(slot: dict) -> tuple:
        dt = datetime.fromisoformat(slot["datetime"])
        dia_match = 0 if (dia_preferido is not None and dt.weekday() == dia_preferido) else 1
        hora_match = 0 if (hora_preferida is not None and dt.hour == hora_preferida) else 1
        return (dia_match, hora_match, slot["datetime"])

    ordenados = sorted(pool, key=score)

    # Opção 1: slot de maior correspondência
    # Opções 2 e 3: próximos disponíveis, priorizando dias diferentes (D-13)
    selecionados: list[dict] = []
    dias_usados: set[str] = set()

    for slot in ordenados:
        dia = slot.get("data_fmt", "")
        if len(selecionados) == 0:
            selecionados.append(slot)
            dias_usados.add(dia)
        elif dia not in dias_usados:
            selecionados.append(slot)
            dias_usados.add(dia)
        if len(selecionados) >= 3:
            break

    # Se não chegamos a 3 com dias diferentes, completa com slots do mesmo dia
    if len(selecionados) < 3:
        for slot in ordenados:
            if slot not in selecionados:
                selecionados.append(slot)
            if len(selecionados) >= 3:
                break

    return selecionados[:3]
```

**Nota:** A função atual `_selecionar_slots_dias_diferentes()` (linhas 399-410) é similar mas não tem o conceito de "opção 1 = preferência, opções 2 e 3 = qualquer". Ela será substituída.

### Pattern 4: Detecção retorno vs. nova consulta

**Precisa de duas novas funções em `dietbox_worker.py`:**

**Função 1 — consultar agendamento ativo do paciente:**
```python
def consultar_agendamento_ativo(id_paciente: int) -> dict | None:
    """
    Retorna o próximo agendamento futuro do paciente no Dietbox.
    Retorna dict com {id, inicio, fim, ...} ou None se não houver.
    """
    hoje = datetime.now(BRT)
    fim_busca = hoje + timedelta(days=90)  # janela de 90 dias
    resp = requests.get(
        f"{DIETBOX_API}/agenda",
        headers=_headers(),
        params={
            "Start": hoje.isoformat(),
            "End": fim_busca.isoformat(),
            "IdPaciente": id_paciente,
        },
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("Data", [])
    # filtra apenas consultas não desmarcadas do paciente
    consultas = [
        i for i in items
        if not i.get("desmarcada") and str(i.get("idPaciente", "")) == str(id_paciente)
    ]
    if not consultas:
        return None
    # retorna o mais próximo
    return min(consultas, key=lambda x: x.get("inicio", ""))
```

**Função 2 — verificar lançamento financeiro:**
```python
def verificar_lancamento_financeiro(id_paciente: int, id_agenda: str) -> bool:
    """
    Retorna True se existe lançamento financeiro para o agendamento.
    Critério de retorno: consulta agendada + lançamento financeiro = já pagou.
    """
    resp = requests.get(
        f"{DIETBOX_API}/finance/transactions",
        headers=_headers(),
        params={"IdPatient": id_paciente, "IdAgenda": id_agenda},
        timeout=15,
    )
    if resp.status_code != 200:
        return False
    items = resp.json().get("Data", []) or []
    return len(items) > 0
```

**ATENÇÃO — incerteza sobre parâmetros de filtro do Dietbox:**
Os parâmetros exatos da API Dietbox para filtrar por `IdPaciente` na agenda e `IdAgenda` em `/finance/transactions` são inferidos por analogia com os endpoints existentes (`/agenda`, `/finance/transactions`). O código atual usa `IdPaciente` como parâmetro em nenhuma chamada GET — apenas nos POSTs. Isso é ASSUMED.

[ASSUMED: parâmetros de filtro `IdPaciente` na `/agenda` GET e `IdAgenda` em `/finance/transactions` GET — precisa verificação real contra a API]

### Pattern 5: Alterar agendamento no Dietbox (REMC-04)

**Nova função `alterar_agendamento()` em `dietbox_worker.py`:**

O código atual tem `agendar_consulta()` (POST) mas não tem update de agendamento. Pela convenção REST do Dietbox (observada em `confirmar_pagamento()` que usa `PATCH /finance/transactions/{id}`), o update de agendamento provavelmente usa:

```python
def alterar_agendamento(
    id_agenda: str,
    nova_data_inicio: datetime,
    duracao_minutos: int = 60,
    observacao: str | None = None,
) -> dict:
    """
    Altera a data/hora de um agendamento existente no Dietbox.
    D-22: altera o agendamento original (não cancela e recria)
    D-23: adiciona observação "Remarcado do dia X para dia Y"
    Retorna {"sucesso": bool, "erro"?: str}
    """
    if nova_data_inicio.tzinfo is None:
        nova_data_inicio = nova_data_inicio.replace(tzinfo=BRT)
    nova_data_fim = nova_data_inicio + timedelta(minutes=duracao_minutos)

    payload: dict = {
        "Start": nova_data_inicio.isoformat(),
        "End": nova_data_fim.isoformat(),
    }
    if observacao:
        payload["Observation"] = observacao  # campo real: verificar na API

    # Tenta PATCH primeiro (convenção REST); fallback para PUT se necessário
    resp = requests.patch(
        f"{DIETBOX_API}/agenda/{id_agenda}",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    if resp.status_code in (200, 204):
        return {"sucesso": True}
    # Fallback: PUT com payload completo
    resp2 = requests.put(
        f"{DIETBOX_API}/agenda/{id_agenda}",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    return {"sucesso": resp2.status_code in (200, 204), "erro": resp2.text if resp2.status_code not in (200, 204) else None}
```

[ASSUMED: o endpoint `PATCH /agenda/{id}` existe no Dietbox v2 API. Verificar em produção — se não funcionar, usar `PUT /agenda/{id}` com payload completo ou cancelar+recriar como fallback]

### Pattern 6: Integração com Redis state (Phase 1)

**O que a Phase 1 já entregou:**
- `AgenteRetencao.to_dict()` e `from_dict()` implementados (linhas 143-170 do `retencao.py` atual)
- `RedisStateManager` em `app/state_manager.py` (criado pelo Plan 01-01)
- `router.py` ainda usa `_AGENT_STATE` in-memory (Plan 01-02 ainda pendente)

**Para a Phase 2, os novos campos precisam ser adicionados ao `to_dict()`:**
```python
def to_dict(self) -> dict:
    return {
        "_tipo": "retencao",
        "telefone": self.telefone,
        "nome": self.nome,
        "modalidade": self.modalidade,
        "etapa": self.etapa,
        "motivo": self.motivo,
        "consulta_atual": self.consulta_atual,
        "novo_slot": self.novo_slot,
        "historico": self.historico[-20:],
        # NOVOS campos Phase 2:
        "tipo_remarcacao": self.tipo_remarcacao,
        "id_agenda_original": self.id_agenda_original,
        "id_paciente_dietbox": self.id_paciente_dietbox,
        "rodada_negociacao": self.rodada_negociacao,
        "_slots_pool": self._slots_pool,
        "_slots_oferecidos_r1": self._slots_oferecidos_r1,
        "_slots_oferecidos_r2": self._slots_oferecidos_r2,
    }
```

[VERIFIED: codebase — `to_dict()` atual em `retencao.py` não inclui `_slots_oferecidos`, `rodada_negociacao` ou `tipo_remarcacao`. Precisam ser adicionados]

**NOTA CRÍTICA sobre dependência da Phase 1:**
O `router.py` atual ainda usa `_AGENT_STATE` in-memory (não Redis). A Phase 2 DEVE ser compatível com o estado de execução da Phase 1. Se Plan 01-02 (substituição do `_AGENT_STATE` por Redis) ainda não foi executado quando a Phase 2 começar, os novos campos de estado funcionarão em memória mas não sobreviverão a restarts. Isso é aceitável — a serialização correta via `to_dict()` garante que quando o Redis for ativado, tudo funcionará.

---

## Don't Hand-Roll

| Problema | Não construir | Usar em vez | Por quê |
|---------|--------------|-------------|---------|
| Parse de preferência de horário | Regex caseiro para "segunda às 9h" | LLM Haiku como fallback via `_gerar_resposta_llm_retencao()` + regex simples para casos claros | Combinação: regex pega 90% dos casos comuns; LLM cobre linguagem ambígua |
| Classificação de intenção durante negociação | Lógica `if "sim" in msg` manual | Continuar usando keywords + fallback LLM (padrão existente) | O `_extrair_escolha_slot()` já funciona bem; extender para rejeição |
| Cálculo de timezone para datas do Dietbox | Conversão manual UTC↔BRT | O `dietbox_worker.py` já define `BRT = timezone(timedelta(hours=-3))` e documenta "API retorna horários sem timezone (já em BRT)" | Convenção já testada no código existente |
| Storage do pool de slots entre mensagens | Redis manual / banco de dados | Campos `_slots_pool` no estado do agente serializado em Redis via `to_dict()` | Consistente com o padrão do projeto — todo estado vai no agente |

---

## Common Pitfalls

### Pitfall 1: Janela de busca calculada a partir de hoje (não do agendamento)
**O que dá errado:** Código atual usa `dias_a_frente=7` a partir de hoje. Se o paciente pede remarcação 3 dias antes da consulta e a consulta é segunda-feira, a janela termina antes de cobrir a semana inteira seguinte.
**Por que acontece:** Implementação inicial simplificou o cálculo.
**Como evitar:** Calcular `sexta_prox_semana` a partir da data do agendamento original, não de hoje. Ver função `calcular_prazo_remarcacao()` acima.
**Sinal de alerta:** Paciente pede remarcação, consulta é na próxima semana, slots retornados terminam antes da sexta da semana seguinte ao agendamento.

### Pitfall 2: Confirmar ao paciente antes do Dietbox confirmar (D-21)
**O que dá errado:** Se a chamada ao Dietbox falhar após enviar confirmação ao paciente, haverá inconsistência — paciente acredita que remarcou mas o Dietbox ainda tem o horário antigo.
**Por que acontece:** Tentação de enviar confirmação imediata para parecer responsivo.
**Como evitar:** Sequência D-20 é obrigatória: chamar `alterar_agendamento()`, verificar `sucesso == True`, ENTÃO enviar `MSG_CONFIRMACAO_REMARCACAO`. Se falhar, enviar mensagem de erro ao paciente.
**Sinal de alerta:** Qualquer `await _enviar(meta, phone, ...)` com confirmação antes do retorno `{"sucesso": True}` do Dietbox.

### Pitfall 3: `_slots_pool` não serializado → segunda rodada impossível
**O que dá errado:** Se o estado do agente não persistir o `_slots_pool` completo, quando o paciente rejeitar a primeira rodada na segunda mensagem, o agente não terá os slots restantes para oferecer.
**Por que acontece:** `to_dict()` atual não inclui `_slots_pool` nem `_slots_oferecidos`.
**Como evitar:** Incluir `_slots_pool`, `_slots_oferecidos_r1`, `_slots_oferecidos_r2` e `rodada_negociacao` no `to_dict()`/`from_dict()`.
**Sinal de alerta:** `rodada_negociacao` é 0 em toda mensagem mesmo depois da primeira oferta.

### Pitfall 4: Detecção de retorno falsa negativa — lançamento sem `idAgenda`
**O que dá errado:** Alguns lançamentos financeiros no Dietbox podem não ter `idAgenda` populado se foram lançados manualmente pela nutricionista. Filtrar por `IdAgenda` específico pode resultar em "nenhum lançamento encontrado" mesmo para paciente que pagou.
**Por que acontece:** A Thaynara pode lançar financeiro manualmente sem vínculo explícito ao agendamento.
**Como evitar:** Estratégia de fallback: se não encontrar lançamento por `IdAgenda`, buscar lançamentos recentes do paciente nos últimos 60 dias. Se existir algum, tratar como retorno.
**Sinal de alerta:** Paciente que é claramente retorno (diz "minha consulta é semana que vem") sendo tratado como nova consulta.

### Pitfall 5: `alterar_agendamento()` sem fallback para endpoint inexistente
**O que dá errado:** Se `PATCH /agenda/{id}` não existir no Dietbox, a remarcação falhará silenciosamente e o paciente não será notificado.
**Por que acontece:** O endpoint de update de agendamento não foi verificado contra a API real — é ASSUMED.
**Como evitar:** Implementar tentativa com PATCH, fallback com PUT, e se ambos falharem: retornar `{"sucesso": False, "erro": "..."}` para o agente enviar mensagem de erro ao paciente. Nunca silenciar falhas de escrita no Dietbox.
**Sinal de alerta:** `resp.status_code` não em `(200, 204)` — logar e retornar falha.

### Pitfall 6: `rodada_negociacao` não incrementado em rejeição ambígua
**O que dá errado:** Se o paciente diz "não gostei de nenhum" ou "tem outros?" sem clareza, o extrator de escolha retorna `None` e a etapa não avança, incrementando `rodada_negociacao` a cada mensagem ambígua.
**Por que acontece:** `_extrair_escolha_slot()` retorna `None` para mensagens que não correspondem a número/dia/hora.
**Como evitar:** Usar LLM para classificar se a resposta é (a) escolha de slot, (b) rejeição explícita, ou (c) pergunta/dúvida. Para (b), incrementar `rodada_negociacao`. Para (c), responder e aguardar.

---

## Code Examples

### Cálculo correto da janela de remarcação

```python
# Source: lógica derivada de D-05 no CONTEXT.md (sexta da semana seguinte ao agendamento)
from datetime import date, timedelta

def calcular_prazo_remarcacao(data_consulta: date) -> date:
    """Retorna a sexta-feira da semana seguinte à semana do agendamento original."""
    # Segunda-feira da semana do agendamento
    seg_da_semana = data_consulta - timedelta(days=data_consulta.weekday())
    # Sexta-feira da semana SEGUINTE = segunda + 7 + 4 dias
    return seg_da_semana + timedelta(days=11)

# Uso no AgenteRetencao._etapa_identificando():
data_consulta = datetime.fromisoformat(self.consulta_atual["inicio"]).date()
prazo = calcular_prazo_remarcacao(data_consulta)
amanha = date.today() + timedelta(days=1)
dias_busca = (prazo - date.today()).days  # pode ser 7-14 dependendo do momento
```

### FSM — etapa identificando (detecção retorno vs. nova consulta)

```python
# Fluxo da etapa "identificando" no _fluxo_remarcacao()
# Chamada na entrada do fluxo, ANTES de pedir preferência
def _etapa_identificando(self) -> list[str]:
    from app.agents.dietbox_worker import (
        buscar_paciente_por_telefone,
        consultar_agendamento_ativo,
        verificar_lancamento_financeiro,
    )

    pac = buscar_paciente_por_telefone(self.telefone)
    if not pac:
        self.tipo_remarcacao = "nova_consulta"
        self.etapa = "coletando_preferencia_nova"
        # Redireciona para fluxo de nova consulta
        return ["Para agendar sua consulta, pode me informar seu nome completo? 😊"]

    consulta = consultar_agendamento_ativo(int(pac["id"]))
    if not consulta:
        # D-04: sem consulta → nova consulta
        self.tipo_remarcacao = "nova_consulta"
        self.etapa = "coletando_preferencia_nova"
        return ["Não encontrei nenhuma consulta agendada para você. Vamos agendar uma nova? 😊"]

    self.consulta_atual = consulta
    self.id_agenda_original = str(consulta.get("id", ""))
    self.id_paciente_dietbox = int(pac["id"])

    tem_lancamento = verificar_lancamento_financeiro(int(pac["id"]), self.id_agenda_original)
    if tem_lancamento:
        # D-02: retorno
        self.tipo_remarcacao = "retorno"
        self.etapa = "coletando_preferencia"
        return [MSG_INICIO_REMARCACAO.format(nome=self.nome or "")]
    else:
        # D-03: sem lançamento = não pagou = nova consulta
        self.tipo_remarcacao = "nova_consulta"
        self.etapa = "coletando_preferencia_nova"
        return [
            f"Oi {self.nome or ''}! Vi que você tem uma consulta agendada, mas o pagamento ainda não foi confirmado. "
            "Para remarcar como retorno, preciso que o pagamento seja confirmado primeiro. "
            "Quer que eu te ajude a agendar uma nova consulta? 😊"
        ]
```

### Segunda rodada de slots (negociação)

```python
# No bloco "oferecendo_slots_r1" quando paciente rejeita
def _etapa_oferecendo_slots_r1(self, msg: str) -> list[str]:
    slot = _extrair_escolha_slot(msg, self._slots_oferecidos_r1)
    if slot:
        self.novo_slot = slot
        self.etapa = "confirmando"
        return self._executar_remarcacao_dietbox()

    # Rejeição — verifica se é explícita
    if _detectar_rejeicao(msg):
        # Segunda rodada: próximos 3 do pool (excluindo os já oferecidos)
        ja_oferecidos = set(s["datetime"] for s in self._slots_oferecidos_r1)
        pool_restante = [s for s in self._slots_pool if s["datetime"] not in ja_oferecidos]
        if not pool_restante:
            self.etapa = "perda_retorno"
            return self._etapa_perda_retorno()

        self._slots_oferecidos_r2 = pool_restante[:3]
        self.rodada_negociacao = 1
        self.etapa = "oferecendo_slots_r2"
        opcoes = "\n".join(
            f"{i+1}. {s['data_fmt']} às {s['hora']}"
            for i, s in enumerate(self._slots_oferecidos_r2)
        )
        return [f"Entendo! Veja mais opções disponíveis:\n\n{opcoes}\n\nAlguma dessas funciona? 😊"]

    # Ambíguo: pede confirmação
    opcoes = "\n".join(
        f"{i+1}. {s['data_fmt']} às {s['hora']}"
        for i, s in enumerate(self._slots_oferecidos_r1)
    )
    return [f"Pode escolher uma das opções abaixo 😊\n\n{opcoes}"]
```

### Sequência obrigatória Dietbox-first (D-20)

```python
def _executar_remarcacao_dietbox(self) -> list[str]:
    """D-20: Dietbox write → verificação → confirmação ao paciente."""
    from app.agents.dietbox_worker import alterar_agendamento
    from datetime import datetime

    if not self.id_agenda_original or not self.novo_slot:
        return ["Ocorreu um erro interno. Pode tentar novamente? 😊"]

    nova_data = datetime.fromisoformat(self.novo_slot["datetime"])
    data_original_str = ""
    if self.consulta_atual:
        data_original_str = self.consulta_atual.get("inicio", "")[:10]

    observacao = f"Remarcado do dia {data_original_str} para {nova_data.strftime('%d/%m/%Y')}"

    resultado = alterar_agendamento(
        id_agenda=self.id_agenda_original,
        nova_data_inicio=nova_data,
        observacao=observacao,
    )

    if not resultado.get("sucesso"):
        logger.error("Falha ao alterar agendamento no Dietbox: %s", resultado.get("erro"))
        return [
            "Tive um problema ao alterar o agendamento no sistema. "
            "Vou verificar e te retorno em breve! Desculpe o inconveniente 🙏"
        ]

    # D-21: só confirma APÓS sucesso no Dietbox
    self.etapa = "concluido"
    return [MSG_CONFIRMACAO_REMARCACAO.format(
        data=self.novo_slot["data_fmt"],
        hora=self.novo_slot["hora"],
        modalidade=self.modalidade,
    )]
```

---

## Runtime State Inventory

> Esta fase é de modificação de lógica (não renomeia nada), mas altera campos de estado que são persistidos no Redis.

| Categoria | Itens encontrados | Ação necessária |
|-----------|-------------------|-----------------|
| Stored data (Redis) | `agent_state:{phone_hash}` — estado serializado dos agentes ativos | `to_dict()`/`from_dict()` precisam incluir novos campos; estados em andamento na produção terão campos ausentes — `from_dict()` deve usar `.get()` com defaults para todos os campos novos |
| Stored data (SQLite/Postgres) | Contact.stage, Contact.collected_name — não afetados pela Phase 2 | Nenhuma |
| Live service config | Nenhum — não há configuração externa afetada | Nenhuma |
| OS-registered state | Nenhum | Nenhuma |
| Secrets/env vars | Nenhum novo — mesmos `DIETBOX_EMAIL`, `DIETBOX_SENHA` já presentes | Nenhuma |
| Build artifacts | Nenhum | Nenhuma |

**Compatibilidade retroativa obrigatória:** `AgenteRetencao.from_dict()` deve usar `.get(campo, default)` para todos os novos campos para que agentes serializados antes da Phase 2 não quebrem quando desserializados.

---

## Open Questions

1. **`PATCH /agenda/{id}` existe no Dietbox v2?**
   - O que sabemos: `confirmar_pagamento()` usa `PATCH /finance/transactions/{id}` com sucesso; `agendar_consulta()` usa `POST /agenda`
   - O que está incerto: Não há nenhum endpoint de update de agendamento no codebase — só POST e GET
   - Recomendação: Implementar `alterar_agendamento()` com PATCH como tentativa principal e PUT como fallback. Se nenhum funcionar, fallback final = cancelar (`desmarcada: true`) e recriar com novo horário. Documentar isso como Wave 0 de testes.

2. **Parâmetros de filtro do GET `/agenda` por paciente**
   - O que sabemos: GET `/agenda` aceita `Start` e `End` como query params (linha 224 do `dietbox_worker.py`)
   - O que está incerto: Aceita `IdPaciente` como parâmetro de filtro? Se não, a `consultar_agendamento_ativo()` retornará todos os agendamentos do período e precisará filtrar por `idPaciente` no cliente
   - Recomendação: Buscar com `Start`/`End` e filtrar no Python pelo campo `idPaciente` do response — isso funciona independentemente do suporte ao parâmetro de filtro.

3. **Campo de observação no agendamento (`Observation`?)**
   - O que sabemos: `cadastrar_paciente()` usa `"Observation"` para Instagram. O `agendar_consulta()` não inclui campo de observação no payload atual.
   - O que está incerto: Qual é o nome exato do campo de observação no endpoint de agenda do Dietbox?
   - Recomendação: Tentar `"Observation"` e `"Observacao"` (camelCase e PascalCase). Se não funcionar, a observação é nice-to-have — a remarcação funciona sem ela.

4. **Detecção de rejeição vs. dúvida no FSM**
   - O que sabemos: `_extrair_escolha_slot()` retorna `None` para qualquer resposta que não seja número/dia/hora
   - O que está incerto: Como distinguir "nenhum serve" (rejeição, avança rodada) de "tenho uma dúvida" (pergunta, não avança)?
   - Recomendação: Usar LLM Haiku com prompt curto: `"O paciente aceitou um dos horários oferecidos, rejeitou todos, ou está perguntando algo? Responda: aceito|rejeitou|pergunta"`. Isso resolve ambiguidade sem regex frágil.

---

## Environment Availability

| Dependência | Necessária para | Disponível | Versão | Fallback |
|-------------|----------------|------------|--------|---------|
| Dietbox API (`api.dietbox.me/v2`) | Detecção retorno, consulta slots, alterar agendamento | ✓ (em produção) | v2 | Sem fallback — core do fluxo |
| Redis | Persistência de estado entre mensagens | ✓ (docker-compose) | redis 7 | In-memory `_AGENT_STATE` se Phase 1 ainda não integrou Redis no router |
| Claude Haiku 4.5 | LLM fallback para parse de rejeição ambígua | ✓ | claude-haiku-4-5-20251001 | Fallback determinístico (keywords) |
| Playwright (headless) | Login Dietbox para token | ✓ | >= 1.40.0 | Sem fallback — necessário para autenticação |

**Dependências sem fallback:** Dietbox API é requisito core. Se a API estiver indisponível, o fluxo de remarcação não pode ser executado — enviar mensagem de erro ao paciente e escalar para humano.

---

## Validation Architecture

### Framework de testes
| Propriedade | Valor |
|-------------|-------|
| Framework | pytest 8.3.2 + pytest-asyncio 0.24.0 |
| Config file | nenhum — pytest roda da raiz do projeto |
| Comando rápido | `python -m pytest tests/test_retencao.py -q` |
| Suite completa | `python -m pytest tests/ -q` |

### Mapa de requisitos → testes

| Req ID | Comportamento | Tipo | Comando | Arquivo existe? |
|--------|---------------|------|---------|-----------------|
| REMC-01 | Janela calculada da semana do agendamento, slots só seg-sex | unit | `python -m pytest tests/test_retencao.py::test_calcular_prazo_remarcacao -x` | ❌ Wave 0 |
| REMC-02 | 3 slots priorizados: 1° preferência, 2°-3° próximos | unit | `python -m pytest tests/test_retencao.py::test_priorizar_slots -x` | ❌ Wave 0 |
| REMC-03 | Retorno detectado (tem lançamento), nova consulta (sem lançamento) | unit | `python -m pytest tests/test_retencao.py::test_deteccao_retorno_nova_consulta -x` | ❌ Wave 0 |
| REMC-04 | Sequência: Dietbox write → sucesso → confirmação ao paciente | unit | `python -m pytest tests/test_retencao.py::test_sequencia_confirmacao_dietbox_first -x` | ❌ Wave 0 |
| REMC-05 | Após 2 rodadas de rejeição → perda_retorno declarada | unit | `python -m pytest tests/test_retencao.py::test_perda_retorno_apos_2_rodadas -x` | ❌ Wave 0 |
| REMC-06 | Segunda rodada oferece slots diferentes da primeira | unit | `python -m pytest tests/test_retencao.py::test_negociacao_segunda_rodada -x` | ❌ Wave 0 |
| REMC-04 | Falha no Dietbox → mensagem de erro (não confirmação falsa) | unit | `python -m pytest tests/test_retencao.py::test_falha_dietbox_nao_confirma -x` | ❌ Wave 0 |
| REMC-01 | Slot de sábado/domingo nunca aparece nas opções | unit | `python -m pytest tests/test_retencao.py::test_sem_slots_fim_de_semana -x` | ❌ Wave 0 |

### Taxa de amostragem
- **Por commit de tarefa:** `python -m pytest tests/test_retencao.py -q`
- **Por merge de wave:** `python -m pytest tests/ -q`
- **Phase gate:** Suite completa verde antes de `/gsd-verify-work`

### Wave 0 — lacunas
- [ ] `tests/test_retencao.py` — cobre todos os 8 cenários acima
- [ ] `tests/test_dietbox_worker.py` — adicionar testes para `alterar_agendamento()`, `consultar_agendamento_ativo()`, `verificar_lancamento_financeiro()` (com mock de `requests`)

*(Arquivo `tests/test_integration.py` existente cobre fluxo de `AgenteRetencao` básico nas linhas 1-80, mas não cobre os novos cenários de 2 rodadas e sequência Dietbox-first)*

---

## Security Domain

### Categorias ASVS aplicáveis

| Categoria ASVS | Aplica | Controle padrão |
|----------------|--------|-----------------|
| V2 Authentication | não | — |
| V3 Session Management | parcial | Estado do agente no Redis sem TTL (D-12 Phase 1) — não há dados de sessão do usuário final |
| V4 Access Control | não | — |
| V5 Input Validation | sim | Validação de entrada: `msg.lower().strip()` + regex para extração de número/hora — previne processamento de mensagem vazia |
| V6 Cryptography | não | — |

### Ameaças relevantes para este domínio

| Padrão | STRIDE | Mitigação padrão |
|--------|--------|-----------------|
| Número 31 99205-9211 em logs ou mensagens | Information Disclosure | Já controlado — nenhuma mensagem ao paciente cita o número interno |
| Dados do paciente (CPF, nome) enviados ao LLM | Information Disclosure | Pseudonimização (Phase 4 — fora do escopo aqui); por ora, apenas nome e preferência de horário chegam ao LLM |
| Escrita no Dietbox sem verificação de identidade do paciente | Tampering | `alterar_agendamento()` só é chamado após verificar que `id_agenda_original` pertence ao `id_paciente_dietbox` do agente (verificação implícita no fluxo de `identificando`) |
| Confirmação enviada antes de Dietbox confirmar | Tampering | D-21 e Pattern 5 acima garantem sequência correta |

---

## Assumptions Log

| # | Afirmação | Seção | Risco se errado |
|---|-----------|-------|-----------------|
| A1 | `PATCH /agenda/{id}` existe no Dietbox v2 API e aceita `Start`/`End` no body | Pattern 5 | Remarcação falha; fallback PUT ou cancelar+recriar necessário |
| A2 | GET `/finance/transactions` aceita `IdAgenda` como parâmetro de filtro | Pattern 4 (Função 2) | `verificar_lancamento_financeiro()` retorna sempre False; todos os pacientes seriam tratados como nova consulta |
| A3 | Campo de observação no agendamento Dietbox se chama `"Observation"` (PascalCase) | Open Question 3 | Observação de remarcação não é gravada — funcional mas sem auditoria no Dietbox |
| A4 | GET `/agenda` pode ser filtrado por `IdPaciente` como query param | Pattern 4 (Função 1) | `consultar_agendamento_ativo()` precisa filtrar no cliente Python (solução alternativa já documentada — risco BAIXO) |

---

## Project Constraints (from CLAUDE.md)

- **LLM:** Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) — usar em todas as chamadas LLM da fase
- **Stack:** Python 3.12 + FastAPI — não mudar
- **Segurança:** Número 31 99205-9211 NUNCA exposto ao paciente — verificar em todas as mensagens novas
- **LGPD:** Nunca armazenar dados sensíveis fora do Dietbox; pseudonimização para LLM — estado do agente no Redis não deve incluir CPF, apenas nome e telefone
- **Nomenclatura:** Agentes: `Agente<Domain>`, workers: `_worker` suffix. Funções públicas: verbos descritivos (`consultar_agendamento_ativo`). Privadas: `_` prefix
- **Testes:** Todos os módulos novos/modificados precisam de testes em `tests/`. Rodar `python -m pytest tests/ -q` antes de cada commit
- **Logging:** Telefones nos logs: apenas últimos 4 dígitos (`phone[-4:]`)
- **UX:** Mensagens curtas e objetivas, tom informal/acolhedor, emojis com moderação (💚, 😊, ✅, 📅)
- **Estilo:** `from __future__ import annotations` em todo arquivo; dividers de seção `# ── Nome ─────`; `msg_lower = msg.lower().strip()` no início de métodos de processamento

---

## Sources

### Primárias (HIGH confidence — verificadas diretamente no codebase)
- `app/agents/retencao.py` — FSM atual, campos de estado, to_dict/from_dict existentes, bugs identificados
- `app/agents/dietbox_worker.py` — endpoints disponíveis, padrão de chamadas HTTP, HORARIOS_POR_DIA, strutura de slots
- `app/router.py` — como AgenteRetencao é instanciado e chamado
- `.planning/phases/02-fluxo-de-remarca-o/02-CONTEXT.md` — decisões D-01 a D-27
- `.planning/REQUIREMENTS.md` — REMC-01 a REMC-06
- `.planning/phases/01-intelig-ncia-conversacional/01-01-PLAN.md` — contrato de RedisStateManager e to_dict/from_dict

### Secundárias (MEDIUM confidence — inferidas do código existente)
- Padrão de endpoint Dietbox `/agenda/{id}` PATCH: inferido de `confirmar_pagamento()` que usa `PATCH /finance/transactions/{id}` — mesmo estilo REST
- Parâmetros de filtro GET `/agenda`: inferidos dos params já usados (`Start`, `End`); `IdPaciente` é ASSUMED

### Terciárias (LOW confidence — assumidas, marcadas para validação)
- Existence of `PATCH /agenda/{id}` endpoint in Dietbox v2 API
- Filter param `IdAgenda` in GET `/finance/transactions`
- Field name `"Observation"` in agenda PATCH payload

---

## Metadata

**Breakdown de confiança:**
- Stack padrão: HIGH — verificado diretamente no código existente
- Arquitetura / FSM: HIGH — baseado em código real + decisões do CONTEXT.md
- Endpoints Dietbox (GET agenda, GET finance): HIGH — usados no código
- Endpoint PATCH agenda (novo): LOW — não existe no código atual, inferido por analogia
- Pitfalls: HIGH — identificados por análise direta do código existente

**Data de pesquisa:** 2026-04-09
**Válido até:** 2026-05-09 (30 dias — stack estável, Dietbox API não muda frequentemente)
