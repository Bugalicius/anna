---
phase: 02-fluxo-de-remarca-o
verified: 2026-04-13T23:30:37Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Enviar mensagem de remarcação para a Ana via WhatsApp com um paciente que tem consulta e lançamento financeiro no Dietbox"
    expected: "Ana deve detectar que é retorno, apresentar a mensagem com '7 dias' e 'prazo máximo', listar 3 opções de horário de segunda a sexta da semana seguinte"
    why_human: "A integração Dietbox real (login Playwright + token) não pode ser verificada por grep ou testes unitários. Os testes mockam essas chamadas"
  - test: "Rejeitar os 3 slots da primeira rodada e depois rejeitar a segunda rodada"
    expected: "Ana deve declarar 'perda de retorno' após a segunda rejeição, com mensagem informando que o prazo não comporta mais remarcação e oferecendo agendar como nova consulta"
    why_human: "O fluxo end-to-end depende de mensagens WhatsApp reais — o comportamento do parser _extrair_escolha_slot com variações de linguagem natural não é 100% cobrível por testes unitários"
  - test: "Escolher um slot, verificar que o Dietbox foi atualizado ANTES de Ana enviar a confirmação"
    expected: "Ana envia 'Um instante, por favor 💚', depois altera o agendamento no Dietbox, depois envia a confirmação com data/hora/modalidade corretas. O agendamento no painel Dietbox deve mostrar a observação 'Remarcado do dia X para Y'"
    why_human: "A sequência Dietbox-first requer acesso real ao painel Dietbox para confirmar que o agendamento foi alterado com a observação correta antes da mensagem de confirmação chegar ao paciente"
---

# Phase 2: Fluxo de Remarcação — Verification Report

**Phase Goal:** Regras de remarcacao de retorno funcionam corretamente — prazo comunicado, horarios priorizados, Dietbox atualizado antes da confirmacao, fallback para "perda de retorno" implementado
**Verified:** 2026-04-13T23:30:37Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | Paciente de retorno recebe "ate 7 dias" e ve horarios de segunda a sexta da semana seguinte inteira | VERIFIED | `MSG_INICIO_REMARCACAO` contem "7 dias" e "prazo maximo". `calcular_fim_janela()` retorna sexta da semana seguinte. Busca inicia em `amanha`. 3 testes TDD passando (`test_calcular_fim_janela_*`). |
| SC-2 | Horarios apresentados na ordem: mais proximo da preferencia do paciente primeiro | VERIFIED | `_priorizar_slots(pool, dia_preferido, hora_preferida)` implementada. Slot 1 = match dia+hora; slots 2-3 = proximos em dias diferentes. 7 testes TDD passando (`test_priorizar_slots_*`). |
| SC-3 | Ana distingue remarcacao de retorno de nova consulta e aplica regras diferentes | VERIFIED | `_detectar_tipo_remarcacao()` chama `buscar_paciente_por_telefone` + `consultar_agendamento_ativo` + `verificar_lancamento_financeiro`. Sem agenda/lancamento -> "nova_consulta" + redirecionamento. Com agenda e lancamento -> "retorno" + regras de prazo. 9 testes TDD passando. |
| SC-4 | Ao confirmar remarcacao, horario alterado no Dietbox ANTES de Ana enviar confirmacao | VERIFIED | Sequencia implementada: `oferecendo_slots` -> `aguardando_confirmacao_dietbox` (retorna "Um instante, por favor") -> `alterar_agendamento()` -> sucesso = `concluido` com `MSG_CONFIRMACAO_REMARCACAO` / falha = `erro_remarcacao`. Nunca envia confirmacao sem sucesso Dietbox. 6 testes TDD passando. |
| SC-5 | Se nenhum horario encaixar apos negociacao, Ana informa que retorno sera perdido | VERIFIED | Apos 2 rodadas (ou pool esgotado), `etapa = "perda_retorno"` com `MSG_PERDA_RETORNO`. Etapa `perda_retorno` redireciona para nova consulta. 4 testes TDD passando (`test_rejeicao_*`, `test_pool_com_so_3_slots_*`). |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|---------|--------|---------|
| `app/agents/dietbox_worker.py` | `consultar_agendamento_ativo()` e `verificar_lancamento_financeiro()` | VERIFIED | Ambas implementadas. GET /agenda e GET /finance/transactions. Timeout=15, try/except, nunca propagam excecao. |
| `app/agents/dietbox_worker.py` | `alterar_agendamento()` — PATCH com nova data e observacao | VERIFIED | PATCH para `DIETBOX_API/agenda/{id_agenda}` com payload `{Start, End, Observacao}`. Timeout=20, retorna bool. |
| `app/agents/retencao.py` | FSM expandido com novos campos, `calcular_fim_janela`, `_detectar_tipo_remarcacao`, `_priorizar_slots` | VERIFIED | 5 novos campos em `__init__`, `to_dict`, `from_dict` com `.get(campo, default)`. Todas as 4 funcoes presentes e operacionais. |
| `app/agents/retencao.py` | Etapas `aguardando_confirmacao_dietbox`, `perda_retorno`, `erro_remarcacao` | VERIFIED | Todas as 3 etapas presentes em `_fluxo_remarcacao`. |
| `tests/test_dietbox_worker.py` | 11 novos testes (6 + 5) cobrindo as novas funcoes | VERIFIED | 23 testes passando total (12 existentes + 6 `consultar/verificar` + 5 `alterar_agendamento`). |
| `tests/test_retencao.py` | 28 testes cobrindo calcular_fim_janela, FSM, deteccao, slots, negociacao, Dietbox-first | VERIFIED | 28 testes passando, todos os cenarios do plano cobertos. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `retencao.py:_fluxo_remarcacao` | `dietbox_worker:consultar_agendamento_ativo` | chamada sincrona na etapa "inicio" via `_detectar_tipo_remarcacao` | WIRED | Import no topo do arquivo. Chamado em `_detectar_tipo_remarcacao()` linha 285. |
| `retencao.py` | `dietbox_worker:verificar_lancamento_financeiro` | checagem apos obter id_agenda | WIRED | Import no topo. Chamado em `_detectar_tipo_remarcacao()` linha 291. |
| `retencao.py:AgenteRetencao.from_dict` | `AgenteRetencao` novos campos | `.get(campo, default)` para todos os novos campos | WIRED | Todos os 5 novos campos usam `.get()`. Compativel com estados Phase 1. |
| `retencao.py:etapa oferecendo_slots` | `retencao.py:_priorizar_slots` | chamada com pool completo e preferencia | WIRED | `_priorizar_slots(todos_slots, dia_preferido, hora_preferida)` na etapa `coletando_preferencia`. |
| `retencao.py:etapa oferecendo_slots` | `rodada_negociacao counter` | incremento antes de oferecer proximos slots | WIRED | `self.rodada_negociacao += 1` antes de oferecer segunda rodada (linha 445). |
| `retencao.py:etapa oferecendo_slots (escolha)` | `retencao.py:aguardando_confirmacao_dietbox` | ao escolher slot, etapa muda (nao para "concluido") | WIRED | `self.etapa = "aguardando_confirmacao_dietbox"` ao extrair slot. |
| `retencao.py:aguardando_confirmacao_dietbox` | `dietbox_worker:alterar_agendamento` | chamada com id_agenda_original, novo dt e observacao | WIRED | `sucesso = alterar_agendamento(id_agenda, novo_dt, observacao)` linha 485. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `retencao.py:_fluxo_remarcacao` | `todos_slots` | `consultar_slots_disponiveis()` -> Dietbox API GET /agenda | Sim (dados reais do Dietbox, mocado em testes) | FLOWING |
| `retencao.py:_detectar_tipo_remarcacao` | `agenda` | `consultar_agendamento_ativo()` -> Dietbox API GET /agenda | Sim (dados reais do Dietbox, mocado em testes) | FLOWING |
| `retencao.py:aguardando_confirmacao_dietbox` | `sucesso` | `alterar_agendamento()` -> Dietbox API PATCH /agenda/{id} | Sim (PATCH real, mocado em testes) | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `calcular_fim_janela` retorna sexta correta | `pytest tests/test_retencao.py -k "calcular_fim_janela" -v` | 3 passed | PASS |
| `_priorizar_slots` respeita preferencia | `pytest tests/test_retencao.py -k "priorizar" -v` | 7 passed | PASS |
| Negociacao 2 rodadas funciona | `pytest tests/test_retencao.py -k "rodada or rejeicao or perda" -v` | 4 passed | PASS |
| Dietbox-first sequencia | `pytest tests/test_retencao.py -k "aguardando or confirmacao" -v` | 5 passed | PASS |
| `alterar_agendamento` retorna bool | `pytest tests/test_dietbox_worker.py -k "alterar_agendamento" -v` | 5 passed | PASS |
| Suite completa sem regressoes | `pytest tests/ -q` | 154 passed, 0 failed | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|------------|------------|-------------|--------|---------|
| REMC-01 | 02-01 | Comunica "ate 7 dias", oferece horarios seg-sex da semana seguinte | SATISFIED | `MSG_INICIO_REMARCACAO` contem "7 dias" + "prazo maximo". `calcular_fim_janela` usa semana seguinte ao agendamento original. `data_inicio_busca = hoje + 1 dia`. |
| REMC-02 | 02-02 | Horarios priorizados: mais proximo da preferencia primeiro | SATISFIED | `_priorizar_slots()` implementada com algoritmo: slot 1 = match dia+hora, slots 2-3 = proximos em dias diferentes. |
| REMC-03 | 02-01 | Distingue retorno (7 dias) de nova consulta (sem restricao) | SATISFIED | `_detectar_tipo_remarcacao()` verifica agendamento ativo + lancamento financeiro. Redireciona nova consulta para `redirecionando_atendimento`. |
| REMC-04 | 02-03 | Altera data/hora no Dietbox ao confirmar remarcacao | SATISFIED | `alterar_agendamento()` chamada na etapa `aguardando_confirmacao_dietbox` ANTES de enviar `MSG_CONFIRMACAO_REMARCACAO`. |
| REMC-05 | 02-02 | Informa perda de retorno apos negociacao | SATISFIED | `MSG_PERDA_RETORNO` enviada apos 2 rodadas ou pool esgotado. Etapa `perda_retorno` redireciona para nova consulta. |
| REMC-06 | 02-02 | Negocia flexivelmente — sugestao de outros horarios | SATISFIED | Segunda rodada com `MSG_SEGUNDA_RODADA` + novos 3 slots do pool restante. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|---------|--------|
| `app/agents/retencao.py` | 464 | `from datetime import datetime as _dt` dentro de bloco condicional | Info | Importacao repetida a cada ativacao da etapa. Sem impacto funcional — Python cacheia o modulo. |

Nenhum stub, placeholder, return vazio ou TODO encontrado nos arquivos modificados pela Fase 2.

### Human Verification Required

#### 1. Fluxo completo de remarcacao de retorno (end-to-end)

**Test:** Enviar mensagem de remarcacao para a Ana via WhatsApp com um numero que tem consulta cadastrada E lancamento financeiro no Dietbox. Verificar que Ana detecta corretamente como "retorno", apresenta a mensagem com "prazo maximo" e lista 3 opcoes de horario de segunda a sexta da semana seguinte ao agendamento original.

**Expected:** Ana responde com `MSG_INICIO_REMARCACAO` (contem "7 dias", "prazo maximo"), e ao receber preferencia de horario lista 3 opcoes numeradas de dias uteis dentro da janela correta.

**Why human:** A integracao real com Dietbox requer login via Playwright (Azure AD B2C) e acesso ao token real. Os testes mockam essas chamadas — o comportamento de fallback quando o Dietbox nao retorna o paciente (novo paciente, timeout) precisa de validacao em ambiente real.

#### 2. Negociacao 2 rodadas + perda de retorno (end-to-end)

**Test:** Rejeitar os 3 slots da primeira rodada enviando "nenhum funciona" ou similar. Verificar que Ana oferece mais 3 opcoes (segunda rodada). Rejeitar novamente. Verificar que Ana declara perda de retorno com a mensagem correta e oferece agendar como nova consulta.

**Expected:** Primeira rejeicao = `MSG_SEGUNDA_RODADA` com 3 novos slots. Segunda rejeicao = `MSG_PERDA_RETORNO` seguida de redirecionamento para o fluxo de nova consulta.

**Why human:** O parser `_extrair_escolha_slot` distingue escolha (numero, "primeiro", hora) de rejeicao pelo que esta ausente na mensagem. Com linguagem natural real os pacientes podem usar expressoes nao cobertas pelos testes unitarios ("nao gosto de nenhum", "tem outra opcao?", etc.).

#### 3. Sequencia Dietbox-first — confirmacao verificada no painel

**Test:** Escolher um slot de remarcacao. Verificar que: (a) Ana envia "Um instante, por favor" primeiro; (b) o agendamento no painel Dietbox e alterado para a nova data/hora; (c) a observacao "Remarcado do dia X para Y" aparece no campo Observacao do agendamento; (d) apenas depois Ana envia `MSG_CONFIRMACAO_REMARCACAO` com os dados corretos.

**Expected:** Sequencia exata: instante -> Dietbox atualizado -> confirmacao ao paciente. O painel Dietbox deve mostrar a nova data e a observacao de remarcacao.

**Why human:** Requer acesso real ao painel Dietbox para confirmar que o PATCH foi aplicado com os dados corretos. Os testes unitarios mockam `alterar_agendamento` — a integracao real pode ter diferencas de schema de API (campo `Observacao` vs `observacao`, etc.).

### Gaps Summary

Nenhum gap identificado. Todos os 5 criterios de sucesso do ROADMAP estao verificados no codigo. Os 154 testes passam sem regressoes. As 3 verificacoes humanas necessarias sao de comportamento end-to-end que dependem de integracao real com Dietbox + WhatsApp — nao representam falhas no codigo, mas confirmacoes de integracao que nao podem ser verificadas programaticamente.

---

_Verified: 2026-04-13T23:30:37Z_
_Verifier: Claude (gsd-verifier)_
