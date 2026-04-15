# Retrospective — Agente Ana

## Milestone: v1.0 — MVP

**Shipped:** 2026-04-15
**Phases:** 4 | **Plans:** 12 | **Duration:** 17 dias (2026-03-29 → 2026-04-15)
**Tests:** 255 passando | **LOC Python:** 11.076 | **Files changed:** 110

---

### What Was Built

- **Fase 1 — Inteligência Conversacional**: Redis state persistence com serialização completa de agentes (`to_dict/from_dict`), router context-aware com detecção de interrupção e reconhecimento por nome, escalação com 3 caminhos + relay bidirecional Breno→paciente + waiting indicator + FAQ aprendido persistente
- **Fase 2 — Fluxo de Remarcação**: Detecção automática retorno vs. nova consulta, algoritmo de priorização de horários (`_priorizar_slots`), sequência Dietbox write-first antes de confirmar ao paciente, fallback para "perde o retorno"
- **Fase 3 — Remarketing**: Migração de BackgroundScheduler para AsyncIOScheduler, drip sequence 24h/7d/30d com MAX=3 tentativas, detecção de `recusou_remarketing`, verificação de conversa ativa antes de disparar
- **Fase 4 — Meta Cloud API**: Deduplicação atômica via Redis SET NX (TTL 4h), envio real de PDF/imagens com cache Redis 23h, sanitização de PII (CPF, telefone, email) antes de chamadas Anthropic

---

### What Worked

- **TDD estrito**: Testes escritos antes do código em todas as fases garantiram que cada feature foi verificável desde o início — regressões detectadas imediatamente
- **Wave-based parallelization**: Planos independentes na mesma fase executaram em paralelo (ex: 04-02 e 04-03 em wave 2), reduzindo tempo de execução
- **Graceful degradation por padrão**: Redis indisponível → webhook processa mesmo assim; template Meta não aprovado → fallback para `send_text`. Decisão de design correta desde o início
- **Worktree isolation**: Executores em worktrees separados evitaram conflitos entre planos paralelos — commit atômico por tarefa manteve histórico limpo
- **Dietbox write-first**: Sequência Dietbox → confirmação paciente funcionou como esperado; evitou confirmações falsas

---

### What Was Inefficient

- **Worktree merge com arquivos untracked**: O arquivo `04-02-SUMMARY.md` foi escrito pelo agente diretamente no repo principal (não no worktree), causando conflito no merge. Precisou de recuperação manual via `git merge d05efe7 --ff-only`. Perda de ~10 min
- **REQUIREMENTS.md não atualizado durante execução**: Todos os 21 requisitos ficaram como "Pending" porque os executores não atualizam REQUIREMENTS.md — só PROJECT.md. A traceability table ficou desatualizada do início ao fim
- **Accomplishments não extraídos pelo CLI**: `gsd-tools milestone complete` não conseguiu extrair one-liners dos SUMMARYs (format mismatch) — precisou de correção manual em MILESTONES.md
- **STATE.md reescrito pelo gsd-tools após update manual**: O `gsd-tools milestone complete` sobrescreveu o STATUS que havia sido atualizado manualmente antes

---

### Patterns Established

- **Deduplicação Redis SET NX**: Padrão para idempotência de webhooks — `SET message_id "1" NX EX 14400` antes de processar
- **PII sanitization antes do LLM**: `sanitize_historico()` chamado em `_gerar_resposta_llm()` — qualquer chamada ao Anthropic passa pelo sanitizador
- **Media dict pattern**: Em vez de strings placeholder `[PDF: nome]`, agentes retornam `{"media_type": "document", "media_key": "guia_homens_pdf"}` — o router despacha o tipo correto automaticamente
- **Context-aware regex para PII**: Telefone e CPF são ambíguos em sequências de 11 dígitos sem formatação — ordem de aplicação (CPF primeiro, depois telefone) e verificação de padrão de CPF resolvem o conflito

---

### Key Lessons

1. **Escrever SUMMARY.md no worktree, não no repo principal** — o agente executor deve criar o SUMMARY dentro do worktree para evitar conflito de merge
2. **gsd-tools summary-extract assume formato específico** — SUMMARYs precisam ter `**One-liner:**` como prefixo exato para extração automática funcionar
3. **Verificar worktree merge antes de deletar a branch** — `git log --oneline HEAD..branch` antes de `git worktree remove --force` evita perda de commits
4. **Graceful degradation em Redis é obrigatório em todas as features que usam Redis** — qualquer `redis.set()` ou `redis.get()` deve ter `try/except` com fallback funcional
5. **Meta Cloud API templates precisam de aprovação prévia (72h+)** — iniciar processo de aprovação antes de codificar a fase de templates

---

### Cost Observations

- Model mix: Sonnet 4.6 para executores e verificador, Haiku 4.5 em runtime
- Sessions: ~3 sessões principais de desenvolvimento
- Notable: Execução paralela de planos independentes (worktrees) reduziu tempo total estimado em ~40% vs. execução sequencial

---

## Cross-Milestone Trends

| Metric | v1.0 MVP |
|--------|---------|
| Phases | 4 |
| Plans | 12 |
| Tests | 255 |
| LOC Python | 11.076 |
| Duration | 17 dias |
| Parallel execution | Sim (worktrees) |
| TDD | Sim (todas as fases) |
