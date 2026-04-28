from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_DIR = ROOT / "docs" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StressScenario:
    slug: str
    title: str
    turns: list[str]
    expected_any: list[str]
    profile: str = "novo"
    source_category: str = ""
    source_sample: str = ""


def _setup_env() -> Path:
    load_dotenv(ROOT / ".env")
    db_path = ROOT / "stress_chat_battery.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
    os.environ["DISABLE_LLM_FOR_TESTS"] = "true"
    return db_path


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


def _sanitize(text: str) -> str:
    text = re.sub(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    text = re.sub(r"\b(?:\+?55)?\d{10,13}\b", "[telefone]", text)
    text = re.sub(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "[cpf]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:180]


def _contains(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def _load_real_inbound_messages() -> list[str]:
    from scripts.analyze_evolution_last_30_days import _fetch_messages, _is_internal

    messages = _fetch_messages(days=3650)
    inbound = [
        _sanitize(m.text)
        for m in messages
        if not m.from_me and not _is_internal(m) and m.text and not m.text.startswith("[")
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for text in inbound:
        key = text.lower()
        if len(text) < 3 or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def _take(pool: list[str], n: int, fallback: list[str]) -> list[str]:
    values = pool or fallback
    return [values[i % len(values)] for i in range(n)]


def build_scenarios() -> tuple[list[StressScenario], dict[str, int]]:
    texts = _load_real_inbound_messages()
    buckets: dict[str, list[str]] = {
        "remarcacao": [],
        "cancelamento": [],
        "pagamento": [],
        "modalidade": [],
        "agenda": [],
        "fora": [],
        "audio_midia": [],
    }
    for text in texts:
        low = text.lower()
        if _contains(low, ("remarc", "reagend", "mudar horário", "mudar horario", "trocar horário", "trocar horario")):
            buckets["remarcacao"].append(text)
        elif (
            _contains(low, ("cancel", "desmarc", "desisti", "não quero mais", "nao quero mais"))
            and not _contains(low, ("número", "numero", "contato", "se por acaso"))
        ):
            buckets["cancelamento"].append(text)
        elif _contains(low, ("pix", "pagamento", "paguei", "comprovante", "valor", "cartão", "cartao")):
            buckets["pagamento"].append(text)
        elif (
            _contains(low, ("online", "presencial", "video", "vídeo", "whatsapp"))
            and _contains(low, ("?", "funciona", "como", "tem atendimento", "modalidade"))
            and not _contains(low, ("emagrec", "performance", "nome completo", "pagar", "pagamento"))
        ):
            buckets["modalidade"].append(text)
        elif _contains(low, ("agenda", "consulta", "horário", "horario", "disponibilidade", "marcar")):
            buckets["agenda"].append(text)
        elif _contains(low, ("audio", "áudio", "foto", "imagem")):
            buckets["audio_midia"].append(text)
        else:
            buckets["fora"].append(text)

    fallbacks = {
        "remarcacao": ["Preciso remarcar minha consulta", "Consigo trocar meu horario?", "Queria reagendar"],
        "cancelamento": ["Preciso cancelar minha consulta", "Vou desmarcar por imprevisto"],
        "pagamento": ["Como funciona o pagamento?", "Posso pagar no pix?", "Qual o valor?"],
        "modalidade": ["A consulta online funciona pelo WhatsApp?", "Tem atendimento presencial?"],
        "agenda": ["Quero marcar uma consulta", "Tem horario essa semana?", "Quero agendar"],
        "fora": ["Bom dia", "Oi", "Tudo bem?"],
        "audio_midia": ["Vou mandar audio", "Enviei uma foto"],
    }

    scenarios: list[StressScenario] = []

    for i, sample in enumerate(_take(buckets["remarcacao"], 20, fallbacks["remarcacao"]), 1):
        scenarios.append(StressScenario(
            slug=f"stress_remarcacao_{i:02d}",
            title=f"Remarcacao real {i:02d}",
            profile="retorno",
            turns=[sample, "qualquer horário", "1"],
            expected_any=["remarcada com sucesso", "Nova data", "Modalidade"],
            source_category="remarcacao",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["remarcacao"], 15, fallbacks["remarcacao"]), 1):
        scenarios.append(StressScenario(
            slug=f"stress_remarcacao_rejeita_{i:02d}",
            title=f"Remarcacao com rejeicao {i:02d}",
            profile="retorno",
            turns=[sample, "qualquer horário", "nenhum desses horários funciona"],
            expected_any=["Vou buscar mais opções", "Qual horário funciona melhor"],
            source_category="remarcacao_rejeicao",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["cancelamento"], 10, fallbacks["cancelamento"]), 1):
        scenarios.append(StressScenario(
            slug=f"stress_cancelamento_{i:02d}",
            title=f"Cancelamento real {i:02d}",
            profile="retorno",
            turns=[sample, "tive um imprevisto"],
            expected_any=["cancelada com sucesso", "retomar"],
            source_category="cancelamento",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["pagamento"], 15, fallbacks["pagamento"]), 1):
        turn = sample
        if "paguei" in sample.lower() or sample.strip().lower() in ("cartão", "cartao", "pix") or len(sample.strip()) <= 8:
            turn = "Como funciona o pagamento?"
        scenarios.append(StressScenario(
            slug=f"stress_pagamento_{i:02d}",
            title=f"Duvida pagamento {i:02d}",
            turns=[turn],
            expected_any=["pagamento"],
            source_category="pagamento",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["modalidade"], 10, fallbacks["modalidade"]), 1):
        turn = sample if "?" in sample or "funciona" in sample.lower() or "como" in sample.lower() else "Quais modalidades vocês têm?"
        scenarios.append(StressScenario(
            slug=f"stress_modalidade_{i:02d}",
            title=f"Duvida modalidade {i:02d}",
            turns=[turn],
            expected_any=["Online", "Presencial"],
            source_category="modalidade",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["agenda"], 20, fallbacks["agenda"]), 1):
        scenarios.append(StressScenario(
            slug=f"stress_agendamento_{i:02d}",
            title=f"Agendamento real {i:02d}",
            turns=[sample, "Cliente Teste, primeira consulta", "emagrecer", "ouro", "quero manter o ouro", "online", "tarde", "1"],
            expected_any=["pagamento antecipado", "Qual opção prefere"],
            source_category="agenda",
            source_sample=sample,
        ))

    for i, sample in enumerate(_take(buckets["fora"], 10, fallbacks["fora"]), 1):
        scenarios.append(StressScenario(
            slug=f"stress_fora_ou_curta_{i:02d}",
            title=f"Mensagem curta/ambigua {i:02d}",
            turns=[sample],
            expected_any=["agendamentos"],
            source_category="fora_ou_curta",
            source_sample=sample,
        ))

    return scenarios[:100], {name: len(items) for name, items in buckets.items()}


def _evaluate(scenario: StressScenario, transcript: list[dict[str, Any]]) -> tuple[str, list[str]]:
    text = "\n".join("\n".join(turn["responses"]) for turn in transcript if turn["responses"]).lower()
    issues = [f"Esperado conter: {needle}" for needle in scenario.expected_any if needle.lower() not in text]
    return ("PASS" if not issues else "FAIL"), issues


async def _fake_media(meta, phone: str, msg: dict) -> None:
    media_type = msg.get("media_type")
    caption = msg.get("caption", "")
    if media_type == "image":
        await meta.send_image(phone, "fake-media-id", caption)
    else:
        await meta.send_document(phone, "fake-media-id", "arquivo.pdf", caption)


def _write_report(results: list[dict[str, Any]], buckets: dict[str, int], db_path: Path) -> tuple[Path, Path]:
    json_path = REPORT_DIR / "evolution_stress_100_results.json"
    md_path = REPORT_DIR / "evolution_stress_100_report.md"
    json_path.write_text(json.dumps({"buckets": buckets, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Bateria de Estresse - 100 cenarios derivados do WhatsApp",
        "",
        f"- Total: {len(results)}",
        f"- PASS: {sum(1 for r in results if r['status'] == 'PASS')}",
        f"- FAIL: {sum(1 for r in results if r['status'] == 'FAIL')}",
        f"- Banco temporario: `{db_path.name}`",
        "",
        "## Amostras mineradas por categoria",
        "",
    ]
    for name, count in sorted(buckets.items()):
        lines.append(f"- {name}: {count}")

    lines.extend(["", "## Resultado", "", "| # | Categoria | Cenario | Status | Observacoes |", "|---|---|---|---|---|"])
    for r in results:
        obs = "; ".join(r["issues"]) if r["issues"] else "-"
        lines.append(f"| {r['id']} | {r['source_category']} | {r['title']} | {r['status']} | {obs} |")

    lines.extend(["", "## Falhas detalhadas", ""])
    for r in results:
        if r["status"] != "FAIL":
            continue
        lines.append(f"### {r['id']}. {r['title']}")
        lines.append(f"- Categoria: {r['source_category']}")
        lines.append(f"- Amostra anonimizada: `{r['source_sample']}`")
        for issue in r["issues"]:
            lines.append(f"- {issue}")
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    db_path = _setup_env()
    scenarios, buckets = build_scenarios()

    from app.main import app
    from app.conversation import state as conv_state
    from app.database import SessionLocal
    from app.models import Contact
    from scripts.manual_chat_battery import (
        FakeDietbox,
        _fake_detectar_tipo_remarcacao,
        _fake_gerar_link,
        _fake_slots_remarcar,
    )

    fake_db = FakeDietbox()
    results: list[dict[str, Any]] = []

    async def _consultar_slots_remarcar_async(modalidade, preferencia, fim_janela, excluir=None, pool=None):
        return _fake_slots_remarcar(modalidade, preferencia, fim_janela, excluir, pool)

    async def _detectar_tipo_async(telefone):
        return _fake_detectar_tipo_remarcacao(fake_db, telefone)

    patches = [
        patch("app.integrations.dietbox.consultar_slots_disponiveis", side_effect=fake_db.consultar_slots_disponiveis),
        patch("app.integrations.dietbox.processar_agendamento", side_effect=fake_db.processar_agendamento),
        patch("app.integrations.dietbox.buscar_paciente_por_telefone", side_effect=fake_db.buscar_paciente_por_telefone),
        patch("app.integrations.dietbox.consultar_agendamento_ativo", side_effect=fake_db.consultar_agendamento_ativo),
        patch("app.integrations.dietbox.verificar_lancamento_financeiro", side_effect=fake_db.verificar_lancamento_financeiro),
        patch("app.integrations.dietbox.alterar_agendamento", side_effect=fake_db.alterar_agendamento),
        patch("app.integrations.dietbox.cancelar_agendamento", side_effect=fake_db.cancelar_agendamento),
        patch("app.integrations.dietbox.confirmar_pagamento", side_effect=fake_db.confirmar_pagamento),
        patch("app.integrations.payment_gateway.gerar_link_pagamento", side_effect=_fake_gerar_link),
        patch("app.tools.scheduling.consultar_slots_remarcar", side_effect=_consultar_slots_remarcar_async),
        patch("app.tools.patients.detectar_tipo_remarcacao", side_effect=_detectar_tipo_async),
        patch("app.chatwoot_bridge.is_human_handoff_active", return_value=False),
        patch("app.router._enviar_midia", side_effect=_fake_media),
    ]

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12]:
        with TestClient(app) as client:
            conv_state._state_mgr = None
            for idx, scenario in enumerate(scenarios, start=1):
                print(f"[{idx:03d}/{len(scenarios)}] {scenario.slug}", flush=True)
                phone = f"55990000{idx:04d}"
                phone_hash = _hash_phone(phone)
                conv_state._mem_store.clear()
                fake_db.reset_for(phone, scenario.profile)
                client.post("/test/reset", json={"phone": phone})

                transcript: list[dict[str, Any]] = []
                for turn in scenario.turns:
                    resp = client.post("/test/chat", json={"phone": phone, "message": turn})
                    payload = resp.json()
                    transcript.append({"message": turn, "responses": payload["responses"]})

                state = asyncio.run(conv_state.load_state(phone_hash, phone))
                with SessionLocal() as db:
                    contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
                    contact_info = {"stage": getattr(contact, "stage", None)}

                status, issues = _evaluate(scenario, transcript)
                results.append({
                    "id": idx,
                    "slug": scenario.slug,
                    "title": scenario.title,
                    "source_category": scenario.source_category,
                    "source_sample": scenario.source_sample,
                    "status": status,
                    "issues": issues,
                    "transcript": transcript,
                    "final_state": state,
                    "contact": contact_info,
                })
                _write_report(results, buckets, db_path)

    json_path, md_path = _write_report(results, buckets, db_path)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")


if __name__ == "__main__":
    main()
