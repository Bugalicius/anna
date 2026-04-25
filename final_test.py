#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Final Test — Executa 5 testes criticos e mostra resultados.
"""

import requests
import json
import sys

# Handle encoding errors on Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE_URL = "http://localhost:8000"

def reset(phone):
    r = requests.post(f"{BASE_URL}/test/reset", json={"phone": phone}, timeout=5)
    return r.status_code == 200

def chat(phone, msg):
    r = requests.post(f"{BASE_URL}/test/chat", json={"phone": phone, "message": msg}, timeout=10)
    return r.json() if r.status_code == 200 else {"error": f"HTTP {r.status_code}"}

def show_response(data, label=""):
    if "error" in data:
        print(f"  ERROR: {data['error']}")
        return False
    resps = data.get("responses", [])
    if not resps:
        print(f"  (no response)")
        return False
    for resp in resps:
        if isinstance(resp, str):
            preview = resp[:70] + "..." if len(resp) > 70 else resp
            print(f"  {preview}")
        elif isinstance(resp, dict):
            if resp.get("_interactive"):
                print(f"  [BUTTON] {resp.get('ask_context')}")
            elif resp.get("_meta_action"):
                print(f"  [ACTION] {resp.get('_meta_action')}")
            elif resp.get("media_type"):
                print(f"  [MEDIA] {resp.get('media_key')}")
    return True

print("\n" + "="*70)
print("TESTE 1: Desistir na primeira mensagem")
print("="*70)
reset("5531990008")
result = chat("5531990008", "Desisto, nao quero mais")
show_response(result)
print("ESPERADO: abandon_process, resposta gracioso")

print("\n" + "="*70)
print("TESTE 2: Trocar plano mid-flow")
print("="*70)
reset("5531990001")
chat("5531990001", "Oi, Maria Silva")
chat("5531990001", "Nova")
chat("5531990001", "Emagrecer")
chat("5531990001", "Unica")
chat("5531990001", "Nao, unica mesmo")
chat("5531990001", "Presencial")
result = chat("5531990001", "Na verdade quero trocar pro ouro")
show_response(result)
print("ESPERADO: correcao detectada, modalidade continua")

print("\n" + "="*70)
print("TESTE 3: Voltar apos desistir")
print("="*70)
reset("5531990009")
chat("5531990009", "Oi, Maria")
chat("5531990009", "Sou nova")
chat("5531990009", "Deixa pra la, nao quero mais")
print("^ Paciente desistiu")
result = chat("5531990009", "Oi")
show_response(result)
print("ESPERADO: Reset goal, reinicia boas-vindas, preserva nome")

print("\n" + "="*70)
print("TESTE 4: Comprovante valor errado")
print("="*70)
reset("5531990017")
chat("5531990017", "Oi, Ana Paula Oliveira")
chat("5531990017", "Nova")
chat("5531990017", "Emagrecer")
chat("5531990017", "Unica")
chat("5531990017", "Presencial")
chat("5531990017", "Qualquer horario")
chat("5531990017", "1")
chat("5531990017", "PIX")
result = chat("5531990017", "[comprovante valor=100.00]")
show_response(result)
print("ESPERADO: valor esperado ~130, recebido 100, Ana pede confirmacao")

print("\n" + "="*70)
print("TESTE 5: Mensagem aleatoria mid-flow (fora de contexto)")
print("="*70)
reset("5531990026")
chat("5531990026", "Oi, Rafael Mendes")
chat("5531990026", "Novo")
chat("5531990026", "Emagrecer")
result = chat("5531990026", "Quanto custa o dolar hoje?")
show_response(result)
print("ESPERADO: ignora intent fora_contexto, continua perguntando plano")

print("\n" + "="*70)
print("RESUMO: Testes executados, ver outputs acima")
print("="*70 + "\n")
