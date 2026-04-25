#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Test Runner — Testa 5 cenarios criticos rapidamente.
"""

import requests
import json

BASE_URL = "http://localhost:8000"
CHAT_URL = f"{BASE_URL}/test/chat"
RESET_URL = f"{BASE_URL}/test/reset"

def test(name, phone, msgs):
    """Roda um teste."""
    print(f"\n[TEST] {name}")
    print("-" * 60)

    # Reset
    r = requests.post(RESET_URL, json={"phone": phone}, timeout=5)
    if r.status_code != 200:
        print(f"FAIL: Reset error {r.status_code}")
        return False

    # Send messages
    for msg in msgs:
        print(f"  > {msg}")
        r = requests.post(CHAT_URL, json={"phone": phone, "message": msg}, timeout=10)
        if r.status_code != 200:
            print(f"  ERROR: {r.status_code}")
            return False

        data = r.json()
        resps = data.get("responses", [])
        if resps:
            for resp in resps:
                if isinstance(resp, str):
                    text = resp[:80] if len(resp) > 80 else resp
                    print(f"  < {text}")
                elif isinstance(resp, dict):
                    if resp.get("_interactive"):
                        print(f"  < [BTN] {resp.get('ask_context', 'action')}")
                    elif resp.get("media_type"):
                        print(f"  < [MEDIA] {resp.get('media_key')}")
                    elif resp.get("_meta_action"):
                        print(f"  < [ACTION] {resp.get('_meta_action')}")

    print("[PASS]")
    return True

# Tests
tests = [
    ("T08: Desistir 1a msg", "5531990008", [
        "Desisto, nao quero mais",
    ]),
    ("T01: Trocar plano", "5531990001", [
        "Oi, Maria Silva",
        "Nova",
        "Emagrecer",
        "Unica",
        "Nao, unica mesmo",
        "Presencial",
        "Na verdade quero trocar pro ouro",
    ]),
    ("T09: Voltar apos desistir", "5531990009", [
        "Oi, Maria Silva",
        "Sou nova",
        "Deixa pra la",
        "Oi",
    ]),
    ("T17: Comprovante valor errado", "5531990017", [
        "Oi, Ana Paula Oliveira",
        "Nova",
        "Emagrecer",
        "Unica",
        "Presencial",
        "Qualquer horario",
        "1",
        "PIX",
        "[comprovante valor=100.00]",
    ]),
    ("T26: Mensagem aleatoria mid-flow", "5531990026", [
        "Oi, Rafael Mendes",
        "Novo",
        "Emagrecer",
        "Quanto custa o dolar hoje?",
    ]),
]

passed = 0
for name, phone, msgs in tests:
    try:
        if test(name, phone, msgs):
            passed += 1
    except Exception as e:
        print(f"EXCEPTION: {e}")

print(f"\n{'='*60}")
print(f"RESULTADO: {passed}/{len(tests)} testes passaram")
print(f"{'='*60}")
