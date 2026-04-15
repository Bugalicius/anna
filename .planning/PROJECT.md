# Agente Ana — Assistente Virtual de Agendamento

## What This Is

Agente de WhatsApp "Ana" para a nutricionista Thaynara Teixeira (CRN9 31020). Backend FastAPI com arquitetura multi-agentes que automatiza agendamento de consultas, remarcação, remarketing de leads e suporte pré-consulta. Atende exclusivamente pacientes da Thaynara via WhatsApp com integração completa à Meta Cloud API e Dietbox.

## Core Value

A Ana deve interpretar corretamente a intenção do paciente e conduzir o fluxo certo — sem travar, sem dar resposta errada, sem perder o contexto da conversa. Se a interpretação falha, todo o resto falha.

## Requirements

### Validated

<!-- Funcionalidades entregues e verificadas no código — v1.0 -->

- ✓ Webhook handler com verificação de assinatura HMAC — v1.0 (app/webhook.py)
- ✓ Roteamento por intenção via Claude Haiku (Orquestrador) — v1.0 (app/agents/orchestrator.py)
- ✓ Agente Atendimento com FSM de 10 etapas — v1.0 (app/agents/atendimento.py)
- ✓ Agente Retenção com remarcação e remarketing — v1.0 (app/agents/retencao.py)
- ✓ Agente Dietbox Worker — cadastro, agendamento, consulta — v1.0 (app/agents/dietbox_worker.py)
- ✓ Agente Rede Worker — geração de link de pagamento — v1.0 (app/agents/rede_worker.py)
- ✓ Knowledge base com dados da clínica, planos e FAQ — v1.0 (app/knowledge_base.py)
- ✓ Redis state persistence + serialização de agentes — v1.0 (app/state_manager.py)
- ✓ Context-aware router com detecção de interrupção + reconhecimento por nome — v1.0 (app/router.py)
- ✓ Escalação com 3 caminhos + relay bidirecional + waiting indicator — v1.0 (app/escalation.py)
- ✓ Deduplicação atômica de mensagens via Redis SET NX (TTL 4h) — v1.0 (app/webhook.py)
- ✓ Envio real de PDF e imagens via Meta Cloud API com cache Redis — v1.0 (app/meta_api.py, app/media_store.py)
- ✓ Sanitização de PII (CPF, telefone, email) antes de chamadas ao LLM — v1.0 (app/pii_sanitizer.py)
- ✓ Sistema de remarketing drip 24h/7d/30d com MAX=3 e lead perdido — v1.0 (app/remarketing.py)
- ✓ Regras de remarcação: retorno vs. nova consulta, priorização de horários, Dietbox write-first — v1.0 (app/agents/retencao.py)
- ✓ 255 testes passando — v1.0 (tests/)

### Active

<!-- Escopo v2 — próximo milestone -->

- [ ] **PGTO-01**: Migrar geração de links de Playwright/Rede para API REST (Asaas ou alternativa) — VPS sem display server
- [ ] **AUTO-01**: Lembrete automático 24h antes da consulta
- [ ] **INTL-06**: FAQ inline durante fluxo ativo — responder perguntas incidentais sem resetar etapa atual
- [ ] **INTL-07**: Guard contra alucinação — agente nunca inventa informações clínicas ou de preço
- [ ] **AUTO-02**: Detecção de comprovante de pagamento por análise de imagem
- [ ] **UX-01**: Desconto família detectado automaticamente
- [ ] **UX-02**: Check de satisfação 24h após consulta

### Out of Scope

| Feature | Reason |
|---------|--------|
| SaaS multi-nutricionista | Projeto exclusivo para Thaynara |
| Orientações nutricionais/clínicas | Limites de atuação da Ana — risco legal e ético |
| Atendimento a gestantes/menores de 16 | Política da clínica |
| Oferta proativa do Formulário | Thaynara não quer — só quando paciente perguntar |
| App mobile | Atendimento exclusivo via WhatsApp |
| WhatsApp Pay nativo | PIX + comprovante funciona melhor no Brasil |
| Reembolso automatizado | Requer julgamento humano; risco de fraude |
| Histórico de conversa > 30 dias | Custo de storage + risco LGPD |
| Botões interativos do WhatsApp | Requer aprovação Meta Business; texto numerado funciona |

## Context

**Estado atual (pós v1.0, abril 2026):**
- 255 testes passando, 11.076 LOC Python
- Ana funciona com inteligência conversacional completa: interpreta contexto, adapta fluxo, persiste estado no Redis
- Integração Meta Cloud API: webhook HMAC validado, deduplicação Redis, envio real de PDF/imagens, PII sanitizado antes do LLM
- Sistema de remarketing automático funcionando: 24h/7d/30d, MAX=3, detecção de lead perdido
- Remarcação: regras corretas de retorno vs. nova consulta, priorização de horários, Dietbox write-first
- **Pendência crítica v2**: Rede/Playwright não funciona em VPS sem display server — geração de link de pagamento é o principal bloqueio para produção

**Documentação de referência:**
- `agente-ana-documentacao-final.docx` — documentação oficial do comportamento da Ana (v2.0)
- `docs/regras_remarcacao.md` — regras de remarcação
- `docs/` — PDFs de planos, guias de preparo, imagens de instruções

**Integrações externas:**
- Dietbox — API/scraper para agenda, cadastro, agendamento (funcional via Playwright headless)
- Rede (userede.com.br) — links de pagamento por cartão (Playwright headless=False, **precisa migrar para API REST**)
- Meta Cloud API — gateway WhatsApp (integração completa v1.0)
- Claude Haiku 4.5 — LLM principal para todos os agentes

## Constraints

- **LLM**: Claude Haiku 4.5 (claude-haiku-4-5-20251001) — custo controlado, latência baixa
- **Stack**: Python 3.12 + FastAPI — não mudar
- **Hospedagem**: VPS Linux — sem display server (impacta Playwright headless=False para Rede)
- **Privacidade**: LGPD — nunca armazenar dados sensíveis fora do Dietbox; PII sanitizado antes de chamar LLM (implementado)
- **Segurança**: Número 31 99205-9211 NUNCA exposto ao paciente
- **UX**: Mensagens curtas e objetivas, tom informal/acolhedor, emojis com moderação

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Redis state persistence antes de qualquer outra feature | Estado confiável é pré-requisito de tudo — agente "amnésico" não serve | ✓ Good — todo FSM depende disso |
| Priorizar inteligência da Ana sobre integrações | Agente "burro" é o maior bloqueio para produção | ✓ Good — interpretação correta funcionando |
| Remarcação: comunicar 7 dias, oferecer semana seguinte inteira | Flexibilidade real sem confundir paciente | ✓ Good — implementado e testado |
| Dietbox write-first antes de confirmar ao paciente | Evita confirmação para horário que falhou no Dietbox | ✓ Good — fluxo correto |
| Rede: manter Playwright por ora, migrar em v2 | Automação de navegador funciona em dev, VPS é problema da v2 | ⚠ Revisit — bloqueio principal para deploy em VPS |
| Deduplicação via Redis SET NX (TTL 4h) | Atômica, sem race condition, graceful degradation se Redis cair | ✓ Good — webhook idempotente |
| Sanitização PII context-aware antes do LLM | Regex simples causava ambiguidade entre CPF e telefone sem formatação | ✓ Good — 13 testes, LGPD compliant |
| Público exclusivo: pacientes da Thaynara | Não é SaaS, não precisa de multi-tenancy | ✓ Good |
| Evolution API → Meta Cloud API | Meta Cloud API é a integração oficial e recomendada | ✓ Good — migração concluída em v1.0 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-15 after v1.0 milestone*
