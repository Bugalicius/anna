# Roadmap: Agente Ana

## Overview

Ana funciona estruturalmente — 5 agentes, 104 testes, interface de teste rodando — mas falha onde mais importa: interpretar o que o paciente quer e agir corretamente. Este milestone corrige a inteligência da Ana de dentro para fora, na ordem que os bugs exigem: contexto conversacional e persistência de estado primeiro (tudo depende disso), depois as regras de remarcação (que usam o FSM corrigido), depois o remarketing (que depende de estado confiável), e por fim o endurecimento da integração Meta Cloud API.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Inteligência Conversacional** - FSM context-aware, Redis state persistence, escalation relay, waiting indicator
- [ ] **Phase 2: Fluxo de Remarcação** - Regras corretas de retorno vs. nova consulta, priorização de horários, Dietbox write antes da confirmação
- [ ] **Phase 3: Remarketing** - Drip sequence 24h/7d/30d funcional, APScheduler async fix, controle de tentativas
- [ ] **Phase 4: Meta Cloud API** - Webhook HMAC, deduplicação, envio de mídia, LGPD pseudonimização

## Phase Details

### Phase 1: Inteligência Conversacional
**Goal**: Ana interpreta corretamente o que o paciente diz, adapta o fluxo sem resetar, persiste estado entre reinicios, e escala para humano quando não sabe responder
**Depends on**: Nothing (first phase)
**Requirements**: INTL-01, INTL-02, INTL-03, INTL-04, INTL-05
**Success Criteria** (what must be TRUE):
  1. Paciente pode mudar de assunto no meio de um fluxo e Ana retoma o contexto correto sem recomeçar do zero
  2. Ana envia "Um instante, por favor 💚" antes de qualquer operação que consulta Dietbox ou gera link, antes de responder
  3. Quando Ana não sabe responder, encaminha a dúvida internamente, aguarda resposta e repassa ao paciente — sem revelar o número 31 99205-9211
  4. Após reinicio do processo, paciente que estava no meio de um fluxo continua de onde parou (estado persistido no Redis)
  5. Tom e sequência de mensagens seguem a documentação oficial — sem improvisar saudações, etapas ou valores
**Plans**: TBD

Plans:
- [ ] 01-01: Context-aware FSM — structured LLM output com `{nova_etapa, slots_atualizados, resposta}` e interrupt detection
- [ ] 01-02: Redis state serialization — `to_dict()/from_dict()` nos agentes, substituição do `_AGENT_STATE` in-memory
- [ ] 01-03: Escalation relay + waiting indicator + confidence threshold + behavior alignment

### Phase 2: Fluxo de Remarcação
**Goal**: Regras de remarcação de retorno funcionam corretamente — prazo comunicado, horários priorizados, Dietbox atualizado antes da confirmação, fallback para "perda de retorno" implementado
**Depends on**: Phase 1
**Requirements**: REMC-01, REMC-02, REMC-03, REMC-04, REMC-05, REMC-06
**Success Criteria** (what must be TRUE):
  1. Paciente de retorno recebe a informação "até 7 dias" e vê horários de segunda a sexta da semana seguinte inteira para escolher
  2. Horários são apresentados na ordem: mais próximo da preferência do paciente primeiro, depois os demais
  3. Ana distingue remarcação de retorno (restrição de 7 dias) de nova consulta (sem restrição) e aplica regras diferentes para cada caso
  4. Ao confirmar remarcação, o horário é alterado no Dietbox antes de Ana enviar a mensagem de confirmação ao paciente
  5. Se nenhum horário encaixar após negociação, Ana informa que o retorno será perdido — como último recurso, após tentar alternativas
**Plans**: TBD

Plans:
- [ ] 02-01: Regras de prazo e detecção retorno vs. nova consulta — lógica em `retencao.py`
- [ ] 02-02: Priorização de horários e negociação flexível — algoritmo de ordenação e fluxo de fallback
- [ ] 02-03: Sequência correta: Dietbox write → verificação de sucesso → confirmação ao paciente

### Phase 3: Remarketing
**Goal**: Sistema de follow-up automático funciona de ponta a ponta — scheduler dispara nas janelas certas, templates corretos são enviados, controle de tentativas e lead perdido funcionam
**Depends on**: Phase 1
**Requirements**: RMKT-01, RMKT-02, RMKT-03, RMKT-04, RMKT-05, RMKT-06
**Success Criteria** (what must be TRUE):
  1. Lead sem resposta recebe follow-up automático em 24h, 7 dias e 30 dias — mensagens chegam de fato no WhatsApp
  2. Sistema para de enviar após 3 tentativas sem resposta — não envia quarta mensagem
  3. Quando lead responde que não vai marcar, sistema move para "lead perdido" e nenhuma mensagem adicional é enviada
  4. Mensagens de follow-up seguem os templates da documentação (seção 6) — sem texto improvisado
  5. Remarketing não interrompe paciente com conversa ativa — verifica estado FSM antes de disparar
**Plans**: TBD

Plans:
- [ ] 03-01: APScheduler fix — migrar de `BackgroundScheduler` para `AsyncIOScheduler`, corrigir coroutine não-awaited
- [ ] 03-02: Drip triggers e controle de estado — counters, lead perdido, verificação de conversa ativa
- [ ] 03-03: Templates e validação end-to-end — submissão/aprovação Meta + teste de entrega real

### Phase 4: Meta Cloud API
**Goal**: Integração Meta Cloud API é segura, idempotente e compliant com LGPD — webhook validado por HMAC, deduplicação previne agendamentos duplicados, mídia real enviada, dados de pacientes pseudonimizados antes de chegar ao LLM
**Depends on**: Phase 3
**Requirements**: META-01, META-02, META-03, META-04
**Success Criteria** (what must be TRUE):
  1. Webhook rejeita requisições sem assinatura HMAC válida — webhook não processa mensagens forjadas
  2. Mesma mensagem entregue duas vezes pelo Meta não cria dois agendamentos — deduplicação por `message_id` funciona
  3. PDFs e imagens de preparo são enviados ao paciente como arquivos reais (não placeholders de texto)
  4. Dados sensíveis do paciente (CPF, telefone) não aparecem em chamadas à API da Anthropic — pseudonimização aplicada antes do prompt
**Plans**: TBD

Plans:
- [ ] 04-01: Webhook HMAC enforcement e deduplicação Redis (`message_id`, 4h TTL)
- [ ] 04-02: Envio de texto, PDF e imagem via Meta Cloud API (substituindo Evolution API)
- [ ] 04-03: LGPD audit — pseudonimização de dados sensíveis antes de LLM calls, proteção contra prompt injection

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Inteligência Conversacional | 0/3 | Not started | - |
| 2. Fluxo de Remarcação | 0/3 | Not started | - |
| 3. Remarketing | 0/3 | Not started | - |
| 4. Meta Cloud API | 0/3 | Not started | - |
