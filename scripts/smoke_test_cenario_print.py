"""
Reproduz localmente o cenario do print do Breno sem enviar mensagem real.

Uso:
    python scripts/smoke_test_cenario_print.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


async def main() -> None:
    from app.conversation import orchestrator
    from app.conversation import state as legacy_state
    from app.conversation.tools import ToolResult

    phone = "5511999990001"
    phone_hash = _phone_hash(phone)
    old = datetime.now(UTC) - timedelta(hours=5, minutes=32)

    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(
        {
            "phone": phone,
            "phone_hash": phone_hash,
            "fluxo_id": "agendamento_paciente_novo",
            "estado": "aguardando_escolha_plano",
            "collected_data": {"nome": "Paciente Teste"},
            "history": [
                {"role": "assistant", "content": "Hoje temos estas opções. Qual faz mais sentido pra você agora?"}
            ],
            "last_message_at": old.isoformat(),
        },
        ensure_ascii=False,
    )

    escalacoes: list[dict] = []

    async def _dry_call_tool(nome: str, payload: dict):
        if nome == "escalar_breno_silencioso":
            escalacoes.append(payload)
        return ToolResult(sucesso=True, dados={"dry_run": True})

    orchestrator.call_tool = _dry_call_tool

    result_oi = await orchestrator.processar_turno(
        phone,
        {"type": "text", "text": "Oi", "from": phone, "id": "smoke-1"},
    )
    texto_oi = "\n".join(m.conteudo for m in result_oi.mensagens_enviadas)
    assert "outro jeito" not in texto_oi.lower(), texto_oi
    assert result_oi.novo_estado == "aguardando_nome", result_oi.novo_estado

    state = json.loads(legacy_state._mem_store[f"conv_state:{phone_hash}"])
    fallback_text = "Pode me mandar de outro jeito para eu entender certinho?"
    state.update(
        {
            "estado": "aguardando_escolha_plano",
            "fallback_streak": 2,
            "last_response_hash": hashlib.sha256(fallback_text.encode()).hexdigest()[:16],
            "last_message_at": datetime.now(UTC).isoformat(),
        }
    )
    legacy_state._mem_store[f"conv_state:{phone_hash}"] = json.dumps(state, ensure_ascii=False)

    result_loop = await orchestrator.processar_turno(
        phone,
        {"type": "text", "text": "Mandar oq?", "from": phone, "id": "smoke-2"},
    )
    respostas = [m.conteudo for m in result_loop.mensagens_enviadas]
    assert respostas == ["Deixa eu chamar alguém da equipe pra te dar atenção especial 💚"], respostas
    assert escalacoes, "Escalacao silenciosa nao foi acionada"

    print("Smoke do cenario do print passou.")


if __name__ == "__main__":
    asyncio.run(main())
