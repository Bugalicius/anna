---
phase: 1
slug: intelig-ncia-conversacional
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-08
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.3.2 + pytest-asyncio 0.24.0 |
| **Config file** | none — pytest runs from project root |
| **Quick run command** | `python -m pytest tests/ -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | INTL-04 | — | N/A | unit | `python -m pytest tests/test_state_manager.py -q` | ❌ W0 | ⬜ pending |
| 01-01-02 | 01 | 1 | INTL-04 | — | N/A | integration | `python -m pytest tests/test_state_manager.py -q` | ❌ W0 | ⬜ pending |
| 01-02-01 | 02 | 2 | INTL-01 | — | N/A | unit | `python -m pytest tests/test_integration.py -q` | ✅ | ⬜ pending |
| 01-02-02 | 02 | 2 | INTL-02 | — | N/A | unit | `python -m pytest tests/test_integration.py -q` | ✅ | ⬜ pending |
| 01-03-01 | 03 | 3 | INTL-03 | — | Número 31 99205-9211 nunca exposto | unit | `python -m pytest tests/test_escalation.py -q` | ❌ W0 | ⬜ pending |
| 01-03-02 | 03 | 3 | INTL-05 | — | N/A | unit | `python -m pytest tests/test_behavior_alignment.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_state_manager.py` — stubs para INTL-04 (Redis state persistence)
- [ ] `tests/test_escalation.py` — stubs para INTL-03 (escalation relay)
- [ ] `tests/test_behavior_alignment.py` — stubs para INTL-05 (tom e comportamento)

*Existing `tests/test_integration.py` and `tests/test_meta_api.py` cover partial INTL-01/INTL-02 scenarios.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Paciente muda de assunto e Ana retoma contexto | INTL-01 | Requer conversa real multi-turno via WhatsApp | Enviar sequência: pergunta preço → muda para horário → volta para preço. Verificar que contexto não resetou |
| "Um instante, por favor 💚" aparece antes de operação lenta | INTL-02 | Timing depende de latência real da API | Solicitar agendamento e verificar que mensagem de espera chega antes da resposta final |
| Número interno nunca aparece na conversa | INTL-03 | Verificação de segurança end-to-end | Fazer pergunta clínica, verificar que resposta não contém "99205-9211" |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
