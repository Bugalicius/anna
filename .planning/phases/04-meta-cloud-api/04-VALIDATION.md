---
phase: 4
slug: meta-cloud-api
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-15
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.2 + pytest-asyncio 0.24.0 |
| **Config file** | `tests/conftest.py` (existente) |
| **Quick run command** | `python -m pytest tests/test_webhook.py tests/test_meta_api.py -q` |
| **Full suite command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_webhook.py tests/test_meta_api.py -q`
- **After every plan wave:** Run `python -m pytest tests/ -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 4-01-01 | 01 | 0 | META-04 | T-dedup | Redis SET NX bloqueia duplicata | unit | `python -m pytest tests/test_webhook.py -q` | ❌ W0 | ⬜ pending |
| 4-01-02 | 01 | 1 | META-04 | T-dedup | Primeira ocorrência é processada | unit | `python -m pytest tests/test_webhook.py -q` | ❌ W0 | ⬜ pending |
| 4-01-03 | 01 | 1 | META-04 | T-dedup | Graceful degradation se Redis cair | unit | `python -m pytest tests/test_webhook.py -q` | ❌ W0 | ⬜ pending |
| 4-02-01 | 02 | 0 | META-03 | — | upload_media retorna media_id | unit | `python -m pytest tests/test_meta_api.py -q` | ❌ W0 | ⬜ pending |
| 4-02-02 | 02 | 0 | META-03 | — | send_document envia payload correto com media_id | unit | `python -m pytest tests/test_meta_api.py -q` | ❌ W0 | ⬜ pending |
| 4-02-03 | 02 | 0 | META-03 | — | send_image envia payload correto com media_id | unit | `python -m pytest tests/test_meta_api.py -q` | ❌ W0 | ⬜ pending |
| 4-02-04 | 02 | 1 | META-02 | T-instancia | MetaAPIClient() sem args lê env vars (não quebra) | unit | `python -m pytest tests/test_meta_api.py -q` | ❌ W0 | ⬜ pending |
| 4-02-05 | 02 | 1 | META-03 | — | atendimento._etapa_confirmacao envia arquivo real, não placeholder | unit | `python -m pytest tests/test_atendimento.py -q` | ✅ (parcial) | ⬜ pending |
| 4-03-01 | 03 | 0 | META-04 | T-pii | sanitize_message mascara CPF | unit | `python -m pytest tests/test_pii_sanitizer.py -q` | ❌ W0 | ⬜ pending |
| 4-03-02 | 03 | 0 | META-04 | T-pii | sanitize_message mascara telefone BR | unit | `python -m pytest tests/test_pii_sanitizer.py -q` | ❌ W0 | ⬜ pending |
| 4-03-03 | 03 | 0 | META-04 | T-inject | sanitize_message detecta prompt injection | unit | `python -m pytest tests/test_pii_sanitizer.py -q` | ❌ W0 | ⬜ pending |
| 4-03-04 | 03 | 1 | META-04 | T-pii | _gerar_resposta_llm usa historico sanitizado | unit | `python -m pytest tests/test_pii_sanitizer.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_pii_sanitizer.py` — stubs para META-04/LGPD: sanitize_message e sanitize_historico
- [ ] Novos testes em `tests/test_meta_api.py` — upload_media, send_document, send_image, MetaAPIClient() sem args
- [ ] Novos testes em `tests/test_webhook.py` — dedup Redis SET NX, graceful degradation

*Infraestrutura pytest/respx já existente — apenas novos arquivos/stubs necessários.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Arquivo PDF real chega ao paciente no WhatsApp | META-03 | Requer conexão real à Meta Cloud API e número de teste | Enviar mensagem de teste que dispara `_etapa_confirmacao`; verificar no WhatsApp que PDF aparece como documento, não texto |
| Webhook rejeita requisição forjada (sem HMAC) | META-01 | Já testado em unit, mas confirmar em staging | `curl -X POST /webhook` sem header `X-Hub-Signature-256` → esperar 403 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
