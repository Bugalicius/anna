"""
debug_bug_nome.py — Reproduz o bug "agente nao entende nome Breno".

Cenario do print:
  1. Agente envia boas-vindas + pede nome
  2. Paciente manda "oi"          -> correto: "Acho que faltou seu nome"
  3. Paciente manda "Breno"       -> BUG: "Pode me dar mais detalhes..."

Logging detalhado em cada passo:
  - Raw response do interpreter
  - Intent + confidence + entities + validacoes
  - Estado antes e depois
  - Trigger que casou (ou nenhum)
  - Output do response_writer antes da validacao
  - Violacoes detectadas pelo output_validator
  - Mensagem final enviada

Requisitos:
  REDIS_URL e GEMINI_API_KEY devem estar no .env (ou exportadas no shell).
  Nao precisa de banco real — so usa Redis/in-memory.

Uso:
  cd /root/agente
  python scripts/debug_bug_nome.py 2>&1 | tee logs/debug_bug_nome_$(date +%Y%m%d_%H%M%S).log
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

# --- carrega .env se existir ---
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# --- logging DEBUG em tudo que interessa ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(name)-40s | %(levelname)-8s | %(message)s",
    stream=sys.stdout,
)
for modulo in [
    "app.conversation",
    "app.conversation.orchestrator",
    "app.conversation.interpreter",
    "app.conversation.state_machine",
    "app.conversation.response_writer",
    "app.conversation.output_validator",
    "app.conversation.rules",
]:
    logging.getLogger(modulo).setLevel(logging.DEBUG)

# silencia barulho de libs externas
for barulhento in ["httpx", "httpcore", "urllib3", "asyncio"]:
    logging.getLogger(barulhento).setLevel(logging.WARNING)

PHONE_TEST = "5599999debug001"


def _sep(titulo: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {titulo}")
    print("=" * 80)


def _dump(label: str, obj: object) -> None:
    print(f"\n[DEBUG] {label}:")
    try:
        print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))
    except Exception:
        print(repr(obj))


async def _limpar_estado() -> None:
    """Remove estado anterior do phone de teste (Redis ou in-memory)."""
    from app.conversation.state import _mem_store

    import hashlib
    phone_hash = hashlib.sha256(PHONE_TEST.encode()).hexdigest()[:64]
    keys_para_deletar = [k for k in list(_mem_store.keys()) if phone_hash in k]
    for k in keys_para_deletar:
        del _mem_store[k]
    print(f"[SETUP] Estado in-memory limpo. Chaves removidas: {keys_para_deletar or '(nenhuma)'}")

    try:
        from redis.asyncio import Redis
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        r = Redis.from_url(redis_url)
        await r.delete(f"agente:state:{phone_hash}")
        await r.close()
        print(f"[SETUP] Estado Redis limpo para phone_hash={phone_hash[:16]}...")
    except Exception as exc:
        print(f"[SETUP] Redis nao disponivel ({exc}) — usando in-memory.")


async def _turno(numero: int, texto: str) -> None:
    from app.conversation.orchestrator import processar_turno
    from app.conversation.state import load_state

    import hashlib
    phone_hash = hashlib.sha256(PHONE_TEST.encode()).hexdigest()[:64]

    _sep(f"TURNO {numero}: paciente manda {texto!r}")

    state_antes = await load_state(phone_hash)
    _dump("Estado ANTES do turno", {
        "estado": state_antes.get("estado"),
        "collected_data": state_antes.get("collected_data"),
        "flags": state_antes.get("flags"),
    })

    resultado = await processar_turno(
        phone=PHONE_TEST,
        mensagem={"type": "text", "text": texto, "from": PHONE_TEST, "id": f"msg{numero}"},
    )

    state_depois = await load_state(phone_hash)
    _dump("Estado DEPOIS do turno", {
        "estado": state_depois.get("estado"),
        "collected_data": state_depois.get("collected_data"),
        "flags": state_depois.get("flags"),
    })

    if resultado:
        _dump("Mensagens enviadas", [
            {"tipo": m.tipo, "conteudo": m.conteudo}
            for m in (resultado.mensagens_enviadas or [])
        ])
    else:
        print("[DEBUG] Resultado None (processamento bloqueado ou erro)")


async def run() -> None:
    print("\n[INICIO] Iniciando debug do bug 'agente nao aceita nome Breno'")
    print(f"[INICIO] Phone de teste: {PHONE_TEST}")

    await _limpar_estado()

    # --- Turno 0: simula o on_enter de inicio (agente sauda o paciente) ---
    # Na producao o primeiro turno do paciente dispara o on_enter.
    # Replicamos enviando uma mensagem inicial qualquer.
    await _turno(0, "oi")  # dispara on_enter → boas-vindas + pede nome

    # --- Turno 1: paciente manda "oi" de novo (estado ja e aguardando_nome) ---
    # Esperado: "Acho que faltou seu nome"
    await _turno(1, "oi")

    # --- Turno 2: paciente manda "Breno" ---
    # Esperado: "Prazer, Breno! ..."
    # BUG: "Pode me dar mais detalhes..."
    await _turno(2, "Breno")

    _sep("DIAGNOSTICO RAPIDO")
    print("""
Interpretar "Breno" em aguardando_nome:
  - _extrair_nome("Breno") retorna "Breno" (5 chars >= 2, 1 palavra <= 5)
  - R12_validar_nome_nao_generico("Breno"): "breno" NAO esta em _NOMES_GENERICOS -> passou=True
  - validacao_nome_passou = True
  - intent = informar_nome

State machine: trigger "intent=informar_nome AND validacao_nome_passou=true"
  -> situacao nome_valido MATCH
  -> resposta: "Prazer, {primeiro_nome}!"
  -> proximo_estado: aguardando_status_paciente

Response writer:
  - renderiza "{primeiro_nome}" -> "Breno" (do contexto via entidades ou collected_data)
  - texto resultante: "Prazer, Breno! ..."

Output validator - R1_nunca_expor_breno:
  - re.search(r"\\bbreno\\b", "prazer, breno! ...") -> MATCH!
  - _bloquear() retornado
  - regenerador retorna _FALLBACK_PADRAO = "Pode me dar mais detalhes..."
  - segunda validacao: sem violacoes -> APROVADO

RESULTADO: paciente recebe "Pode me dar mais detalhes para eu te ajudar certinho?"
""")

    _sep("VALIDACAO DIRETA DAS REGRAS")
    from app.conversation.rules import R1_nunca_expor_breno, R12_validar_nome_nao_generico

    casos_r12 = [("Breno", True), ("oi", False), ("consulta", False), ("Maria Silva", True)]
    print("\nR12 (validar_nome_nao_generico):")
    for nome, esperado in casos_r12:
        resultado_r12 = R12_validar_nome_nao_generico(nome)
        status = "OK" if resultado_r12.passou == esperado else "FALHOU"
        print(f"  [{status}] R12({nome!r}) = passou={resultado_r12.passou} (esperado={esperado})")

    casos_r1_saida = [
        ("Prazer, Breno! Sua primeira consulta?", True, "Resposta tipica do agente para paciente chamado Breno"),
        ("Fale com o Breno no 31 99205-9211", True, "Expor contato do Breno (deve bloquear)"),
        ("Pra comecar, qual e o seu nome e sobrenome?", False, "Palavra sobrenome contem breno como substring (nao deve bloquear com word boundary)"),
        ("Pode me dar mais detalhes?", False, "Fallback padrao (nao deve bloquear)"),
    ]
    print("\nR1 (nunca_expor_breno) — aplicada a SAIDA do agente:")
    for texto, espera_bloqueio, descricao in casos_r1_saida:
        resultado_r1 = R1_nunca_expor_breno(texto)
        bloqueou = not resultado_r1.passou
        status = "OK" if bloqueou == espera_bloqueio else "FALHOU"
        icone = "BLOQUEOU" if bloqueou else "passou"
        print(f"  [{status}] [{icone}] {descricao!r}")
        if bloqueou and not espera_bloqueio:
            print(f"    *** FALSO POSITIVO: {texto!r} ***")
        elif not bloqueou and espera_bloqueio:
            print(f"    *** FALSO NEGATIVO: {texto!r} ***")


if __name__ == "__main__":
    asyncio.run(run())
