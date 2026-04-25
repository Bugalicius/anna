#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Runner — Simples, sem print direto (evita encoding issues).
Salva tudo em arquivo.
"""

import requests
import json
from datetime import datetime
import io

BASE_URL = "http://localhost:8000"
CHAT_URL = f"{BASE_URL}/test/chat"
RESET_URL = f"{BASE_URL}/test/reset"

def test(name, phone, msgs, output_file):
    """Roda um teste, escreve resultado no arquivo."""
    output_file.write(f"\n{'='*70}\n")
    output_file.write(f"TEST: {name}\n")
    output_file.write(f"{'='*70}\n")

    # Reset
    try:
        r = requests.post(RESET_URL, json={"phone": phone}, timeout=5)
        if r.status_code != 200:
            output_file.write(f"FAIL: Reset error {r.status_code}\n")
            return False
    except Exception as e:
        output_file.write(f"FAIL: Reset exception {e}\n")
        return False

    # Send messages
    try:
        for msg in msgs:
            output_file.write(f"\nPACIENTE: {msg}\n")
            r = requests.post(CHAT_URL, json={"phone": phone, "message": msg}, timeout=10)

            if r.status_code != 200:
                output_file.write(f"HTTP ERROR: {r.status_code}\n")
                return False

            data = r.json()
            if "error" in data:
                output_file.write(f"API ERROR: {data['error']}\n")
                return False

            resps = data.get("responses", [])
            if resps:
                for i, resp in enumerate(resps, 1):
                    if isinstance(resp, str):
                        output_file.write(f"  [{i}] TEXT: {resp[:100]}...\n" if len(resp) > 100 else f"  [{i}] TEXT: {resp}\n")
                    elif isinstance(resp, dict):
                        if resp.get("_interactive"):
                            output_file.write(f"  [{i}] INTERACTIVE: {resp.get('ask_context', 'action')}\n")
                        elif resp.get("media_type"):
                            output_file.write(f"  [{i}] MEDIA: {resp.get('media_key')}\n")
                        elif resp.get("_meta_action"):
                            output_file.write(f"  [{i}] ACTION: {resp.get('_meta_action')}\n")
                        else:
                            output_file.write(f"  [{i}] OBJECT: {str(resp)[:100]}\n")
            else:
                output_file.write("  (no response)\n")

        output_file.write("\n[PASS]\n")
        return True

    except Exception as e:
        output_file.write(f"\nEXCEPTION: {e}\n")
        return False

# Tests
tests = [
    ("T08: Desistir na 1a msg", "5531990008", [
        "Desisto, nao quero mais",
    ]),
    ("T01: Trocar plano mid-flow", "5531990001", [
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
        "Deixa pra la, nao quero mais",
        "Oi",
    ]),
    ("T10: Desistir no pagamento", "5531990010", [
        "Oi, Pedro Costa",
        "Sou novo",
        "Quero ganhar massa",
        "Ouro",
        "Nao, ouro mesmo",
        "Presencial",
        "Terca de manha",
        "1",
        "PIX",
        "Desisto",
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
    ("T18: Pagar no consultorio", "5531990018", [
        "Oi, Carlos Santos",
        "Novo",
        "Emagrecer",
        "Premium",
        "Online",
        "Segunda manha",
        "1",
        "Posso acertar no consultorio depois?",
    ]),
    ("T26: Mensagem aleatoria mid-flow", "5531990026", [
        "Oi, Rafael Mendes",
        "Novo",
        "Emagrecer",
        "Quanto custa o dolar hoje?",
    ]),
    ("T27: Pergunta preco sem nome", "5531990027", [
        "Qual o preco do plano ouro?",
    ]),
]

# Run tests
timestamp = datetime.now().isoformat().replace(":", "-")
results_file = f"TEST_RESULTS_{timestamp}.txt"

with open(results_file, "w", encoding="utf-8") as f:
    f.write(f"TEST RESULTS\n")
    f.write(f"Generated: {datetime.now()}\n")
    f.write(f"Total tests: {len(tests)}\n")

    passed = 0
    for name, phone, msgs in tests:
        try:
            if test(name, phone, msgs, f):
                passed += 1
        except Exception as e:
            f.write(f"\nUNCAPTURED EXCEPTION: {e}\n")

    f.write(f"\n{'='*70}\n")
    f.write(f"SUMMARY\n")
    f.write(f"{'='*70}\n")
    f.write(f"Passed: {passed}/{len(tests)}\n")
    f.write(f"Failed: {len(tests)-passed}/{len(tests)}\n")
    f.write(f"Rate: {passed*100//len(tests)}%\n")

print(f"Results saved to: {results_file}")
print(f"Passed: {passed}/{len(tests)} ({passed*100//len(tests)}%)")
