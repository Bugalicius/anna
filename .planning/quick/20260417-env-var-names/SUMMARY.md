---
status: complete
phase: quick-20260417-env-var-names
plan: 01
date: 2026-04-17
commit: 8c68c6a
duration: ~5m
files_modified:
  - app/flows.py
  - app/remarketing.py
  - app/ai_engine.py
  - .env.example
---

# Quick Fix: Padronizar nomes de variáveis de ambiente — WHATSAPP_TOKEN/WHATSAPP_PHONE_NUMBER_ID

## One-liner

Renamed `META_ACCESS_TOKEN`/`META_PHONE_NUMBER_ID`/`META_VERIFY_TOKEN` to the
canonical names `WHATSAPP_TOKEN`/`WHATSAPP_PHONE_NUMBER_ID`/`WEBHOOK_VERIFY_TOKEN`
in three app files and `.env.example`, unblocking all outbound WhatsApp message delivery.

## Problem

Three files (`app/flows.py`, `app/remarketing.py`, `app/ai_engine.py`) were reading
env vars named `META_PHONE_NUMBER_ID` and `META_ACCESS_TOKEN`, which were never set.
The canonical names used by `app/meta_api.py`, `app/webhook.py`, and
`app/media_handler.py` are `WHATSAPP_PHONE_NUMBER_ID` and `WHATSAPP_TOKEN`.

Result: every outbound message sent via `flows.py`, `remarketing.py` and `ai_engine.py`
was silently delivering to an empty URL with an empty token — failing with no visible error.

## Changes

| File | Change |
|------|--------|
| `app/flows.py` | `handle_flow()`: 2 var names fixed |
| `app/remarketing.py` | `_dispatch_due_messages()`: 2 var names fixed; `_check_escalation_reminders()`: 2 var names fixed |
| `app/ai_engine.py` | `handle_ai()`: 2 var names fixed |
| `.env.example` | `META_ACCESS_TOKEN` → `WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID` → `WHATSAPP_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN` → `WEBHOOK_VERIFY_TOKEN` (META_APP_SECRET left unchanged) |

## Verification

- `grep` finds zero occurrences of stale names in all source files
- `python -m pytest tests/ -q` — 254 passed, 1 skipped, 0 failures

## Deviations

None — plan executed exactly as written.
