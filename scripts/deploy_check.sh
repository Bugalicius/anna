#!/bin/bash
set -e

echo "=== PRE-DEPLOY ==="
pytest tests/test_webhook.py tests/test_router.py tests/test_conversation_engine.py tests/test_bug_fixes.py tests/test_remarcacao_humana.py -q
git status
echo "=== POS-DEPLOY (rodar no VPS) ==="
echo "curl http://localhost:8000/health"
