"""
Teste prático: dispara uma escalação real para o número do Breno via Meta API.

Uso:
    python scripts/test_escalacao_real.py

O script:
1. Carrega credenciais do .env
2. Envia mensagem de contexto ao _NUMERO_INTERNO (Breno)
3. Imprime o resultado da API
"""
import asyncio
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx
from app.escalation import _NUMERO_INTERNO, build_contexto_escalacao
from app.meta_api import MetaAPIClient


async def main():
    token = os.environ.get("WHATSAPP_TOKEN", "")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")

    if not token or not phone_id:
        print("ERRO: WHATSAPP_TOKEN ou WHATSAPP_PHONE_NUMBER_ID nao encontrado no .env")
        sys.exit(1)

    print(f"Phone Number ID : {phone_id}")
    print(f"Numero interno  : {_NUMERO_INTERNO}")
    print()

    contexto = build_contexto_escalacao(
        nome_paciente="Carlos Teste",
        telefone_paciente="5531999990099",
        historico_resumido=(
            "Paciente: Oi, quero agendar\n"
            "Ana: Ótimo! Qual seu nome?\n"
            "Paciente: Carlos Teste, sou novo\n"
            "Paciente: tenho diabetes, posso comer pão integral?"
        ),
        motivo="duvida_clinica",
    )

    msg = "[TESTE AUTOMATICO] " + contexto

    print("Enviando ao numero interno (Breno)...")
    print("=" * 60)
    print(msg)
    print("=" * 60)

    meta = MetaAPIClient(phone_number_id=phone_id, access_token=token)

    try:
        resultado = await meta.send_text(_NUMERO_INTERNO, msg)
        print()
        print("Sucesso! Resposta da API:")
        print(resultado)
    except httpx.HTTPStatusError as e:
        print()
        print(f"ERRO HTTP {e.response.status_code}: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"ERRO: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
