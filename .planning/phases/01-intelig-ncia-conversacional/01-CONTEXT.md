# Phase 1: Inteligência Conversacional - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Ana interpreta corretamente o que o paciente diz, adapta o fluxo sem resetar, persiste estado entre reinícios, e escala para humano quando não sabe responder. Cobre os requisitos INTL-01 a INTL-05.

Não inclui: regras de remarcação (Fase 2), remarketing (Fase 3), Meta Cloud API (Fase 4).

</domain>

<decisions>
## Implementation Decisions

### Interrupt Detection
- **D-01:** Toda mensagem passa pelo orquestrador MESMO com agente ativo — classificação sempre acontece
- **D-02:** Intenções que INTERROMPEM o fluxo (troca de agente): `remarcar`, `cancelar`, `duvida_clinica`
- **D-03:** Intenções respondidas INLINE sem sair do fluxo: `tirar_duvida`, `fora_de_contexto` — responde e volta para etapa atual
- **D-04:** Mudança de etapa DENTRO do mesmo agente é permitida (ex: "quero trocar de plano" volta para `escolha_plano`)

### Escalação — 3 caminhos
- **D-05:** Dúvida clínica + paciente cadastrado → Ana diz "Aqui é um canal somente para marcação de consultas. Para dúvidas clínicas por favor chame a Thaynara no WhatsApp" → envia contato da Thaynara (5531991394759). Não escala internamente, não aguarda resposta
- **D-06:** Dúvida clínica + NÃO é paciente (lead) → encaminha para Breno (31 99205-9211) com contexto. Ana: "Só um instante, vou verificar essa informação 💚". Memoriza resposta do Breno para próximas vezes. Repassa ao paciente
- **D-07:** Ana não sabe responder (qualquer situação) → encaminha para Breno (31 99205-9211). Mesma mecânica: aguarda, memoriza, repassa
- **D-08:** Número 31 99205-9211 (Breno) NUNCA é exposto ao paciente — é exclusivamente interno
- **D-09:** Cobrança ao Breno: a cada 15 min na primeira hora (15, 30, 45, 60 min), depois a cada 1h (2h, 3h, ...)
- **D-10:** Após 1h sem resposta do Breno → Ana avisa paciente: "Ainda estou verificando, te aviso assim que tiver retorno 💚"
- **D-11:** Respostas aprendidas são salvas na knowledge base como FAQ aprendido — persiste entre deploys, revisável

### Redis State Persistence
- **D-12:** Estado de conversa (fluxo ativo) persiste no Redis SEM TTL automático — só limpa quando fluxo termina (`finalizacao`)
- **D-13:** Perfil do paciente (nome, sobrenome, dados permanentes) salvo no PostgreSQL via tabela `Contact` expandida — NUNCA expira
- **D-14:** Paciente que retorna é reconhecido pelo perfil: "Ei Marcela, lembro que já nos falamos! Como posso te ajudar?" — sem re-perguntar nome
- **D-15:** Falha do Redis → loga erro, cria estado novo, Ana pede as informações novamente: "Tive um probleminha técnico e perdi algumas informações da nossa conversa. Poderia me passar seu nome novamente?"

### Alinhamento com Documentação
- **D-16:** Fora de contexto: escalar na primeira mensagem que Ana não souber responder (sem contador de 2x). Pergunta ao Breno, memoriza, responde
- **D-17:** Múltiplas perguntas por mensagem são permitidas DESDE QUE o agente consiga interpretar respostas parciais/fora de ordem
- **D-18:** Tom e expressões conforme documentação: "Eiii", "Perfeitoooo", "Obrigadaaa" — informal, caloroso, com emojis moderados (💚, 😊, ✅, 📅, 👉)
- **D-19:** Agendamento: nunca oferecer horário no mesmo dia. Mínimo 1 dia útil. Quando oferecer na mesma semana, usar o termo "tive uma desistência amanhã às X horas"
- **D-20:** "Vou pensar" / "Vou confirmar depois" → remarketing tradicional (24h, 7d, 30d). No dia seguinte Ana pergunta proativamente se pensou, se ficou alguma dúvida, se pode ajudar

### Waiting Indicator
- **D-21:** Ana envia "Um instante, por favor 💚" (ou variação) ANTES de qualquer operação demorada: consulta Dietbox, busca de horários, geração de link de pagamento

### Claude's Discretion
- Formato exato do structured LLM output (`{nova_etapa, slots_atualizados, resposta}`)
- Schema de serialização Redis (`to_dict()/from_dict()`)
- Implementação do mecanismo de cobrança ao Breno (APScheduler job vs loop async)
- Formato de armazenamento do FAQ aprendido na knowledge base
- Colunas exatas a adicionar na tabela `Contact`

</decisions>

<specifics>
## Specific Ideas

- Breno (não Thaynara) é quem recebe escalações internas no 31 99205-9211. Ele decide se consulta a Thaynara ou responde direto
- Paciente de retorno deve ser tratado com familiaridade — Ana lembra do nome e do contexto anterior
- "Tive uma desistência" é a expressão comercial usada quando oferece horário na mesma semana — faz parte do tom de vendas
- Follow-up do "vou pensar": tom de interesse genuíno, não pressão. "Pensou sobre a consulta? Ficou alguma dúvida? Posso te ajudar?"

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Comportamento e fluxo da Ana
- `agente-ana-documentacao-final.docx` — Documentação oficial v2.0. Define identidade, tom, fluxo de 10 etapas, regras de comunicação, escalação, remarketing, FAQ, pagamento, cadastro. É a fonte de verdade para INTL-05
- `agente-ana-documentacao-final.docx` §1.2 — Tom e linguagem: expressões naturais, emojis, limite de formalidade
- `agente-ana-documentacao-final.docx` §3.1 — Regras de comunicação: interpretar variações, abreviações, gírias
- `agente-ana-documentacao-final.docx` §3.3 — Regras de escalação para humano: quando escalar, como escalar, timeout
- `agente-ana-documentacao-final.docx` §3.5 — Regras de agendamento: 3 opções, priorização, sem mesmo dia
- `agente-ana-documentacao-final.docx` §7 — Comportamentos especiais: não sabe responder, fora de contexto, dúvidas clínicas, "vou pensar"

### Knowledge base existente
- `app/knowledge_base.py` — Singleton com dados estáticos. FAQ aprendido será adicionado aqui
- `knowledge_base/` — Diretório com JSONs/MDs de planos, preços, políticas

### Código existente a modificar
- `app/router.py` — `_AGENT_STATE` dict in-memory (será substituído por Redis), lógica de roteamento
- `app/agents/orchestrator.py` — Classificador de intenções (será chamado sempre, não só sem agente ativo)
- `app/agents/atendimento.py` — FSM de 10 etapas (receberá structured LLM output + interrupt detection)
- `app/agents/retencao.py` — FSM de retenção (mesma refatoração de serialização)
- `app/escalation.py` — Escalação atual (será expandida com 3 caminhos + relay bidirecional com Breno)
- `app/database.py` + `app/models.py` — Tabela Contact (será expandida com perfil permanente)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/agents/orchestrator.py:_classificar_intencao()` — Classificador LLM já funcional, retorna `(intencao, confianca)`. Será chamado sempre em vez de só sem agente ativo
- `app/escalation.py:escalar_para_humano()` — Função async que envia para número interno. Base para expandir relay
- `app/escalation.py:build_contexto_escalacao()` — Monta contexto para escalação. Reutilizável
- `app/knowledge_base.py:KnowledgeBase` — Singleton com `system_prompt()`, `get_valor()`, `get_plano()`. Ponto de extensão para FAQ aprendido
- `app/agents/atendimento.py:_gerar_resposta_llm()` — Chamada LLM com system prompt + contexto. Base para structured output

### Established Patterns
- Agents usam FSM com `etapa: str` + `_despachar()` → `_etapa_X()`. Refatorar para structured output mantendo esse pattern
- Workers retornam `{"sucesso": bool, "erro": ...}` — manter para Dietbox/Rede
- Mensagens fixas como constantes `MSG_*` no topo do módulo — manter, mas alinhar com documentação
- `phone_hash` como chave de estado — manter para Redis

### Integration Points
- `app/router.py:route_message()` — Ponto central: aqui entra a chamada ao orquestrador sempre + Redis load/save
- `app/main.py` lifespan — Onde inicializar conexão Redis
- `docker-compose.yml` — Redis 7 já configurado como serviço
- `app/models.py:Contact` — Tabela existente, precisa de migration Alembic para novas colunas

</code_context>

<deferred>
## Deferred Ideas

- Detecção de comprovante por análise de imagem (v2 — AUTO-02)
- Desconto família automático (v2 — UX-01)
- Guard contra alucinação / informações inventadas (v2 — INTL-07)
- Interface admin para revisar FAQ aprendido (backlog)

</deferred>

---

*Phase: 01-intelig-ncia-conversacional*
*Context gathered: 2026-04-08*
