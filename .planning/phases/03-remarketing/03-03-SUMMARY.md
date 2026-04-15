---
phase: 03-remarketing
plan: "03"
subsystem: remarketing
tags: [remarketing, templates, send_text, send_template, tdd, graceful-degradation]
dependency_graph:
  requires: [03-02-PLAN.md]
  provides: [MSG_FOLLOWUP_constantes, _enviar_remarketing, TEMPLATES_APPROVED-flag]
  affects: [app/remarketing.py, tests/test_remarketing_templates.py, tests/test_remarketing.py]
tech_stack:
  added: []
  patterns: [TDD-RED-GREEN, graceful-degradation-templates, send_text-fallback-24h]
key_files:
  created: [tests/test_remarketing_templates.py]
  modified: [app/remarketing.py, tests/test_remarketing.py]
decisions:
  - "MSG_FOLLOWUP_* copiados exatamente de D-02/D-03/D-04 com acentos e emojis unicode"
  - "position 1 (24h) usa send_text — funciona dentro da janela de 24h da Meta"
  - "positions 2/3 (7d/30d) usam send_template apenas quando TEMPLATES_APPROVED=true"
  - "Erro 131026 (janela fechada) capturado: entry vai para failed sem crash"
  - "Templates nao aprovados: entry permanece pending para retry no proximo ciclo"
  - "TEMPLATES_APPROVED controlado por env var REMARKETING_TEMPLATES_APPROVED (false por padrao)"
  - "Guia de submissao de templates no Meta Business Manager documentado inline"
metrics:
  duration: "~20 min"
  completed: "2026-04-14"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 03 Plan 03: Textos e Logica de Envio de Remarketing Summary

**One-liner:** Constantes MSG_FOLLOWUP_* com textos exatos aprovados (D-02/D-03/D-04) e _enviar_remarketing() com canal correto por posicao — send_text para 24h, send_template para 7d/30d com graceful degradation quando templates Meta nao estao aprovados.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Constantes MSG_FOLLOWUP_* e TEMPLATE_NAMES | 10bc3ed | app/remarketing.py, tests/test_remarketing_templates.py |
| 2 | Funcao _enviar_remarketing com logica send_text/send_template | 148991c | app/remarketing.py, tests/test_remarketing.py |

## What Was Built

### app/remarketing.py

**Constantes de mensagem (fonte de verdade):**
- `MSG_FOLLOWUP_24H`: texto exato D-02 — "Eiii! 😊 Tudo bem por aí?" com acentos e emojis unicode
- `MSG_FOLLOWUP_7D`: texto exato D-03 — "Oii! Passando pra saber..." com "Às vezes", "relação"
- `MSG_FOLLOWUP_30D`: texto exato D-04 — "Eiii, última passagem por aqui!" com "adiar", "você"
- `TEMPLATE_NAMES`: dict {1: "ana_followup_24h", 2: "ana_followup_7d", 3: "ana_followup_30d"}
- `_MSG_POR_POSICAO`: dict interno {1: MSG_FOLLOWUP_24H, 2: MSG_FOLLOWUP_7D, 3: MSG_FOLLOWUP_30D}
- `TEMPLATES_APPROVED`: flag bool lido de env var `REMARKETING_TEMPLATES_APPROVED` (padrão False)

**Funcao _enviar_remarketing() (D-05, D-06):**
- position 1: chama `meta.send_text(to, text=MSG_FOLLOWUP_24H)` — funciona dentro da janela 24h
- position 1 com erro 131026 ou "re-engage": loga warning, retorna False (entry -> failed)
- positions 2/3 com TEMPLATES_APPROVED=True: chama `meta.send_template(to, template_name)`
- positions 2/3 com TEMPLATES_APPROVED=False: loga info, retorna False (entry permanece pending)

**_dispatch_from_db() atualizado:**
- Substituiu bloco `try: meta.send_template(...)` por `success = await _enviar_remarketing(...)`
- Sucesso: entry.status = "sent", incrementa remarketing_count, verifica MAX
- Falha position 1: entry.status = "failed"
- Falha positions 2/3 (sem template aprovado): entry.status permanece "pending" (retry proximo ciclo)

**Guia de submissao de templates:** comentario-bloco inline documentando os 3 templates necessarios, passos para submissao no Meta Business Manager, e comportamento enquanto nao aprovados.

### tests/test_remarketing_templates.py (novo, 16 testes)

- `TestMsgFollowupConstantes`: 6 testes verificando acentos obrigatorios, nomes de templates, ausencia do numero interno
- `TestEnviarRemarketingPosition1`: 3 testes — send_text chamado, erro 131026, outro erro
- `TestEnviarRemarketingPosition2E3`: 3 testes — send_template com flag True/False, position 3
- `TestDispatchFromDbUsaEnviarRemarketingEStatus`: 3 testes — status sent/failed/pending
- `TestTemplatesApprovedFlag`: 1 teste — False por padrao

### tests/test_remarketing.py (fix de regressao)

- `test_dispatch_envia_quando_sem_conversa_ativa`: atualizado para nova arquitetura de delegacao; agora verifica que `_enviar_remarketing` foi chamado em vez de `meta.send_template` diretamente

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Regressao em test_dispatch_envia_quando_sem_conversa_ativa**
- **Found during:** Task 2, suite completa
- **Issue:** Teste do Plan 03-02 verificava `meta.send_template.assert_called_once()` diretamente. Apos refatoracao de _dispatch_from_db para delegar para _enviar_remarketing, send_template nao e mais chamado diretamente pelo dispatch — e chamado internamente por _enviar_remarketing.
- **Fix:** Teste atualizado para verificar que `_enviar_remarketing` e chamado (via `patch("app.remarketing._enviar_remarketing")`), e que `entry.status == "sent"` apos chamada bem-sucedida. Comportamento funcional preservado.
- **Files modified:** tests/test_remarketing.py
- **Commit:** 148991c

## Verification Results

```
python -m pytest tests/test_remarketing_templates.py -x -q  -> 16 passed
python -m pytest tests/ -q                                   -> 231 passed, 1 warning
grep "99205" app/remarketing.py                              -> OK — numero interno ausente
python -c "from app.remarketing import MSG_FOLLOWUP_24H; assert 'Eiii' in MSG_FOLLOWUP_24H" -> OK
python -c "from app.remarketing import TEMPLATES_APPROVED; print(TEMPLATES_APPROVED)"        -> False
```

## Known Stubs

Nenhum stub identificado. Todos os textos e logica de envio estao implementados e testados. Os templates Meta (ana_followup_24h, ana_followup_7d, ana_followup_30d) precisam ser submetidos manualmente no Business Manager — isso nao e um stub de codigo, e uma etapa operacional documentada no guia inline.

## Threat Flags

Nenhuma nova superficie de seguranca alem do escopo do threat model do plano.

- T-03-09 (mitigado): MSG_FOLLOWUP_* nao contem dados sensiveis nem numero interno — verificado por teste e por `grep "99205" app/remarketing.py`
- T-03-10 (mitigado): Erro 131026 capturado em _enviar_remarketing — entry vai para "failed", sem retry infinito

## Self-Check: PASSED

- [x] `app/remarketing.py` — `MSG_FOLLOWUP_24H`, `MSG_FOLLOWUP_7D`, `MSG_FOLLOWUP_30D` presentes com textos corretos
- [x] `app/remarketing.py` — `TEMPLATE_NAMES`, `_MSG_POR_POSICAO`, `TEMPLATES_APPROVED` presentes
- [x] `app/remarketing.py` — `_enviar_remarketing` presente com logica position 1 vs 2/3
- [x] `app/remarketing.py` — `_dispatch_from_db` usa `_enviar_remarketing` (nao mais send_template diretamente)
- [x] `tests/test_remarketing_templates.py` — 16 testes coletados e passando
- [x] `tests/test_remarketing.py` — fix de regressao aplicado, 25 testes passando
- [x] Suite completa: 231 testes passando, 0 falhas
- [x] Commits `10bc3ed` e `148991c` confirmados
