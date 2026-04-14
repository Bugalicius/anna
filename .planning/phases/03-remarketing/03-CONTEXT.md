# Phase 3: Remarketing - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Sistema de follow-up automático funciona de ponta a ponta: scheduler dispara nas janelas certas (24h, 7d, 30d), textos aprovados pelo usuário são enviados, controle de tentativas e "lead perdido" funcionam, e remarketing não interrompe conversa ativa.

Não inclui: envio de mídia (Fase 4), campanhas em massa, segmentação de leads por perfil clínico.

</domain>

<decisions>
## Implementation Decisions

### Sequência e Textos dos Templates

- **D-01:** Sequência fixa: 3 mensagens em 24h, 7 dias e 30 dias após o lead ficar em silêncio. MAX_REMARKETING = 3 (RMKT-04). Sequência atual no código (5 mensagens, delays errados) deve ser corrigida.

- **D-02:** Texto da mensagem 1 (24h):
  ```
  Eiii! 😊 Tudo bem por aí?

  Fico pensando se ficou alguma dúvida sobre a consulta com a Thaynara... Pode me perguntar à vontade, tô aqui pra isso! 💚

  Quando quiser marcar é só me falar 📅
  ```

- **D-03:** Texto da mensagem 2 (7 dias):
  ```
  Oii! Passando pra saber se você teve chance de pensar na consulta com a Thaynara 🌿

  Às vezes bate aquela dúvida se vale a pena... mas a maioria das pacientes conta que a primeira consulta já muda bastante a relação com a alimentação 😊

  Se quiser conversar sobre qualquer coisa antes de decidir, me chama! 👉
  ```

- **D-04:** Texto da mensagem 3 (30 dias):
  ```
  Eiii, última passagem por aqui! 💚

  Sei que a vida corrida faz a gente adiar algumas coisas... Se um dia você quiser dar esse passo, pode me chamar que a gente vê o melhor horário pra você com a Thaynara 📅

  Qualquer coisa, estarei por aqui! 😊
  ```

### Templates Meta vs Texto Livre

- **D-05:** Mensagem 24h → tenta `send_text` primeiro. Se a Meta rejeitar por janela fechada (erro 131026 ou similar), loga e aguarda template aprovado.

- **D-06:** Mensagens 7d e 30d → ficam na fila mas só disparam depois que os templates Meta estiverem aprovados. Plano 03-03 inclui: criação dos templates no formato exato, instruções para submissão no Business Manager, e código que usa `send_template()` quando aprovados.

- **D-07:** Nomes dos templates na Meta: `ana_followup_24h`, `ana_followup_7d`, `ana_followup_30d`. O conteúdo dos templates deve espelhar exatamente os textos de D-02, D-03 e D-04.

### Detecção de "Lead Perdido"

- **D-08:** Quando lead responde negativamente ("não tenho interesse", "pode tirar meu número", "não vou marcar", "deixa pra lá", etc.) → orquestrador classifica como `recusou_remarketing` (nova intenção a ser adicionada) com fallback de palavras-chave para casos óbvios.

- **D-09:** Ao detectar `recusou_remarketing`: Ana envia a mensagem de encerramento e move para `stage = "lead_perdido"`:
  ```
  Tudo bem! Posso perguntar o que pesou na decisão? Só pra melhorar nosso atendimento 😊
  ```
  Após a resposta do lead (ou silêncio de 24h), encerra sem mais mensagens. Nenhum remarketing adicional é enviado.

- **D-10:** `stage = "lead_perdido"` cancela toda a fila pendente de RemarketingQueue para aquele contact_id.

### Verificação de Conversa Ativa

- **D-11:** Antes de disparar qualquer mensagem de remarketing, o scheduler verifica se existe estado Redis para o `phone_hash` do contato (chave `agent_state:{phone_hash}`).
  - Se existe → pula este ciclo (skip, não cancela nem reagenda). O scheduler tenta de novo no próximo ciclo (1 minuto).
  - Se não existe → dispara normalmente.

- **D-12:** Quando o lead manda qualquer mensagem (inclusive resposta ao remarketing), `cancel_pending_remarketing()` já é chamado automaticamente em `route_message()` — comportamento existente, mantido.

### APScheduler — Migração para AsyncIOScheduler

- **D-13:** Migrar de `BackgroundScheduler` para `AsyncIOScheduler`. Jobs de remarketing passam a rodar no event loop do FastAPI, permitindo `await` em `meta.send_text()` e operações de banco assíncronas.

- **D-14:** A função `_dispatch_due_messages` passa a ser `async def`. A função `create_scheduler()` retorna `AsyncIOScheduler`.

- **D-15:** `SQLAlchemyJobStore` mantido para persistência de jobs entre reinícios. Configuração de intervalo mantida (1 min remarketing, 5 min retry).

### Claude's Discretion

- Estratégia de rate limiting Redis no scheduler async (adaptar lógica atual de 30/min)
- Estrutura exata da nova intenção `recusou_remarketing` no orchestrator
- Timeout para "silêncio do lead" após pergunta de encerramento (24h recomendado)
- Mecanismo de verificação do Redis no scheduler (usar `redis.asyncio` ou `_state_mgr` global)

</decisions>

<specifics>
## Specific Ideas

- Os 3 textos foram escritos pela Ana e aprovados por Breno — são a fonte de verdade para os templates
- "Lead perdido" não é abandono silencioso — Ana sempre pergunta o motivo antes de encerrar (tom de melhoria contínua, não pressão)
- A verificação de conversa ativa protege o paciente de ser interrompido enquanto está fechando uma consulta
- Templates Meta precisam ser aprovados manualmente no Business Manager — isso pode levar dias. O código deve funcionar sem eles (graceful degradation para o 24h)

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Código existente a modificar
- `app/remarketing.py` — Scheduler, fila, dispatch. Reescrever sequência e migrar scheduler
- `app/agents/orchestrator.py` — Adicionar intenção `recusou_remarketing` ao classificador
- `app/main.py` — Trocar BackgroundScheduler por AsyncIOScheduler no lifespan
- `app/models.py` — `RemarketingQueue`, `Contact.stage` (adicionar `lead_perdido`)
- `app/meta_api.py` — `send_template()` (já existe parcialmente), verificar `send_text` fallback

### Contexto de fases anteriores
- `.planning/phases/01-intelig-ncia-conversacional/01-CONTEXT.md` — D-20: trigger do remarketing ("vou pensar")
- `.planning/phases/01-intelig-ncia-conversacional/01-02-SUMMARY.md` — Redis state, interrupt detection, orchestrator
- `app/state_manager.py` — `RedisStateManager` com prefixo `agent_state:` — usar para verificar conversa ativa

### Documentação do produto
- `agente-ana-documentacao-final.docx` §6 — Templates de remarketing (referência original)
- `docs/regras_remarcacao.md` — Regras de contexto para leads

</canonical_refs>

<deferred>
## Deferred Ideas

- Segmentação de leads por comportamento (pediu preço, mencionou concorrente) — era o `BEHAVIORAL_TEMPLATES` original, removido do escopo desta fase
- Campanha de reativação em datas especiais (Dia das Mães, Verão) — backlog
- Dashboard de métricas de remarketing (taxa de conversão por mensagem) — backlog

</deferred>

---

*Phase: 03-remarketing*
*Context gathered: 2026-04-14*
