---
phase: 04-meta-cloud-api
plan: "02"
subsystem: media-delivery
tags: [meta-cloud-api, media-upload, whatsapp, redis-cache, tdd]
dependency_graph:
  requires: [04-01]
  provides: [media-upload-cache, send-document, send-image, placeholder-removal]
  affects: [app/meta_api.py, app/media_store.py, app/agents/atendimento.py, app/router.py]
tech_stack:
  added: [redis.asyncio para cache de media_id]
  patterns: [upload-then-cache, media-key-catalog, dict-dispatch-in-list]
key_files:
  created:
    - app/media_store.py
  modified:
    - app/meta_api.py
    - app/agents/atendimento.py
    - app/router.py
    - tests/test_meta_api.py
decisions:
  - "Cache Redis de media_id com TTL 23h (82800s) para evitar re-upload a cada envio"
  - "Fallback gracioso quando Redis offline: upload direto sem cache, nao bloqueia entrega"
  - "Placeholder substituido por dict {media_type, media_key, caption} — compativel com list[str|dict] existente"
  - "Guia de circunferencias: usa variante mulher por padrao (pdf_guia_circunf_mulher) — homem disponivel no catalogo"
metrics:
  duration: "~20 min"
  completed_date: "2026-04-15"
  tasks_completed: 2
  files_modified: 5
---

# Phase 04 Plan 02: Envio Real de Midia via Meta Cloud API — Summary

**One-liner:** Implementa upload_media/send_document/send_image em MetaAPIClient com cache Redis 23h + substitui 4 placeholders [PDF/IMG] em atendimento.py por dicts de midia despachados por _enviar no router.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | TDD: upload_media, send_document, send_image + media_store.py | fa96d34 | tests/test_meta_api.py, app/meta_api.py, app/media_store.py |
| 2 | Substituir placeholders em atendimento.py + _enviar em router.py | 9470354 | app/agents/atendimento.py, app/router.py |

## What Was Built

### app/meta_api.py — 3 novos metodos em MetaAPIClient

- `upload_media(file_bytes, mime_type, filename) -> str` — POST multipart para `/{phone_id}/media`, retorna `media_id`
- `send_document(to, media_id, filename, caption) -> dict` — payload `type=document` com `id`, `filename`, `caption` opcional
- `send_image(to, media_id, caption) -> dict` — payload `type=image` com `id`, `caption` opcional

### app/media_store.py — Catalogo de 5 arquivos estaticos

```python
MEDIA_STATIC = {
    "pdf_thaynara":           docs/Thaynara - Nutricionista.pdf
    "img_preparo_online":     docs/COMO-SE-PREPARAR---ONLINE.jpg
    "img_preparo_presencial": docs/COMO-SE-PREPARAR---presencial.jpg
    "pdf_guia_circunf_mulher": docs/Guia - Circunferencias Corporais - Mulheres.pdf
    "pdf_guia_circunf_homem":  docs/Guia - Circunferencias Corporais - Homens.pdf
}
```

### app/agents/atendimento.py — 4 placeholders substituidos

| Antes | Depois |
|-------|--------|
| `"[PDF: Thaynara - Nutricionista.pdf]"` | `{"media_type": "document", "media_key": "pdf_thaynara", ...}` |
| `"[IMG: COMO-SE-PREPARAR---ONLINE.jpg]"` | `{"media_type": "image", "media_key": "img_preparo_online", ...}` |
| `"[PDF: Guia Circunferências Corporais]"` | `{"media_type": "document", "media_key": "pdf_guia_circunf_mulher", ...}` |
| `"[IMG: COMO-SE-PREPARAR---presencial.jpg]"` | `{"media_type": "image", "media_key": "img_preparo_presencial", ...}` |

### app/router.py — _enviar com suporte a midia

- `_enviar` agora aceita `list` (antes `list[str | None]`) e detecta dicts com `media_type`
- `_enviar_midia` resolve `media_key` -> `MEDIA_STATIC` -> `_get_or_upload_media` -> `send_document/send_image`
- `_get_or_upload_media` implementa cache Redis com chave `media_id:{sha256[:16]}` e TTL 82800s (23h)
- Falha de Redis nao bloqueia entrega: upload direto como fallback
- `_MEDIA_CACHE_TTL = 82800` como constante de modulo

## Deviations from Plan

None — plano executado exatamente como especificado.

## Test Results

```
239 passed, 1 warning in 8.28s
```

- 4 novos testes TDD (test_upload_media_returns_media_id, test_send_document_payload, test_send_image_payload, test_media_store_has_all_keys)
- 10 testes em test_meta_api.py passando
- Suite completa verde (239 testes)

## Known Stubs

Nenhum stub identificado — todos os arquivos fisicos existem em `docs/` e os metodos sao funcionais.

## Threat Surface Scan

Nenhuma nova superficie de seguranca alem do previsto no threat_model do plano:
- T-04-05 (accept): docs/ contem materiais de marketing publicos, sem PII
- T-04-06 (mitigate): cache Redis com TTL 23h implementado conforme especificado
- T-04-07 (accept): media_id falsificado causa erro 400 da Meta, nao exposicao de dados
- T-04-08 (mitigate): try/except em _get_or_upload_media; falha de upload nao bloqueia outras mensagens

## Self-Check: PASSED

- [x] app/meta_api.py existe com upload_media, send_document, send_image
- [x] app/media_store.py existe com MEDIA_STATIC e 5 chaves
- [x] app/agents/atendimento.py sem placeholders [PDF:] ou [IMG:]
- [x] app/router.py com _enviar_midia, _get_or_upload_media, _MEDIA_CACHE_TTL, send_document, send_image
- [x] Commits fa96d34 e 9470354 existem no git log
- [x] 239 testes passando
