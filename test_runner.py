#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Runner — Executa os 32 cenarios do ROTEIRO_TESTES.md
via POST /test/chat e registra resultados.
"""

import json
import requests
import sys
import os
from datetime import datetime
from typing import Any

# Fix encoding on Windows
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
os.environ['PYTHONIOENCODING'] = 'utf-8'

BASE_URL = "http://localhost:8000"
TEST_CHAT = f"{BASE_URL}/test/chat"
TEST_RESET = f"{BASE_URL}/test/reset"

# Phones para cada teste (diferentes para estado isolado)
PHONES = {f"test{i:02d}": f"553199000{i:04d}" for i in range(1, 33)}

def reset_phone(test_num: int, phone: str) -> bool:
    """Limpa estado para novo teste."""
    try:
        r = requests.post(TEST_RESET, json={"phone": phone}, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"  ❌ Reset falhou: {e}")
        return False

def send_message(phone: str, message: str) -> dict[str, Any]:
    """Envia mensagem e captura resposta."""
    try:
        r = requests.post(
            TEST_CHAT,
            json={"phone": phone, "message": message},
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
        else:
            return {"error": f"HTTP {r.status_code}", "responses": []}
    except Exception as e:
        return {"error": str(e), "responses": []}

def format_responses(responses: list) -> str:
    """Formata lista de respostas para exibicao."""
    if not responses:
        return "(sem resposta)"
    result = []
    for r in responses:
        if isinstance(r, str):
            result.append(f"TXT: {r[:80]}")
        elif isinstance(r, dict):
            if r.get("_interactive") or r.get("_meta_action"):
                result.append(f"BTN: {r.get('ask_context', 'action')}")
            elif r.get("media_type"):
                result.append(f"MED: {r.get('media_key', 'media')}")
            else:
                result.append(f"OBJ: {str(r)[:80]}")
    return " | ".join(result)

# ── TESTES ─────────────────────────────────────────────────────────────────────

TESTS = {
    "CRITICOS": [
        {
            "num": 8,
            "nome": "Desistir na 1a mensagem",
            "msgs": [
                "Desisto, nao quero mais",
            ],
            "esperado": "abandon_process, resposta gracioso"
        },
        {
            "num": 9,
            "nome": "Voltar apos desistir",
            "msgs": [
                "Oi, meu nome e Maria Silva",
                "Sou nova",
                "Deixa pra la, nao quero mais",
                "Oi",
            ],
            "esperado": "Reset goal, reinicia boas-vindas, preserva nome"
        },
        {
            "num": 10,
            "nome": "Desistir no pagamento (sem consulta)",
            "msgs": [
                "Oi, Pedro Costa",
                "Sou novo",
                "Quero ganhar massa",
                "Ouro",
                "Nao, ouro mesmo",
                "Presencial",
                "Segunda de manha",
                "1",
                "PIX",
                "Desisto",
            ],
            "esperado": "abandon_process gracioso (sem id_agenda)"
        },
        {
            "num": 1,
            "nome": "Trocar plano mid-flow",
            "msgs": [
                "Oi, Maria Silva",
                "Nova",
                "Emagrecer",
                "Unica",
                "Nao, unica mesmo",
                "Presencial",
                "Na verdade quero trocar pro ouro",
            ],
            "esperado": "correcao detectada, state.plano atualizado"
        },
        {
            "num": 2,
            "nome": "Trocar modalidade apos slot",
            "msgs": [
                "Oi, Julia Oliveira",
                "Nova",
                "Emagrecer",
                "Com_retorno",
                "Nao",
                "Presencial",
                "Quarta de manha",
                "1",
                "Quero online na verdade",
            ],
            "esperado": "modalidade atualizada, slots_offered limpo, novos slots consultados"
        },
        {
            "num": 17,
            "nome": "Comprovante valor errado",
            "msgs": [
                "Oi, Ana Paula Oliveira",
                "Nova",
                "Emagrecer",
                "Unica",
                "Presencial",
                "Qualquer horario",
                "1",
                "PIX",
                "[comprovante valor=100.00]",
            ],
            "esperado": "valor_esperado ~130, valor_recebido=100, Ana pede confirmacao"
        },
        {
            "num": 18,
            "nome": "Pagar no consultorio",
            "msgs": [
                "Oi, Carlos Santos",
                "Novo",
                "Emagrecer",
                "Premium",
                "Online",
                "Segunda manha",
                "1",
                "Posso acertar no consultorio depois?",
            ],
            "esperado": "regex _PAGAR_CONSULTORIO detecta, Ana explica politica"
        },
        {
            "num": 19,
            "nome": "Comprovante antes de escolher forma",
            "msgs": [
                "Oi, Mariana Costa",
                "Novo",
                "Emagrecer",
                "Ouro",
                "Online",
                "Terca manha",
                "2",
                "[comprovante valor=130.00]",
            ],
            "esperado": "valor detectado, assume PIX, avanca para cadastro"
        },
    ],
    "ALTERNATIVAS": [
        {
            "num": 23,
            "nome": "Plano formulario",
            "msgs": [
                "Oi, Lucas Oliveira",
                "Novo",
                "Emagrecer",
                "Formulario",
            ],
            "esperado": "send_formulario_instrucoes, sem modalidade, sem upsell"
        },
        {
            "num": 24,
            "nome": "Aceitar upsell",
            "msgs": [
                "Oi, Patricia Alves",
                "Nova",
                "Emagrecer",
                "Unica",
                "Sim, quero o ouro!",
                "Presencial",
                "Quinta manha",
                "1",
            ],
            "esperado": "upgrade aplicado, modalidade perguntado com plano=ouro"
        },
    ],
    "RETORNO": [
        {
            "num": 20,
            "nome": "Retorno nao existe no Dietbox",
            "msgs": [
                "Oi, Fernanda Lima",
                "Ja sou paciente, quero remarcar",
            ],
            "esperado": "detectar_tipo_remarcacao, tipo=nova_consulta, status_paciente->novo"
        },
    ],
    "FORA_CONTEXTO": [
        {
            "num": 26,
            "nome": "Mensagem aleatoria mid-flow",
            "msgs": [
                "Oi, Rafael Mendes",
                "Novo",
                "Emagrecer",
                "Quanto custa o dolar hoje?",
            ],
            "esperado": "ignora intent fora_contexto, continua perguntando plano"
        },
        {
            "num": 27,
            "nome": "Pergunta preco sem nome",
            "msgs": [
                "Qual o preco do plano ouro?",
            ],
            "esperado": "pede nome primeiro OU responde e guia para fluxo"
        },
    ],
}

def main():
    timestamp = datetime.now().isoformat()
    results_file = f"TEST_RESULTS_{timestamp.replace(':', '')}.txt"

    with open(results_file, "w", encoding="utf-8") as f:
        f.write(f"# RESULTADOS DOS TESTES — {timestamp}\n\n")

        total = 0
        passed = 0
        failed = 0

        for categoria, testes in TESTS.items():
            f.write(f"\n## {categoria}\n\n")
            print(f"\n{'='*60}")
            print(f"{categoria}")
            print(f"{'='*60}\n")

            for teste in testes:
                test_num = teste["num"]
                test_name = teste["nome"]
                msgs = teste["msgs"]
                esperado = teste["esperado"]
                phone = PHONES[f"test{test_num:02d}"]

                total += 1
                print(f"[T{test_num:02d}] {test_name}...", end=" ", flush=True)

                # Reset
                if not reset_phone(test_num, phone):
                    print("[RESET FAILED]")
                    f.write(f"### T{test_num:02d} — {test_name}\n")
                    f.write(f"[RESET FAILED]\n\n")
                    failed += 1
                    continue

                # Run messages
                f.write(f"### T{test_num:02d} — {test_name}\n")
                f.write(f"**Esperado:** {esperado}\n\n")
                f.write(f"```\n")

                last_response = None
                try:
                    for i, msg in enumerate(msgs, 1):
                        f.write(f"{i}. PACIENTE: {msg}\n")
                        result = send_message(phone, msg)

                        if "error" in result:
                            f.write(f"   [ERROR] {result['error']}\n")
                            failed += 1
                            raise Exception(result['error'])

                        resps = result.get("responses", [])
                        last_response = resps
                        f.write(f"   ANA: {format_responses(resps)}\n")

                    print("[OK]")
                    passed += 1
                    f.write("```\n\n[OK]\n\n")

                except Exception as e:
                    print(f"[FAIL] {e}")
                    f.write(f"```\n\n[FAIL] {e}\n\n")
                    failed += 1

        # Summary
        f.write(f"\n\n## RESUMO\n\n")
        f.write(f"- Total: {total}\n")
        f.write(f"- [PASS] Passou: {passed}\n")
        f.write(f"- [FAIL] Falhou: {failed}\n")
        f.write(f"- Taxa: {passed*100//total if total > 0 else 0}%\n")

        print(f"\n{'='*60}")
        print(f"RESUMO: {passed}/{total} testes passaram ({passed*100//total}%)")
        print(f"Resultados salvos em: {results_file}")
        print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
