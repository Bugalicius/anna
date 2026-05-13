#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/remarketing_report.py

Gera relatório de remarketing em 3 categorias:
  1. Leads frios        — entraram em contato mas não demonstraram interesse
  2. Quase marcaram     — perguntaram valor/horário mas não converteram
  3. Ex-pacientes       — já foram pacientes mas pararam o acompanhamento

Regra de exclusão: contatos com 2+ mensagens de remarketing já enviadas ficam
fora da lista (marcados como "remarketing_concluido").

Uso:
  python scripts/remarketing_report.py
  python scripts/remarketing_report.py --output relatorio_remarketing.json
"""

from __future__ import annotations

import json
import sys
import re
import argparse
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT    = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

EXPORT_FILE     = ROOT / "conversas_export.json"
CHECKPOINT_FILE = SCRIPTS / "checkpoint.json"

# ── Identificadores do remarketing já enviado ─────────────────────────────────
REMARKETING_MARKERS = [
    "Parabéns pelo seu mês",
    "Parabens pelo seu mes",
]

# ── Keywords para classificação ───────────────────────────────────────────────
AGENDAMENTO_KW = [
    "agendar", "agendamento", "marcar", "consulta", "horário", "horario",
    "disponível", "disponivel", "atende", "quanto custa", "valor", "preço",
    "preco", "planos", "midia kit", "mídia kit", "pacote", "presencial",
    "online", "quero", "interesse", "informação", "informacao",
]

CONVERTEU_KW = [
    "pagamento confirmado", "comprovante", "pix enviado", "transferi",
    "paguei", "sua vaga está garantida", "vaga garantida", "agendado",
    "confirmado", "cadastro finalizado", "dados para o formulário",
    "bem-vinda ao programa", "bem vinda", "primeira consulta agendada",
    "retorno agendado",
]

EX_PACIENTE_KW = [
    "retorno", "já sou paciente", "ja sou paciente", "fiz consulta",
    "fiz acompanhamento", "era paciente", "minha dieta", "meu plano",
    "minha consulta anterior", "última consulta", "ultima consulta",
    "quero voltar", "parei", "precisei parar", "problemas financeiros",
    "remarcar", "remarcação", "cancelei", "cancelar",
]


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _digits(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _normalize(phone: str) -> str:
    d = _digits(phone)
    if d.startswith("55") and len(d) in (12, 13):
        return d
    if len(d) in (10, 11):
        return "55" + d
    return d


def _has_keyword(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(kw in t for kw in keywords)


def extract_phone(conv: dict) -> str | None:
    chat = conv.get("chat", {})
    jid = chat.get("remoteJid", "")
    if jid.endswith("@s.whatsapp.net"):
        return _normalize(jid.replace("@s.whatsapp.net", ""))
    alt = chat.get("lastMessage", {}).get("key", {}).get("remoteJidAlt", "")
    if alt.endswith("@s.whatsapp.net"):
        return _normalize(alt.replace("@s.whatsapp.net", ""))
    for msg in conv.get("messages", [])[:5]:
        raw = msg.get("raw", {}).get("key", {}).get("remoteJidAlt", "")
        if raw.endswith("@s.whatsapp.net"):
            return _normalize(raw.replace("@s.whatsapp.net", ""))
    return None


def extract_name(conv: dict) -> str:
    chat = conv.get("chat", {})
    push = chat.get("pushName", "")
    if push and len(push) > 1:
        return push
    for msg in conv.get("messages", []):
        pn = msg.get("pushName", "")
        if pn and len(pn) > 1:
            return pn
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# Análise de conversa
# ══════════════════════════════════════════════════════════════════════════════

def analyze_conv(conv: dict) -> dict:
    """Retorna métricas da conversa para classificação."""
    messages = conv.get("messages", [])

    remarketing_sent = 0
    patient_msgs = []
    bot_msgs = []

    for msg in messages:
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        if msg.get("fromMe"):
            bot_msgs.append(text)
            for marker in REMARKETING_MARKERS:
                if marker.lower() in text.lower():
                    remarketing_sent += 1
        else:
            patient_msgs.append(text)

    all_patient_text = " ".join(patient_msgs).lower()
    all_bot_text = " ".join(bot_msgs).lower()
    all_text = (all_patient_text + " " + all_bot_text).lower()

    interest = _has_keyword(all_patient_text, AGENDAMENTO_KW)
    converted = _has_keyword(all_bot_text, CONVERTEU_KW) or _has_keyword(all_text, ["pagamento confirmado", "vaga garantida", "primeira consulta"])
    ex_patient = _has_keyword(all_patient_text, EX_PACIENTE_KW) or _has_keyword(all_bot_text, EX_PACIENTE_KW)

    return {
        "remarketing_sent": remarketing_sent,
        "patient_msg_count": len(patient_msgs),
        "bot_msg_count": len(bot_msgs),
        "showed_interest": interest,
        "converted": converted,
        "ex_patient_signals": ex_patient,
        "last_patient_msg": patient_msgs[-1][:120] if patient_msgs else "",
        "last_bot_msg": bot_msgs[-1][:120] if bot_msgs else "",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Classificação
# ══════════════════════════════════════════════════════════════════════════════

def classify(analysis: dict, conv_count: int) -> str:
    """
    Retorna categoria:
      - remarketing_concluido
      - ex_paciente
      - quase_marcou
      - lead_frio
    """
    if analysis["remarketing_sent"] >= 2:
        return "remarketing_concluido"

    if analysis["converted"] or analysis["ex_patient_signals"]:
        return "ex_paciente"

    if analysis["showed_interest"] and analysis["patient_msg_count"] >= 2:
        return "quase_marcou"

    return "lead_frio"


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="scripts/relatorio_remarketing.json")
    args = parser.parse_args()

    print(f"Carregando {EXPORT_FILE} ...")
    with open(EXPORT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    convs = data.get("conversations", [])
    print(f"  {len(convs)} conversas encontradas")

    # Carrega checkpoint para cruzar nomes
    checkpoint = {}
    if CHECKPOINT_FILE.exists():
        try:
            checkpoint = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    print(f"  {len(checkpoint)} contatos no checkpoint")

    # Agrupa conversas por telefone (pode haver múltiplas)
    by_phone: dict[str, list[dict]] = defaultdict(list)
    phone_name: dict[str, str] = {}

    BLOCKED = {"5531991394759", "5531992059211"}

    for conv in convs:
        if "@g.us" in conv.get("chat", {}).get("remoteJid", ""):
            continue
        phone = extract_phone(conv)
        if not phone or phone in BLOCKED:
            continue
        by_phone[phone].append(conv)
        if phone not in phone_name:
            phone_name[phone] = extract_name(conv)

    print(f"  {len(by_phone)} contatos únicos")

    # Classifica cada contato
    results: dict[str, list] = {
        "lead_frio":             [],
        "quase_marcou":          [],
        "ex_paciente":           [],
        "remarketing_concluido": [],
    }

    for phone, phone_convs in by_phone.items():
        # Agrega análise de todas as conversas do contato
        total_remarketing = 0
        total_patient_msgs = 0
        showed_interest = False
        converted = False
        ex_patient = False
        last_msg = ""

        for conv in phone_convs:
            a = analyze_conv(conv)
            total_remarketing += a["remarketing_sent"]
            total_patient_msgs += a["patient_msg_count"]
            showed_interest = showed_interest or a["showed_interest"]
            converted = converted or a["converted"]
            ex_patient = ex_patient or a["ex_patient_signals"]
            if a["last_patient_msg"]:
                last_msg = a["last_patient_msg"]

        agg = {
            "remarketing_sent": total_remarketing,
            "patient_msg_count": total_patient_msgs,
            "bot_msg_count": 0,
            "showed_interest": showed_interest,
            "converted": converted,
            "ex_patient_signals": ex_patient,
            "last_patient_msg": last_msg,
            "last_bot_msg": "",
        }
        category = classify(agg, len(phone_convs))

        # Nome: prioriza checkpoint, depois pushName do histórico
        cp = checkpoint.get(phone, {})
        cp_variants = [_normalize(k) for k in checkpoint.keys()]
        cp_name = cp.get("name", "") if cp else ""

        # Tenta variante com/sem 9
        if not cp_name:
            for k, v in checkpoint.items():
                if _normalize(k) == phone:
                    cp_name = v.get("name", "")
                    break

        name = cp_name or phone_name.get(phone, "")

        entry = {
            "nome": name or "Sem nome",
            "numero": f"+{phone}",
            "remarketing_enviados": total_remarketing,
            "mensagens_paciente": total_patient_msgs,
            "conversas": len(phone_convs),
            "ultima_mensagem": last_msg,
        }
        results[category].append(entry)

    # Ordena cada categoria por nome
    for cat in results:
        results[cat].sort(key=lambda x: x["nome"].lower())

    # Resumo
    print()
    print("=" * 60)
    print("RESUMO DO RELATÓRIO DE REMARKETING")
    print("=" * 60)
    print(f"  Leads frios             : {len(results['lead_frio'])}")
    print(f"  Quase marcaram          : {len(results['quase_marcou'])}")
    print(f"  Ex-pacientes            : {len(results['ex_paciente'])}")
    print(f"  Remarketing concluído   : {len(results['remarketing_concluido'])}")
    total_ativos = len(results['lead_frio']) + len(results['quase_marcou']) + len(results['ex_paciente'])
    print(f"  ─────────────────────────")
    print(f"  Total para abordar      : {total_ativos}")
    print()

    # Grava JSON
    output = {
        "resumo": {
            "lead_frio": len(results["lead_frio"]),
            "quase_marcou": len(results["quase_marcou"]),
            "ex_paciente": len(results["ex_paciente"]),
            "remarketing_concluido": len(results["remarketing_concluido"]),
        },
        "lead_frio": results["lead_frio"],
        "quase_marcou": results["quase_marcou"],
        "ex_paciente": results["ex_paciente"],
        "remarketing_concluido": results["remarketing_concluido"],
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório salvo em: {out_path}")
    print()

    # Preview de cada categoria
    for cat, label in [
        ("lead_frio", "LEADS FRIOS"),
        ("quase_marcou", "QUASE MARCARAM"),
        ("ex_paciente", "EX-PACIENTES"),
    ]:
        print(f"--- {label} (primeiros 10) ---")
        for e in results[cat][:10]:
            print(f"  {e['numero']} | {e['nome']} | msgs={e['mensagens_paciente']} | rmkt={e['remarketing_enviados']}")
        print()


if __name__ == "__main__":
    main()
