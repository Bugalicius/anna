---
phase: 04-meta-cloud-api
verified: 2026-04-15T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
deferred: []
human_verification:
  - test: "Enviar mensagem WhatsApp real com CPF no texto e verificar que a Anthropic recebeu '[CPF]'"
    expected: "Historico enviado ao LLM nao contem o CPF digitado"
    why_human: "Requer sessao ativa com Meta Cloud API e acesso aos logs de chamada Anthropic — nao testavel sem infra real"
  - test: "Enviar mesma mensagem duas vezes via Meta Cloud API e verificar que o agendamento nao e duplicado"
    expected: "Apenas um agendamento criado no Dietbox, log mostra 'Dedup Redis: mensagem X ja processada'"
    why_human: "Requer Redis e Meta Cloud API ativos simultaneamente para simular entrega duplicada real"
  - test: "Acionar fluxo de confirmacao de consulta e verificar que paciente recebe PDF e imagem reais"
    expected: "Paciente recebe doc/imagem como arquivo no WhatsApp, nao texto placeholder"
    why_human: "Requer numero WhatsApp ativo e ambiente de producao para confirmar entrega de midia"
---

# Phase 04: Meta Cloud API — Verification Report

**Phase Goal:** Integração Meta Cloud API é segura, idempotente e compliant com LGPD — webhook validado por HMAC, deduplicação previne agendamentos duplicados, mídia real enviada, dados de pacientes pseudonimizados antes de chegar ao LLM
**Verified:** 2026-04-15
**Status:** passed
**Re-verification:** Não — verificação inicial

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Webhook rejeita requisições sem assinatura HMAC válida | VERIFIED | `verify_signature()` em `app/meta_api.py` usa `hmac.compare_digest`; chamada em `receive_webhook()` na linha 54 de `app/webhook.py` retorna 403 se inválido |
| 2 | Mesma mensagem entregue duas vezes pelo Meta não cria dois agendamentos | VERIFIED | `_is_duplicate_message()` implementado em `app/webhook.py` com Redis SET NX + TTL 14400s; chamado antes do bloco `SessionLocal`; graceful degradation para dedup DB como segunda camada |
| 3 | PDFs e imagens de preparo são enviados como arquivos reais (não placeholders de texto) | VERIFIED | 4 placeholders `[PDF:]`/`[IMG:]` removidos de `atendimento.py`; substituídos por dicts `{media_type, media_key, caption}`; `_enviar_midia` e `_get_or_upload_media` em `router.py` fazem upload real com cache Redis |
| 4 | Dados sensíveis do paciente (CPF, telefone) não aparecem em chamadas à API da Anthropic | VERIFIED | `sanitize_historico()` chamado em `_gerar_resposta_llm` antes de construir `msgs`; `app/pii_sanitizer.py` mascara CPF, telefone, email com 6 regex compilados; historico original preservado |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Esperado | Status | Detalhes |
|----------|----------|--------|---------|
| `app/webhook.py` | Redis dedup atomica via SET NX | VERIFIED | Contém `_is_duplicate_message`, `dedup:msg:`, `_DEDUP_TTL = 14400`, chamada antes de `SessionLocal` |
| `app/meta_api.py` | MetaAPIClient com args opcionais + upload_media/send_document/send_image | VERIFIED | `phone_number_id: str \| None = None`, `access_token: str \| None = None`, todos os 3 métodos de mídia presentes |
| `app/media_store.py` | Catálogo de 5 arquivos estáticos | VERIFIED | `MEDIA_STATIC` com 5 chaves: `pdf_thaynara`, `img_preparo_online`, `img_preparo_presencial`, `pdf_guia_circunf_mulher`, `pdf_guia_circunf_homem` |
| `app/pii_sanitizer.py` | sanitize_message() e sanitize_historico() | VERIFIED | Ambas funções presentes; 6 regex compilados; aliases `_CPF_RE` e `_PHONE_BR_RE` para compatibilidade |
| `app/agents/atendimento.py` | Sem placeholders [PDF/IMG]; usa sanitize_historico | VERIFIED | Grep `[PDF:` e `[IMG:` retornam zero matches; `from app.pii_sanitizer import sanitize_historico` na linha 31; `historico_limpo` na linha 210 |
| `app/router.py` | _enviar detecta dicts de mídia e envia via Meta Cloud API | VERIFIED | `_MEDIA_CACHE_TTL = 82800`, `_enviar_midia`, `_get_or_upload_media`, `send_document`, `send_image` todos presentes |
| `tests/test_webhook.py` | Testes dedup Redis | VERIFIED | `test_dedup_redis_blocks_duplicate`, `test_dedup_redis_allows_first`, `test_dedup_graceful_degradation` presentes |
| `tests/test_meta_api.py` | Testes MetaAPIClient sem args + mídia | VERIFIED | `test_client_no_args_reads_env`, `test_upload_media_returns_media_id`, `test_send_document_payload`, `test_send_image_payload`, `test_media_store_has_all_keys` presentes |
| `tests/test_pii_sanitizer.py` | 13+ testes de PII | VERIFIED | 13 testes cobrindo CPF formatado/sem pontuação, telefone, email, injection, historico; todos passam |

### Key Link Verification

| From | To | Via | Status | Detalhes |
|------|----|-----|--------|---------|
| `app/webhook.py` | `redis.asyncio` | SET NX com key `dedup:msg:{meta_message_id}` | WIRED | Import `redis.asyncio as aioredis` na linha 5; key pattern verificada na linha 26 |
| `app/meta_api.py` | `os.environ` | MetaAPIClient le WHATSAPP_PHONE_NUMBER_ID e WHATSAPP_TOKEN | WIRED | Linha 25-26: `phone_number_id or os.environ.get(...)` |
| `app/agents/atendimento.py` | `app/pii_sanitizer.py` | import sanitize_historico; chamado em _gerar_resposta_llm | WIRED | Linha 31 (import) + linhas 209-211 (uso com comentário LGPD) |
| `app/agents/atendimento.py` | `app/router.py` | Retorna dicts {media_type, media_key} em vez de strings [PDF: ...] | WIRED | 4 dicts confirmados nas linhas 338, 633, 634, 645 de atendimento.py; router.py detecta via `isinstance(msg, dict) and "media_type" in msg` |
| `app/router.py` | `app/meta_api.py` | _enviar chama send_document/send_image quando detecta dict de mídia | WIRED | `_enviar_midia` chama `meta.send_document` (linha 304) e `meta.send_image` (linha 306) |
| `app/router.py` | Redis | Cache media_id com key `media_id:{hash}` TTL 82800s | WIRED | `cache_key = f"media_id:..."` na linha 314; `r.set(cache_key, media_id, ex=_MEDIA_CACHE_TTL)` na linha 340 |
| `app/webhook.py` | HMAC validation | verify_signature chamado antes de processar payload | WIRED | Linha 54: `if not verify_signature(body, signature, APP_SECRET): raise HTTPException(403)` |

### Data-Flow Trace (Level 4)

| Artifact | Variável de Dados | Fonte | Produz Dados Reais | Status |
|----------|------------------|-------|-------------------|--------|
| `app/pii_sanitizer.py` → `_gerar_resposta_llm` | `historico_limpo` | `sanitize_historico(historico[-10:])` — filtra cópia do historico real | Sim — histórico real do FSM, apenas sanitizado | FLOWING |
| `app/router.py` `_get_or_upload_media` | `media_id` | Redis cache ou `meta.upload_media(file_bytes, ...)` com bytes lidos do filesystem | Sim — `open(info["path"], "rb").read()` lê arquivo físico em `docs/` | FLOWING |
| `app/webhook.py` `_is_duplicate_message` | `result` | `r.set(key, "1", nx=True, ex=...)` | Sim — SET NX retorna None se já existia (duplicata) ou True se criou | FLOWING |

### Behavioral Spot-Checks

| Behavior | Comando | Resultado | Status |
|----------|---------|-----------|--------|
| Suite completa de testes passa | `python -m pytest tests/ -q` | 255 passed, 1 warning | PASS |
| Módulo pii_sanitizer importável | Coberto pelo pytest (test_pii_sanitizer.py importa e usa as funções) | 13 testes passam | PASS |
| media_store.py tem todas as 5 chaves | `test_media_store_has_all_keys` no pytest | PASS (confirmado pelo teste dedicado) | PASS |
| Sem placeholders [PDF:] ou [IMG:] em atendimento.py | grep retorna zero matches | Confirmado acima | PASS |

### Requirements Coverage

| Requirement | Plano | Descrição | Status | Evidência |
|-------------|-------|-----------|--------|-----------|
| META-01 | 04-03 | LGPD — pseudonimização antes do LLM | SATISFIED | `sanitize_historico` integrado em `_gerar_resposta_llm`; CPF/tel/email mascarados |
| META-02 | 04-01, 04-02 | MetaAPIClient sem args + envio de mídia | SATISFIED | Args opcionais com env fallback; upload_media/send_document/send_image implementados |
| META-03 | 04-02 | Envio de mídia real (PDF, imagens) | SATISFIED | `_enviar_midia` + `_get_or_upload_media` + `MEDIA_STATIC` com 5 arquivos |
| META-04 | 04-01, 04-03 | Dedup Redis + PII protection | SATISFIED | Redis SET NX TTL 4h + sanitizador PII com 6 padrões regex |

### Anti-Patterns Found

| Arquivo | Linha | Padrão | Severidade | Impacto |
|---------|-------|--------|------------|---------|
| `app/ai_engine.py` | 6 | `FutureWarning: google.generativeai deprecated` | Info | Aviso de deprecação de SDK Google — não é da Fase 4; não afeta funcionalidade atual |

Nenhum anti-padrão bloqueador identificado nos arquivos da Fase 4. Sem TODOs, placeholders, ou implementações vazias.

### Human Verification Required

Os checks automatizados passaram completamente. Os itens abaixo requerem ambiente real:

#### 1. Deduplicação em Produção

**Test:** Acionar envio da mesma mensagem via API da Meta duas vezes com o mesmo `message_id` (simular reenvio por timeout da Meta)
**Expected:** Apenas uma execução de `route_message`; log exibe `"Dedup Redis: mensagem X ja processada, ignorando"`
**Why human:** Requer Redis ativo e Meta Cloud API real para simular condição de race condition; não reproduzível em unit tests sem mock de timing

#### 2. Sanitização PII em Fluxo Completo

**Test:** Conversa real onde paciente digita CPF ("meu CPF e 123.456.789-09") e verifica logs de chamada à Anthropic
**Expected:** Logs de `_gerar_resposta_llm` mostram `[CPF]` no histórico enviado ao LLM; `self.historico` interno preserva CPF original
**Why human:** Requer sessão ativa com API Anthropic para inspecionar payload enviado; testes unitários cobrem a função isolada mas não o fluxo completo

#### 3. Entrega de Mídia Real

**Test:** Paciente avança até etapa de confirmação de consulta online; verificar no WhatsApp que recebe imagem JPG e PDF como arquivos reais
**Expected:** Mensagem com tipo `document`/`image` entregue, não texto `[PDF: ...]`
**Why human:** Requer número WhatsApp ativo, credenciais Meta Cloud API reais e conta Dietbox; não testável sem infra completa

---

## Resumo dos Gaps

Nenhum gap técnico identificado. Todos os 4 Success Criteria do roadmap estão implementados, testados e conectados corretamente. 255 testes passam.

Os itens de verificação humana são para validar comportamento end-to-end com infraestrutura real — são esperados nesta fase de desenvolvimento e não indicam falhas de implementação.

---

_Verified: 2026-04-15_
_Verifier: Claude (gsd-verifier)_
