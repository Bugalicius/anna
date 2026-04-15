# Milestones

## v1.0 MVP (Shipped: 2026-04-15)

**Phases completed:** 4 phases, 12 plans, 0 tasks

**Stats:** 4 fases | 12 planos | 110 arquivos | 20.952 linhas | 11.076 LOC Python | 17 dias | 255 testes

**Key accomplishments:**

- Redis state persistence + serialização de agentes — Ana mantém contexto entre reinicializações do processo
- Router context-aware com detecção de interrupção + reconhecimento por nome do paciente
- Escalação com 3 caminhos + relay bidirecional (Breno→paciente) + waiting indicator + FAQ aprendido
- Fluxo de remarcação: detecção retorno vs. nova consulta, priorização de horários, Dietbox write antes da confirmação
- Sistema de remarketing 24h/7d/30d com MAX=3 tentativas, lead perdido e verificação de conversa ativa
- Meta Cloud API: dedup Redis SET NX (TTL 4h), envio real de PDF/imagens, sanitização PII/LGPD antes do LLM

---
