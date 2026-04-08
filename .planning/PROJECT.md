# Agente Ana — Assistente Virtual de Agendamento

## What This Is

Agente de WhatsApp "Ana" para a nutricionista Thaynara Teixeira (CRN9 31020). Backend FastAPI com arquitetura multi-agentes (5 agentes especializados) que automatiza agendamento de consultas, atendimento a dúvidas, remarketing de leads e suporte pré/pós-agendamento. Atende exclusivamente pacientes da Thaynara via WhatsApp.

## Core Value

A Ana deve interpretar corretamente a intenção do paciente e conduzir o fluxo certo — sem travar, sem dar resposta errada, sem perder o contexto da conversa. Se a interpretação falha, todo o resto falha.

## Requirements

### Validated

<!-- Funcionalidades que já existem e funcionam no código -->

- ✓ Webhook handler para receber mensagens WhatsApp — existing (app/webhook.py)
- ✓ Roteamento por intenção via Claude Haiku (Orquestrador) — existing (app/agents/orchestrator.py)
- ✓ Agente 1 (Atendimento) com FSM de 10 etapas — existing (app/agents/atendimento.py)
- ✓ Agente 2 (Retenção) com remarcação e remarketing — existing (app/agents/retencao.py)
- ✓ Agente 3 (Dietbox Worker) — cadastro, agendamento, consulta de agenda — existing (app/agents/dietbox_worker.py)
- ✓ Agente 4 (Rede Worker) — geração de link de pagamento por automação — existing (app/agents/rede_worker.py)
- ✓ Knowledge base com dados da clínica, planos e FAQ — existing (app/knowledge_base.py)
- ✓ Interface de teste em http://localhost:8000/test/chat — existing (app/static/)
- ✓ 104 testes passando (pytest) — existing (tests/)
- ✓ Banco SQLite com SQLAlchemy + Alembic — existing (app/database.py)

### Active

<!-- Escopo atual — o que precisa ser construído/corrigido -->

**Prioridade 1 — Inteligência da Ana (bloqueio principal):**
- [ ] Corrigir interpretação de contexto — agente deve entender a conversa e adaptar o fluxo, não seguir rigidamente
- [ ] Alinhar comportamento do agente com a documentação oficial (agente-ana-documentacao-final.docx)
- [ ] Corrigir regras de remarcação de retorno: comunicar "até 7 dias", mas oferecer semana seguinte inteira (seg-sex)
- [ ] Priorização de horários na remarcação: 1) mais próximo da preferência, 2) próximo mais próximo, 3) mais distante disponível
- [ ] Negociação flexível de horários com fallback para "perde o retorno" se nenhum encaixar
- [ ] Distinção entre remarcação de retorno (já pagou, prazo de 7 dias) e nova consulta (sem restrição)
- [ ] Enviar "Um instante, por favor 💚" antes de operações demoradas (consulta Dietbox, busca de horários)
- [ ] Escalar para 31 99205-9211 (interno) quando não souber responder, e repassar a resposta ao paciente

**Prioridade 2 — Gateway de Pagamento (Rede):**
- [ ] Pesquisar e migrar de automação Playwright para API REST e-Rede (ou alternativa)
- [ ] Garantir que funcione em VPS sem display server
- [ ] Manter geração de links de pagamento por plano/modalidade/parcelas

**Prioridade 3 — Remarketing:**
- [ ] Implementar sistema de follow-up automático (24h, 7d, 30d)
- [ ] Controle de contadores (máximo 3 tentativas) e etiquetas
- [ ] Mensagens conforme documentação (seção 6)

**Prioridade 4 — Meta Cloud API:**
- [ ] Finalizar integração com Meta Cloud API (substituir Evolution API)
- [ ] Verificação de assinatura de webhook
- [ ] Envio/recebimento de mensagens, mídia e templates

### Out of Scope

- SaaS multi-nutricionista — projeto é exclusivo para Thaynara
- Orientações nutricionais/clínicas pela Ana — limites claros de atuação
- Atendimento a gestantes e menores de 16 anos — política da clínica
- Oferta proativa da modalidade Formulário — só quando paciente perguntar
- App mobile — atendimento exclusivo via WhatsApp

## Context

**Estado atual (abril 2026):**
- Fase 3 concluída: multi-agentes + testes de integração (104 testes)
- Ana funciona na interface de teste (localhost:8000/test/chat) mas com problemas de inteligência
- Agente não interpreta contexto corretamente — segue fluxo rígido sem adaptar
- Regras de remarcação implementadas incorretamente
- Integração Rede usa Playwright com headless=False (não funciona em VPS, lento ~180s, frágil)
- APScheduler configurado para remarketing mas lógica de disparo não testada

**Documentação de referência:**
- `agente-ana-documentacao-final.docx` — documentação oficial do comportamento da Ana (v2.0)
- `docs/regras_remarcacao.md` — regras de remarcação (template com ⚠️ a preencher)
- `docs/` — PDFs de planos, guias de preparo, imagens de instruções

**Integrações externas:**
- Dietbox — API/scraper para agenda, cadastro, agendamento (funcional via Playwright headless)
- Rede (userede.com.br) — links de pagamento por cartão (Playwright headless=False, precisa migrar)
- Evolution API — gateway WhatsApp atual
- Meta Cloud API — gateway WhatsApp futuro
- Claude Haiku 4.5 — LLM principal para todos os agentes

## Constraints

- **LLM**: Claude Haiku 4.5 (claude-haiku-4-5-20251001) — custo controlado, latência baixa
- **Stack**: Python 3.12 + FastAPI — não mudar
- **Hospedagem**: VPS Linux — sem display server (impacta Playwright headless=False)
- **Privacidade**: LGPD — nunca armazenar dados sensíveis fora do Dietbox, pseudonimização para LLM
- **Segurança**: Número 31 99205-9211 NUNCA exposto ao paciente
- **UX**: Mensagens curtas e objetivas, tom informal/acolhedor, emojis com moderação

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Manter Evolution API por enquanto | Testar agente offline antes de finalizar Meta | — Pending |
| Priorizar inteligência da Ana sobre integrações | Agente "burro" é o maior bloqueio para produção | — Pending |
| Remarcação: comunicar 7 dias, oferecer semana seguinte inteira | Flexibilidade real sem confundir paciente | — Pending |
| Rede: migrar de Playwright para API REST (ou alternativa) | Automação de navegador não funciona em VPS, é frágil e lenta | — Pending |
| Público exclusivo: pacientes da Thaynara | Não é SaaS, não precisa de multi-tenancy | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-07 after initialization*
