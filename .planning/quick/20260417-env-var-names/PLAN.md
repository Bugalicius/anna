---
phase: quick-20260417-env-var-names
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - app/flows.py
  - app/remarketing.py
  - app/ai_engine.py
  - .env.example
autonomous: true
requirements: []
must_haves:
  truths:
    - "All MetaAPIClient instantiation sites read WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN"
    - ".env.example documents the canonical variable names that the code actually reads"
  artifacts:
    - path: "app/flows.py"
      provides: "flows.handle_flow() instantiates MetaAPIClient with correct env vars"
      contains: "WHATSAPP_PHONE_NUMBER_ID"
    - path: "app/remarketing.py"
      provides: "_dispatch_due_messages() and _check_escalation_reminders() use correct env vars"
      contains: "WHATSAPP_PHONE_NUMBER_ID"
    - path: "app/ai_engine.py"
      provides: "ai_engine response sender uses correct env vars"
      contains: "WHATSAPP_PHONE_NUMBER_ID"
    - path: ".env.example"
      provides: "Developer reference for required env var names"
      contains: "WHATSAPP_TOKEN"
  key_links:
    - from: ".env.example"
      to: "app/meta_api.py"
      via: "env var names must match what MetaAPIClient constructor reads"
      pattern: "WHATSAPP_PHONE_NUMBER_ID|WHATSAPP_TOKEN"
---

<objective>
Align all env var reads in the codebase to the canonical names already used by
`app/meta_api.py`, `app/webhook.py`, and `app/media_handler.py`.

Purpose: Three files instantiate MetaAPIClient with `META_PHONE_NUMBER_ID` and
`META_ACCESS_TOKEN`, which are never set — so the token and phone_id arrive as
empty strings and every outbound WhatsApp send silently fails. Fixing the names
unblocks all message delivery without any other code change.

Output: Four edited files. No new files. No schema changes. No dependency changes.
</objective>

<execution_context>
@/home/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md

Canonical env var names (source of truth — do NOT change these files):
- `app/meta_api.py` line 25: `os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")`
- `app/meta_api.py` line 26: `os.environ.get("WHATSAPP_TOKEN", "")`
- `app/webhook.py` lines 137-138: same names
- `app/media_handler.py` line 34: `os.environ.get("WHATSAPP_TOKEN", "")`

Files to fix (wrong names confirmed by read):
- `app/flows.py` line 52: `META_PHONE_NUMBER_ID`, line 53: `META_ACCESS_TOKEN`
- `app/remarketing.py` line 164: `META_PHONE_NUMBER_ID`, line 165: `META_ACCESS_TOKEN`
- `app/remarketing.py` line 289: `META_PHONE_NUMBER_ID`, line 290: `META_ACCESS_TOKEN`
- `app/ai_engine.py` line 154: `META_PHONE_NUMBER_ID`, line 155: `META_ACCESS_TOKEN`
- `.env.example` line 2: `META_ACCESS_TOKEN`, line 3: `META_PHONE_NUMBER_ID`, line 5: `META_VERIFY_TOKEN`
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix env var names in app/flows.py, app/remarketing.py, and app/ai_engine.py</name>
  <files>app/flows.py, app/remarketing.py, app/ai_engine.py</files>
  <action>
In each file, replace every occurrence of `META_PHONE_NUMBER_ID` with
`WHATSAPP_PHONE_NUMBER_ID` and every occurrence of `META_ACCESS_TOKEN` with
`WHATSAPP_TOKEN`. There are exactly three locations:

1. `app/flows.py` — `handle_flow()` function, lines 52-53:
   ```python
   # Before
   phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
   access_token=os.environ.get("META_ACCESS_TOKEN", ""),

   # After
   phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
   access_token=os.environ.get("WHATSAPP_TOKEN", ""),
   ```

2. `app/remarketing.py` — `_dispatch_due_messages()`, lines 164-165:
   ```python
   # Before
   phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
   access_token=os.environ.get("META_ACCESS_TOKEN", ""),

   # After
   phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
   access_token=os.environ.get("WHATSAPP_TOKEN", ""),
   ```

3. `app/remarketing.py` — `_check_escalation_reminders()`, lines 289-290:
   same substitution as above.

4. `app/ai_engine.py` — response sender block, lines 154-155:
   same substitution as above.

Do NOT change any other lines. Do NOT rename variables, arguments, or comments.
Do NOT touch `app/meta_api.py`, `app/webhook.py`, or `app/media_handler.py` —
those are already correct and are the canonical reference.
  </action>
  <verify>
    <automated>grep -rn "META_PHONE_NUMBER_ID\|META_ACCESS_TOKEN" app/flows.py app/remarketing.py app/ai_engine.py && echo "FAIL: stale names still present" || echo "PASS: no stale names found"</automated>
  </verify>
  <done>
grep finds zero matches for META_PHONE_NUMBER_ID and META_ACCESS_TOKEN in the
three application files. The correct names WHATSAPP_PHONE_NUMBER_ID and
WHATSAPP_TOKEN appear in all three files at the locations listed above.
  </done>
</task>

<task type="auto">
  <name>Task 2: Update .env.example to document canonical variable names</name>
  <files>.env.example</files>
  <action>
In `.env.example`, update the "Meta Cloud API" section so the variable names
match what the code actually reads. Change exactly these three lines:

```
# Before
META_ACCESS_TOKEN=seu_token_aqui
META_PHONE_NUMBER_ID=seu_phone_number_id
META_APP_SECRET=seu_app_secret
META_VERIFY_TOKEN=token_webhook_verificacao

# After
WHATSAPP_TOKEN=seu_token_aqui
WHATSAPP_PHONE_NUMBER_ID=seu_phone_number_id
META_APP_SECRET=seu_app_secret
WEBHOOK_VERIFY_TOKEN=token_webhook_verificacao
```

`META_APP_SECRET` is already correct (used by `app/meta_api.py` for signature
verification) — do not change it. Only rename the three vars listed above.

Leave every other section of `.env.example` untouched.
  </action>
  <verify>
    <automated>grep -n "META_ACCESS_TOKEN\|META_PHONE_NUMBER_ID\|META_VERIFY_TOKEN" .env.example && echo "FAIL: stale names still present" || echo "PASS: .env.example updated"</automated>
  </verify>
  <done>
grep finds zero matches for META_ACCESS_TOKEN, META_PHONE_NUMBER_ID, and
META_VERIFY_TOKEN in .env.example. The file now shows WHATSAPP_TOKEN,
WHATSAPP_PHONE_NUMBER_ID, and WEBHOOK_VERIFY_TOKEN in the Meta Cloud API section.
  </done>
</task>

</tasks>

<verification>
Run both verify commands above, then confirm the canonical files are untouched:

```bash
# 1. No stale names in fixed files
grep -rn "META_PHONE_NUMBER_ID\|META_ACCESS_TOKEN" app/flows.py app/remarketing.py app/ai_engine.py .env.example

# 2. Correct names present in all fixed files
grep -rn "WHATSAPP_PHONE_NUMBER_ID" app/flows.py app/remarketing.py app/ai_engine.py
grep -rn "WHATSAPP_TOKEN" app/flows.py app/remarketing.py app/ai_engine.py

# 3. Canonical files still correct (should not have changed)
grep -n "WHATSAPP_PHONE_NUMBER_ID\|WHATSAPP_TOKEN" app/meta_api.py app/webhook.py app/media_handler.py

# 4. Existing test suite still passes
python -m pytest tests/ -q
```
</verification>

<success_criteria>
- Zero occurrences of META_PHONE_NUMBER_ID or META_ACCESS_TOKEN in
  app/flows.py, app/remarketing.py, app/ai_engine.py, and .env.example
- WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_TOKEN present in all three app files
  at every MetaAPIClient instantiation site
- .env.example Meta Cloud API section documents WHATSAPP_TOKEN,
  WHATSAPP_PHONE_NUMBER_ID, META_APP_SECRET, WEBHOOK_VERIFY_TOKEN
- python -m pytest tests/ -q passes (no regressions)
</success_criteria>

<output>
No SUMMARY.md required for quick fixes. After completing, confirm with the user
that the fix is in place and the test suite passes.
</output>
