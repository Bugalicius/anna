# Phase 2: Fluxo de Remarcação - Context

**Gathered:** 2026-04-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Ana gerencia remarcação de consultas: detecta se é retorno ou nova consulta, aplica regras de prazo corretas, apresenta horários priorizados, negocia com o paciente, atualiza o Dietbox antes de confirmar. Cobre REMC-01 a REMC-06.

Não inclui: remarketing (Fase 3), Meta Cloud API (Fase 4).

</domain>

<decisions>
## Implementation Decisions

### Detecção: Retorno vs. Nova Consulta (REMC-03)
- **D-01:** Ana verifica no Dietbox se o paciente tem consulta agendada E lançamento financeiro
- **D-02:** Tem consulta + lançamento financeiro → é retorno. Prazo e regras de remarcação de retorno se aplicam
- **D-03:** Tem consulta mas SEM lançamento financeiro → paciente ainda não pagou. Ana pergunta plano e modalidade e segue o fluxo normal de atendimento (nova consulta)
- **D-04:** Não tem consulta agendada → nova consulta, fluxo normal de atendimento

### Janela de Remarcação (REMC-01)
- **D-05:** Prazo = sempre até a sexta-feira da semana APÓS a semana do agendamento original
  - Ex: consulta na semana 13-17/04 → pode remarcar até sexta 24/04
  - Ex: consulta segunda 13/04 → até sexta 24/04. Consulta sexta 17/04 → também até sexta 24/04
  - Calculado a partir da semana do agendamento, não de hoje
- **D-06:** Início da janela de busca: amanhã (dia seguinte ao pedido de remarcação) — nunca o mesmo dia
- **D-07:** Slots oferecidos: apenas seg-sex. Sábado e domingo nunca aparecem
- **D-08:** A mensagem inicial comunica "prazo máximo para a remarcação" sem citar a data exata calculada internamente

### Priorização de Horários (REMC-02)
- **D-09:** Sempre oferecer exatamente 3 opções
- **D-10:** Opção 1: slot mais próximo da preferência declarada do paciente (dia da semana + hora)
- **D-11:** Opções 2 e 3: próximos disponíveis na janela (qualquer horário)
- **D-12:** Se não houver slot compatível com a preferência: oferecer as 3 primeiras opções disponíveis na janela, sem mencionar preferência
- **D-13:** Slots de dias diferentes são preferidos — evitar oferecer 3 opções no mesmo dia

### Negociação Flexível (REMC-06)
- **D-14:** Após paciente rejeitar os 3 slots oferecidos, Ana oferece mais 3 do pool restante
- **D-15:** Se paciente rejeitar a segunda rodada também → declarar "perda de retorno" (último recurso)
- **D-16:** Durante negociação, Ana pode sugerir horários próximos à preferência: "Não tenho segunda, mas tenho terça às 9h — funciona?"

### Fallback "Perda de Retorno" (REMC-05)
- **D-17:** Só declarado após 2 rodadas de negociação sem acordo (D-14, D-15)
- **D-18:** Mensagem: informar que o prazo não comporta mais remarcação e que o retorno será perdido
- **D-19:** Após declarar perda do retorno, oferecer agendar como nova consulta (com cobrança normal)

### Dietbox: Sequência de Confirmação (REMC-04)
- **D-20:** Sequência OBRIGATÓRIA: (1) atualiza Dietbox → (2) verifica sucesso → (3) envia confirmação ao paciente
- **D-21:** Nunca enviar confirmação antes de o Dietbox confirmar a atualização
- **D-22:** O agendamento original tem sua data/hora alterada para o novo slot (não cancela e recria)
- **D-23:** Adicionar observação no agendamento: "Remarcado do dia X para dia Y"
- **D-24:** Enviar confirmação similar ao agendamento novo (com data, hora, modalidade)
- **D-25:** Dietbox é a fonte de verdade — nutri acompanha agenda, consultas e financeiro por lá

### Mensagens Fixas
- **D-26:** Mensagens conforme `docs/regras_remarcacao.md` — usar como base canônica
- **D-27:** Tom: informal, acolhedor, com emojis moderados (💚, 😊, ✅, 📅) — alinhado com documentação oficial

### Claude's Discretion
- Implementação exata do cálculo da janela (sexta da semana seguinte ao agendamento)
- Estratégia de fallback quando o Dietbox não retorna o agendamento do paciente (paciente sem consulta cadastrada)
- Formato exato da observação de remarcação no Dietbox
- Lógica de detecção de preferência de horário do paciente (parse de texto livre)

</decisions>

<specifics>
## Specific Ideas

- Dietbox é a base de toda operação da Thaynara — toda alteração deve refletir lá primeiro
- "Remarcado do dia X para dia Y" é a observação a inserir no agendamento original
- Paciente sem lançamento financeiro = ainda não pagou = trata como nova consulta
- Nunca oferecer horário no mesmo dia do pedido
- Janela calculada a partir da semana do agendamento original, não de hoje

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Regras de remarcação
- `docs/regras_remarcacao.md` — Regras de janela, seleção de slots, mensagens fixas, horários por dia. Fonte canônica para comportamento da Ana no fluxo de remarcação
- `agente-ana-documentacao-final.docx` — Documentação oficial v2.0. Tom, identidade, regras gerais de comunicação

### Código existente a modificar
- `app/agents/retencao.py` — Fluxo de remarcação atual (FSM, lógica de slots, mensagens). Contém implementação INCORRETA que precisa ser corrigida
- `app/agents/dietbox_worker.py` — Worker Dietbox. Tem `consultar_slots_disponiveis()` mas NÃO tem função de alterar agendamento — precisa ser criada
- `app/router.py` — Roteamento de intenções para AgenteRetencao

### Fase anterior
- `.planning/phases/01-intelig-ncia-conversacional/01-CONTEXT.md` — Decisões de interrupt detection, Redis state, escalação — manter compatibilidade

</canonical_refs>

<deferred>
## Deferred Ideas

- Lembrete automático de remarcação após X dias sem resposta (v2)
- Sugestão proativa de horário com base no histórico do paciente (v2)

</deferred>

---

*Phase: 02-fluxo-de-remarca-o*
*Context gathered: 2026-04-09*
