"""
Configuração global de testes.

Define variáveis de ambiente mínimas para que módulos que leem os.environ
na inicialização não falhem em ambiente de CI/testes sem .env.
"""
from __future__ import annotations

import os

# Variáveis mínimas para os módulos FastAPI + Meta API funcionarem em teste
_FAKE_ENV = {
    "WHATSAPP_PHONE_NUMBER_ID": "123456789",
    "WHATSAPP_TOKEN": "fake-token",
    "WHATSAPP_BUSINESS_ACCOUNT_ID": "fake-account",
    "META_APP_SECRET": "fake-secret",
    "WEBHOOK_VERIFY_TOKEN": "fake-verify",
    "ANTHROPIC_API_KEY": "fake-anthropic-key",
    "GEMINI_API_KEY": "fake-gemini-key",
    "DATABASE_URL": "sqlite:///./test.db",
    "REDIS_URL": "redis://localhost:6379/0",
    "DIETBOX_EMAIL": "test@test.com",
    "DIETBOX_SENHA": "fake-senha",
    "REDE_EMAIL": "test@test.com",
    "REDE_SENHA": "fake-senha",
}

for key, value in _FAKE_ENV.items():
    os.environ.setdefault(key, value)
