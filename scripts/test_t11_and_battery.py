"""
Script de teste: T11 relay Breno + cenários T01/T02/T08/T09/T10/T17/T18/T19.

Execução:
    python scripts/test_t11_and_battery.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Força UTF-8 no stdout para não quebrar com emojis no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# ── Banco SQLite isolado ──────────────────────────────────────────────────────
_DB_PATH = ROOT / "test_t11_battery.db"
if _DB_PATH.exists():
    _DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
os.environ["DISABLE_LLM_FOR_TESTS"] = "true"

from fastapi.testclient import TestClient

# ── Slots fake ────────────────────────────────────────────────────────────────

def _slot(day, date_fmt, hour, dt):
    return {"datetime": dt, "data_fmt": f"{day}, {date_fmt}", "hora": hour}

SLOTS_PRESENCIAL = [
    _slot("segunda", "27/04", "8h",  "2026-04-27T08:00:00"),
    _slot("terca",   "28/04", "15h", "2026-04-28T15:00:00"),
    _slot("quarta",  "29/04", "19h", "2026-04-29T19:00:00"),
    _slot("quinta",  "30/04", "9h",  "2026-04-30T09:00:00"),
    _slot("sexta",   "01/05", "16h", "2026-05-01T16:00:00"),
]
SLOTS_ONLINE = [
    _slot("segunda", "27/04", "9h",  "2026-04-27T09:00:00"),
    _slot("terca",   "28/04", "16h", "2026-04-28T16:00:00"),
    _slot("quarta",  "29/04", "18h", "2026-04-29T18:00:00"),
    _slot("quinta",  "30/04", "10h", "2026-04-30T10:00:00"),
]
RETORNO_SLOTS = [
    _slot("segunda", "04/05", "8h",  "2026-05-04T08:00:00"),
    _slot("terca",   "05/05", "15h", "2026-05-05T15:00:00"),
    _slot("quarta",  "06/05", "18h", "2026-05-06T18:00:00"),
    _slot("quinta",  "07/05", "9h",  "2026-05-07T09:00:00"),
    _slot("sexta",   "08/05", "16h", "2026-05-08T16:00:00"),
]

def fake_slots(modalidade="presencial", **_):
    return list(SLOTS_ONLINE if modalidade == "online" else SLOTS_PRESENCIAL)

def fake_processar(dados_paciente, dt_consulta, modalidade, plano, valor_sinal, forma_pagamento):
    phone = dados_paciente["telefone"]
    pid = abs(hash(phone)) % 9000 + 1000
    return {"sucesso": True, "id_paciente": pid, "id_agenda": f"AGENDA-{pid}", "id_transacao": f"TRANS-{pid}"}

def fake_buscar_paciente(telefone):
    return None

def fake_agendamento_ativo(id_paciente):
    return None

def fake_lancamento(id_agenda):
    return False

def fake_alterar(id_agenda, novo_dt, obs):
    return True

def fake_cancelar(id_agenda, obs=""):
    return True

def fake_confirmar(id_transacao):
    return True

def fake_gerar_link(*a, **kw):
    from app.integrations.payment_gateway import LinkPagamento
    return LinkPagamento(url="https://pagamento.fake/checkout/abc", valor=768.0,
                         parcelas=6, parcela_valor=128.0, sucesso=True, erro=None)

async def fake_slots_remarcar(modalidade, preferencia, fim_janela, excluir=None, pool=None):
    todos = list(pool or RETORNO_SLOTS)
    excluir_set = set(excluir or [])
    return {"slots": [s for s in todos if s["datetime"] not in excluir_set][:3],
            "slots_pool": todos, "aviso_preferencia": None}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]

def _chat(client, phone, message):
    r = client.post("/test/chat", json={"phone": phone, "message": message})
    return r.json()["responses"]

def _reset(client, phone):
    client.post("/test/reset", json={"phone": phone})

def _breno_reply(client, texto, patient_phone):
    r = client.post("/test/breno-reply", json={"texto": texto, "patient_phone": patient_phone})
    return r.json()

def _sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def _turn(msg, responses):
    print(f"  Paciente: {msg}")
    for r in responses:
        print(f"  Ana:      {r}")
    print()

# ── Patches globais ───────────────────────────────────────────────────────────

PATCHES = [
    patch("app.integrations.dietbox.consultar_slots_disponiveis", side_effect=fake_slots),
    patch("app.integrations.dietbox.processar_agendamento",        side_effect=fake_processar),
    patch("app.integrations.dietbox.buscar_paciente_por_telefone", side_effect=fake_buscar_paciente),
    patch("app.integrations.dietbox.consultar_agendamento_ativo",  side_effect=fake_agendamento_ativo),
    patch("app.integrations.dietbox.verificar_lancamento_financeiro", side_effect=fake_lancamento),
    patch("app.integrations.dietbox.alterar_agendamento",          side_effect=fake_alterar),
    patch("app.integrations.dietbox.cancelar_agendamento",         side_effect=fake_cancelar),
    patch("app.integrations.dietbox.confirmar_pagamento",          side_effect=fake_confirmar),
    patch("app.integrations.payment_gateway.gerar_link_pagamento", side_effect=fake_gerar_link),
    patch("app.tools.scheduling.consultar_slots_remarcar",         side_effect=fake_slots_remarcar),
    patch("app.chatwoot_bridge.is_human_handoff_active",           return_value=False),
]

# ── Cenários ──────────────────────────────────────────────────────────────────

def run_t11(client):
    """T11 — relay Breno completo: dúvida clínica → escalação → Breno responde → paciente recebe."""
    _sep("T11 — Relay Breno (lead com dúvida clínica)")
    phone = "5500001100011"
    _reset(client, phone)

    # Passo 1: lead faz dúvida clínica
    turns = [
        "Oi",
        "Carlos Mendes, sou novo",
        "tenho diabetes e quero saber se posso comer pão integral",
    ]
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)

    # Passo 2: Breno recebe contexto e responde
    resposta_breno = "Sim, pode comer pão integral com moderação! Prefira o integral sem adição de açúcar."
    print(f"  [Breno responde]: {resposta_breno}")
    resultado = _breno_reply(client, resposta_breno, phone)

    print(f"  relay_ok: {resultado['relay_ok']}")
    print(f"  Mensagem repassada ao paciente:")
    for r in resultado["responses"]:
        print(f"    -> {r}")

    ok = resultado["relay_ok"] and len(resultado["responses"]) > 0
    status = "PASS" if ok else "FAIL"
    print(f"\n  Status: {status}")
    return status, resultado


def run_t01(client):
    """T01 — corrigir plano depois de já ter escolhido."""
    _sep("T01 — Correcao de plano mid-flow")
    phone = "5500000100001"
    _reset(client, phone)
    turns = [
        "Oi, quero agendar",
        "Ana Paula Dias, primeira consulta",
        "emagrecer",
        "consulta individual",
        "na verdade quero trocar para ouro",
        "quero manter o ouro mesmo",
        "online",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["ouro", "consulta", "modalidade", "horário"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t02(client):
    """T02 — corrigir modalidade depois de já ter escolhido."""
    _sep("T02 — Correcao de modalidade mid-flow")
    phone = "5500000200002"
    _reset(client, phone)
    turns = [
        "Quero agendar consulta",
        "Fernanda Lima, sou nova",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "na verdade quero online",
        "tarde",
        "2",
        "pix",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["online", "pix", "pagamento", "chave"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t08(client):
    """T08 — desistência no meio do agendamento."""
    _sep("T08 — Desistencia no meio do fluxo")
    phone = "5500000800008"
    _reset(client, phone)
    turns = [
        "Oi quero consulta",
        "Paula Barros, primeira vez",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "manhã",
        "deixa pra lá, desisti",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["sem problemas", "mudar de ideia", "chamar", "qualquer"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t09(client):
    """T09 — abandona e retoma depois."""
    _sep("T09 — Abandona e retoma com outra intencao")
    phone = "5500000900009"
    _reset(client, phone)
    turns = [
        "Quero consulta",
        "Gabi Torres, nova paciente",
        "emagrecer",
        "deixa pra lá",
        "na verdade quero voltar e ver os planos",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["opções", "planos", "ouro", "mídia", "mostra"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t10(client):
    """T10 — desiste na etapa de pagamento."""
    _sep("T10 — Desistencia na etapa de pagamento")
    phone = "5500001000010"
    _reset(client, phone)
    turns = [
        "Oi",
        "Renata Souza, primeira consulta",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "manhã",
        "1",
        "desisti, não vou pagar agora",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["sem problemas", "chamar", "qualquer", "tudo bem", "retornar"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t17(client):
    """T17 — comprovante com valor divergente."""
    _sep("T17 — Comprovante com valor divergente")
    phone = "5500001700017"
    _reset(client, phone)
    turns = [
        "Quero agendar",
        "Helena Souza, primeira consulta",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "manhã",
        "1",
        "pix",
        "[comprovante valor=100.00 favorecido=Thaynara]",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["valor", "sinal", "comprovante", "identificado", "diverge", "enviou"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t18(client):
    """T18 — paciente quer pagar no consultório."""
    _sep("T18 — Pagar no consultorio")
    phone = "5500001800018"
    _reset(client, phone)
    turns = [
        "Quero agendar",
        "Renata Braga, primeira consulta",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "manhã",
        "1",
        "quero pagar lá na hora",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["pagamento antecipado", "política", "comprovante", "pix", "cartão"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


def run_t19(client):
    """T19 — comprovante enviado antes de ser solicitado."""
    _sep("T19 — Comprovante antes de ser pedido")
    phone = "5500001900019"
    _reset(client, phone)
    turns = [
        "Oi",
        "Isabela Mota, nova paciente",
        "emagrecer",
        "ouro",
        "quero manter o ouro",
        "presencial",
        "manhã",
        "1",
        "[comprovante valor=384.00 favorecido=Thaynara]",
    ]
    all_resp = []
    for msg in turns:
        resp = _chat(client, phone, msg)
        _turn(msg, resp)
        all_resp.extend(resp)
    full = "\n".join(all_resp).lower()
    ok = any(w in full for w in ["comprovante", "confirmad", "pix", "cartão", "pagamento", "identific"])
    status = "PASS" if ok else "FAIL"
    print(f"  Status: {status}")
    return status, all_resp


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    from app.main import app
    from app.conversation import state as conv_state

    with (PATCHES[0], PATCHES[1], PATCHES[2], PATCHES[3], PATCHES[4],
          PATCHES[5], PATCHES[6], PATCHES[7], PATCHES[8], PATCHES[9], PATCHES[10]):
        with TestClient(app) as client:
            conv_state._state_mgr = None

            results = {}
            results["T11"] = run_t11(client)[0]
            results["T01"] = run_t01(client)[0]
            results["T02"] = run_t02(client)[0]
            results["T08"] = run_t08(client)[0]
            results["T09"] = run_t09(client)[0]
            results["T10"] = run_t10(client)[0]
            results["T17"] = run_t17(client)[0]
            results["T18"] = run_t18(client)[0]
            results["T19"] = run_t19(client)[0]

    _sep("RESULTADO FINAL")
    for t, s in results.items():
        icon = "✓" if s == "PASS" else "✗"
        print(f"  {icon} {t}: {s}")
    total = len(results)
    passed = sum(1 for s in results.values() if s == "PASS")
    print(f"\n  {passed}/{total} passaram")

    if _DB_PATH.exists():
        _DB_PATH.unlink()


if __name__ == "__main__":
    main()
