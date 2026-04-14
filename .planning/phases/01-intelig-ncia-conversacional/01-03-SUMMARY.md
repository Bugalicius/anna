---
phase: 01-intelig-ncia-conversacional
plan: "03"
subsystem: escalation-relay-behavior
tags: [escalation, relay, faq-aprendido, waiting-indicator, seguranca, dietbox]
dependency_graph:
  requires:
    - app/models.py: PendingEscalation (Plan 01-01)
    - app/state_manager.py: RedisStateManager (Plan 01-01)
    - app/router.py: route_message com Redis (Plan 01-02)
    - app/agents/orchestrator.py: rotear() (Plan 01-02)
  provides:
    - app/escalation.py: 3 caminhos escalacao + relay bidirecional + lembretes
    - app/meta_api.py: send_contact() para VCard Thaynara
    - app/knowledge_base.py: salvar_faq_aprendido() + faq_combinado() inclui aprendido
    - app/agents/atendimento.py: waiting indicator D-21 + filtro mesmo dia D-19
    - app/webhook.py: deteccao de mensagem do Breno + processar_resposta_breno()
    - app/remarketing.py: job escalation_reminders no APScheduler
  affects:
    - router.py: escalar_para_humano() mantida para compatibilidade
    - faq_combinado(): retorna mais itens (FAQ aprendido incluso)
tech_stack:
  added: []
  patterns:
    - random.choice(_WAITING_MESSAGES) para variar indicadores de espera
    - Patch via app.database.SessionLocal para isolar testes de funcoes com import lazy
    - asyncio.new_event_loop() no job APScheduler sincrono para chamar funcao async
    - _FAQ_APRENDIDO_FILE como constante de modulo para facilitar patch em testes
key_files:
  created:
    - tests/test_escalation.py
    - tests/test_behavior.py
  modified:
    - app/escalation.py
    - app/webhook.py
    - app/meta_api.py
    - app/knowledge_base.py
    - app/agents/atendimento.py
    - app/remarketing.py
decisions:
  - "salvar_faq_aprendido() como funcao de modulo (nao metodo da classe) para facilitar import lazy em escalation.py"
  - "Patch via app.database.SessionLocal (nao app.escalation.SessionLocal) porque import e lazy dentro do corpo da funcao"
  - "waiting indicator como primeiro item da lista retornada (nao enviado separadamente) — router.py ja envia sequencialmente"
  - "filtro de mesmo dia usando date.today().strftime('%d/%m/%Y') para comparar com data_fmt do slot"
  - "asyncio.new_event_loop() no job _check_escalation_reminders porque APScheduler e sincrono"
metrics:
  duration: "~45 minutos"
  completed_date: "2026-04-14"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 6
---

# Phase 01 Plan 03: Escalação 3 Caminhos + Relay + Waiting Indicator Summary

**One-liner:** Escalação com 3 caminhos (D-05/D-06/D-07), relay bidirecional Breno→paciente com lembretes (D-09/D-10), FAQ aprendido persistente (D-11), waiting indicator antes de Dietbox/Rede (D-21) e filtro de slots no mesmo dia (D-19).

## What Was Built

### app/escalation.py (refatorado)

Nova função principal `escalar_duvida()` com 3 caminhos:
- **D-05**: `duvida_clinica` + `is_paciente_cadastrado=True` → envia mensagem + VCard Thaynara via `send_contact()`
- **D-06**: `duvida_clinica` + lead → cria `PendingEscalation`, envia contexto ao Breno, paciente recebe aguardo
- **D-07**: qualquer outro motivo → mesmo fluxo do D-06

Nova função `criar_escalacao_relay()`: persiste `PendingEscalation` no banco, envia contexto ao `_NUMERO_INTERNO`.

Nova função `processar_resposta_breno()`: encontra escalação pendente mais recente, marca como "respondido", repassa resposta ao paciente, salva como FAQ aprendido.

Nova função `enviar_lembretes_pendentes()`: schedule D-09 (15min x4, depois 1h), D-10 (aviso ao paciente no 4º lembrete).

Helper `_formatar_tempo()`: formata timedelta como "15 min", "1h30", "2h".

`escalar_para_humano()` mantida por compatibilidade com `router.py`.

`_NUMERO_INTERNO` lido de `os.environ.get("NUMERO_INTERNO", "5531992059211")` — nunca hard-coded em mensagens ao paciente.

### app/meta_api.py (adicionado send_contact)

Novo método `send_contact(to, nome, telefone)`: envia VCard via WhatsApp Business API com type "contacts". Separa nome em first_name/last_name automaticamente.

### app/webhook.py (detecção do Breno)

`process_message()` verifica `phone == _NUMERO_INTERNO` ANTES de chamar `route_message()`. Se for o Breno, chama `processar_resposta_breno()` e retorna sem rotear como paciente normal.

### app/knowledge_base.py (FAQ aprendido)

Adicionados:
- `_FAQ_APRENDIDO_FILE = _KB_DIR / "faq_aprendido.json"` — constante de módulo
- `salvar_faq_aprendido(pergunta, resposta)` — persiste JSON, evita duplicatas, atualiza resposta existente
- `faq_combinado()` atualizado: inclui FAQ aprendido como terceira fonte após FAQ estático e FAQ minerado

### app/agents/atendimento.py (waiting indicator + filtro mesmo dia)

Adicionados:
- `_WAITING_MESSAGES` — lista de 3 variações de waiting indicator
- `import random` e `import date` no topo do módulo
- `_iniciar_agendamento()`: prepende `random.choice(_WAITING_MESSAGES)` + filtra `hoje_fmt` dos slots (D-19) — retorna lista de 2+ mensagens
- `_etapa_forma_pagamento()`: prepende waiting indicator antes de `gerar_link_pagamento()` para fluxo cartão
- `_etapa_cadastro_dietbox()`: prepende waiting indicator antes de `processar_agendamento()`

### app/remarketing.py (job APScheduler)

Adicionada função `_check_escalation_reminders()` com `asyncio.new_event_loop()` para executar `enviar_lembretes_pendentes()` de contexto síncrono do APScheduler.

`create_scheduler()` registra o job com `interval minutes=5, id="escalation_reminders"`.

### tests/test_escalation.py (12 testes)

Cobre todos os 8 behaviors do plan:
- 3 caminhos de escalação (D-05, D-06, D-07)
- Relay bidirecional: Breno responde → paciente recebe
- Schedule de lembretes (15min < 4 reminders, 1h >= 4)
- Timeout 1h: aviso ao paciente no 4º lembrete
- Número interno NUNCA exposto ao paciente
- FAQ aprendido salvo com pergunta/resposta corretos
- Sem escalação pendente: retorna False sem crash

### tests/test_behavior.py (9 testes)

Cobre comportamentos D-18, D-19, D-21:
- Waiting indicator como primeiro item em _iniciar_agendamento()
- Waiting indicator em _etapa_forma_pagamento() (cartão)
- Waiting indicator em _etapa_cadastro_dietbox()
- MSG_BOAS_VINDAS tem tom informal e emoji
- Slots do dia atual filtrados (D-19)
- Formulário nunca oferecido proativamente em MSG_*
- salvar_faq_aprendido() persiste em JSON
- Atualização de duplicata em vez de duplicar
- faq_combinado() não quebra sem arquivo

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] patch via app.escalation.SessionLocal não funciona — import lazy**
- **Found during:** Task 1 ao executar testes TDD
- **Issue:** `from app.database import SessionLocal` feito dentro do corpo da função (lazy import). `patch("app.escalation.SessionLocal")` falha com AttributeError pois o módulo não tem esse atributo
- **Fix:** Usar `patch("app.database.SessionLocal")` — intercepta no ponto correto
- **Files modified:** tests/test_escalation.py
- **Commit:** 88e2767

**2. [Rule 2 - Missing] filtro de slots do mesmo dia não estava implementado (D-19)**
- **Found during:** Task 2 ao implementar test_agendamento_nunca_mesmo_dia
- **Issue:** `_iniciar_agendamento()` original não filtrava slots do dia atual
- **Fix:** Adicionado `hoje_fmt = date.today().strftime("%d/%m/%Y")` e `if dia == hoje_fmt: continue`
- **Files modified:** app/agents/atendimento.py
- **Commit:** da9bc54

## Tests

```
tests/test_escalation.py  — 12 testes, todos passando
tests/test_behavior.py    — 9 testes, todos passando
Suite completa: 186 passed, 1 warning (FutureWarning google-generativeai — pre-existente)
```

## Security / LGPD Compliance

- `_NUMERO_INTERNO` lido de env var `NUMERO_INTERNO` — nunca hard-coded em mensagens ao paciente (INTL-04, T-01-08)
- Teste explícito verifica que nenhum fragmento do número aparece em mensagens ao paciente
- FAQ aprendido escrito em arquivo local pela aplicação — sem acesso externo (T-01-10)
- Lembretes com `next_reminder_at` previnem envios duplicados (T-01-11)

## Known Stubs

Nenhum stub identificado. Toda a lógica está wired a implementações reais:
- `salvar_faq_aprendido()` escreve em `knowledge_base/faq_aprendido.json`
- `enviar_lembretes_pendentes()` registrado no APScheduler via `_check_escalation_reminders()`
- `send_contact()` usa `_post()` do MetaAPIClient real

## Threat Surface Scan

Nenhuma nova superfície de rede criada. `send_contact()` usa o mesmo endpoint e auth do `send_text()`. Webhook detecta `_NUMERO_INTERNO` e desvia antes de `route_message()` — sem novo endpoint exposto.

## Self-Check: PASSED

- app/escalation.py: FOUND (escalar_duvida, criar_escalacao_relay, processar_resposta_breno, enviar_lembretes_pendentes)
- app/meta_api.py: FOUND (send_contact presente)
- app/knowledge_base.py: FOUND (salvar_faq_aprendido, _FAQ_APRENDIDO_FILE, faq_combinado atualizado)
- app/agents/atendimento.py: FOUND (_WAITING_MESSAGES, filtro hoje_fmt)
- app/webhook.py: FOUND (detecção _NUMERO_INTERNO)
- app/remarketing.py: FOUND (_check_escalation_reminders, job escalation_reminders)
- tests/test_escalation.py: FOUND (12 testes)
- tests/test_behavior.py: FOUND (9 testes)
- Commit 88e2767 (Task 1): FOUND
- Commit da9bc54 (Task 2): FOUND
- 186 tests passed: VERIFIED
- grep "99205|9211" app/escalation.py: apenas em _NUMERO_INTERNO: VERIFIED
