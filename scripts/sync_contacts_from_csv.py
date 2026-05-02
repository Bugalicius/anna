#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/sync_contacts_from_csv.py

Sincroniza contatos da planilha CSV com o Chatwoot:
  - Atualiza nomes de contatos existentes
  - Cria novos contatos

Uso:
  python scripts/sync_contacts_from_csv.py path/to/planilha.csv --dry-run
  python scripts/sync_contacts_from_csv.py path/to/planilha.csv --apply

Variaveis de ambiente necessarias:
  CHATWOOT_API_URL, CHATWOOT_API_TOKEN, CHATWOOT_ACCOUNT_ID, CHATWOOT_INBOX_ID
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

# UTF-8 encoding para Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Variaveis de ambiente ─────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CHATWOOT_URL   = os.environ.get("CHATWOOT_API_URL", "").rstrip("/")
CHATWOOT_TOKEN = os.environ.get("CHATWOOT_API_TOKEN", "")
ACCOUNT_ID     = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
INBOX_ID       = int(os.environ.get("CHATWOOT_INBOX_ID", "1"))

# Numeros internos — nunca modificar
BLOCKED_PHONES = {
    os.environ.get("THAYNARA_PHONE", "5531991394759"),
    os.environ.get("BRENO_PHONE",    "5531992059211"),
}


def phone_variants(phone: str) -> set[str]:
    """
    Gera variantes do numero para comparacao tolerante ao nono digito brasileiro.

    Brasil: codigo pais 55 + DDD (2 dig) + numero (8 ou 9 dig)
    - 13 digitos: 55 + DDD + 9 + 8 digitos  → tambem gera versao sem o 9
    - 12 digitos: 55 + DDD + 8 digitos      → tambem gera versao com o 9

    Exemplo:
      5531986240221 (13) → {5531986240221, 553186240221}
      553186240221  (12) → {553186240221,  5531986240221}
    """
    variants = {phone}
    if phone.startswith("55") and len(phone) == 13:
        # Remove o 9 apos o DDD (posicao 4)
        sem9 = phone[:4] + phone[5:]
        variants.add(sem9)
    elif phone.startswith("55") and len(phone) == 12:
        # Insere o 9 apos o DDD (posicao 4)
        com9 = phone[:4] + "9" + phone[4:]
        variants.add(com9)
    return variants


# ══════════════════════════════════════════════════════════════════════════════
# Chatwoot API Client (simplificado)
# ══════════════════════════════════════════════════════════════════════════════

class ChatwootClient:
    """Cliente HTTP minimo para a API v1 do Chatwoot."""

    def __init__(self) -> None:
        if not CHATWOOT_URL or not CHATWOOT_TOKEN:
            raise ValueError(
                "CHATWOOT_API_URL e CHATWOOT_API_TOKEN sao obrigatorios no .env"
            )
        self.base    = f"{CHATWOOT_URL}/api/v1/accounts/{ACCOUNT_ID}"
        self.headers = {
            "api_access_token": CHATWOOT_TOKEN,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        r = httpx.get(
            f"{self.base}{path}", headers=self.headers,
            params=params, timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = httpx.post(
            f"{self.base}{path}", headers=self.headers,
            json=body, timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def search_contact(self, phone: str) -> Optional[dict]:
        """Busca contato por telefone. Retorna None se nao encontrado.

        Compara variantes com e sem o nono digito do Brasil (DDD celular).
        Ex: 5531986240221 (13 dig) bate em 553186240221 (12 dig) e vice-versa.
        """
        variants = phone_variants(phone)

        # Tenta buscar por cada variante — o Chatwoot faz busca parcial
        for variant in variants:
            try:
                data = self._get("/contacts/search", {"q": variant, "include_contacts": "true"})
            except httpx.HTTPStatusError:
                continue
            for c in data.get("payload", []):
                cp = (c.get("phone_number") or "").lstrip("+").replace(" ", "")
                if cp in variants:
                    return c

        return None

    def create_contact(self, phone: str, name: str) -> dict:
        payload = self._post("/contacts", {
            "name": name,
            "phone_number": f"+{phone}",
            "identifier": phone,
        })
        contact = (
            payload.get("payload", {}).get("contact")
            or payload.get("contact")
            or payload
        )
        if not contact or not contact.get("id"):
            raise ValueError(f"create_contact nao retornou id valido: {payload}")
        return contact

    def get_or_create_contact(self, phone: str, name: str) -> dict:
        existing = self.search_contact(phone)
        if existing:
            return existing
        try:
            contact = self.create_contact(phone, name)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 422:
                time.sleep(0.5)
                found = self.search_contact(phone)
                if found:
                    return found
            raise
        time.sleep(0.3)
        return contact

    def update_contact_name(self, contact_id: int, name: str) -> None:
        """Atualiza nome do contato no Chatwoot."""
        try:
            r = httpx.patch(
                f"{self.base}/contacts/{contact_id}",
                headers=self.headers,
                json={"name": name},
                timeout=30,
            )
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"PATCH contact {contact_id}: {e}") from e


# ══════════════════════════════════════════════════════════════════════════════
# Parsing CSV
# ══════════════════════════════════════════════════════════════════════════════

def normalize_phone(phone: str) -> Optional[str]:
    """Extrai apenas digitos e retorna sem + ou espaços."""
    if not phone:
        return None
    # Remove quotes do Excel: ="..." ou ="+..."
    phone = phone.strip()
    if phone.startswith('="'):
        phone = phone[2:-1]
    if phone.startswith("+"):
        phone = phone[1:]
    digits = "".join(ch for ch in phone if ch.isdigit())
    return digits if len(digits) >= 8 else None


def load_csv(filepath: str) -> list[dict]:
    """Le CSV com formato Excel e retorna lista de contatos."""
    contacts = []

    # Tenta diferentes encodings
    encodings = ["latin-1", "utf-16", "utf-8-sig", "cp1252"]
    data = None

    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                data = f.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if not data:
        print(f"ERRO: Nao foi possivel decodificar {filepath}")
        sys.exit(1)

    try:
        # Processa o conteudo
        lines = data.split("\n")
        if not lines:
            return contacts

        # Detecta separador e pula primeira linha se necessario
        first_line = lines[0].strip()
        delimiter = "|" if "sep=|" in first_line else ","

        start_idx = 1 if first_line.startswith("sep=") else 0
        header_line = lines[start_idx] if start_idx < len(lines) else ""

        # Parse manual do CSV
        header = [h.strip() for h in header_line.split(delimiter)]
        nome_idx = header.index("Nome") if "Nome" in header else -1
        celular_idx = header.index("Celular") if "Celular" in header else -1
        email_idx = header.index("Email") if "Email" in header else -1

        if nome_idx < 0 or celular_idx < 0:
            print("ERRO: Colunas 'Nome' ou 'Celular' nao encontradas no CSV")
            sys.exit(1)

        # Processa linhas
        for i in range(start_idx + 1, len(lines)):
            if not lines[i].strip():
                continue

            parts = [p.strip() for p in lines[i].split(delimiter)]

            nome = parts[nome_idx] if nome_idx < len(parts) else ""
            celular = parts[celular_idx] if celular_idx < len(parts) else ""
            email = parts[email_idx] if email_idx < len(parts) else ""

            nome = nome.strip()
            phone = normalize_phone(celular)

            if not nome or not phone:
                continue

            contacts.append({
                "nome": nome,
                "phone": phone,
                "email": email.strip(),
            })
    except Exception as e:
        print(f"ERRO ao processar CSV: {e}")
        sys.exit(1)

    return contacts


# ══════════════════════════════════════════════════════════════════════════════
# Sincronizacao
# ══════════════════════════════════════════════════════════════════════════════

def run_sync(contacts: list[dict], apply: bool = False) -> None:
    """Sincroniza contatos: atualiza nomes e cria novos."""

    if not apply:
        print("=" * 70)
        print("DRY-RUN — nenhuma alteracao sera feita no Chatwoot")
        print("=" * 70)
    else:
        print("=" * 70)
        print("SINCRONIZACAO ATIVA — atualizando Chatwoot")
        print("=" * 70)

    client = ChatwootClient()

    # Estatisticas
    stats = {
        "sem_nome": 0,
        "sem_telefone": 0,
        "bloqueados": 0,
        "atualizados": 0,
        "criados": 0,
        "ja_existem": 0,
        "erros": 0,
    }

    print(f"\nProcessando {len(contacts)} contatos da planilha...\n")

    for idx, contact in enumerate(contacts, 1):
        nome = contact["nome"]
        phone = contact["phone"]
        email = contact.get("email", "")

        # Validacoes basicas
        if not nome or nome.startswith("Thaynara"):
            stats["sem_nome"] += 1
            continue

        if not phone:
            stats["sem_telefone"] += 1
            print(f"  [{idx}] SKIP {nome} — sem telefone valido")
            continue

        if phone in BLOCKED_PHONES:
            stats["bloqueados"] += 1
            continue

        # Busca ou cria contato
        try:
            existing = client.search_contact(phone)

            if existing:
                contact_id = existing.get("id")
                current_name = (existing.get("name") or "").strip()

                # Compara nomes
                if current_name == nome:
                    stats["ja_existem"] += 1
                    print(f"  [{idx}] OK {phone} | {nome!r} (ja correto)")
                else:
                    # Atualiza nome
                    if apply:
                        try:
                            client.update_contact_name(contact_id, nome)
                            stats["atualizados"] += 1
                            print(f"  [{idx}] UPDATE {phone} | {current_name!r} -> {nome!r}")
                            time.sleep(0.1)
                        except Exception as e:
                            stats["erros"] += 1
                            print(f"  [{idx}] ERRO UPDATE {phone}: {e}")
                    else:
                        stats["atualizados"] += 1
                        print(f"  [{idx}] [SERIA] UPDATE {phone} | {current_name!r} -> {nome!r}")
            else:
                # Cria novo contato
                if apply:
                    try:
                        new_contact = client.get_or_create_contact(phone, nome)
                        stats["criados"] += 1
                        print(f"  [{idx}] CREATE {phone} | {nome!r} | id={new_contact.get('id')}")
                        time.sleep(0.15)
                    except Exception as e:
                        stats["erros"] += 1
                        print(f"  [{idx}] ERRO CREATE {phone}: {e}")
                else:
                    stats["criados"] += 1
                    print(f"  [{idx}] [SERIA] CREATE {phone} | {nome!r}")

        except Exception as e:
            stats["erros"] += 1
            print(f"  [{idx}] ERRO {phone}: {e}")

    # Resumo
    print()
    print("=" * 70)
    print("RESUMO")
    print("=" * 70)
    print(f"  Atualizados (nome)  : {stats['atualizados']}")
    print(f"  Criados             : {stats['criados']}")
    print(f"  Ja corretos         : {stats['ja_existem']}")
    print(f"  Sem telefone        : {stats['sem_telefone']}")
    print(f"  Sem nome util       : {stats['sem_nome']}")
    print(f"  Bloqueados          : {stats['bloqueados']}")
    print(f"  Erros               : {stats['erros']}")
    print()

    if not apply:
        print("PROXIMO PASSO:")
        print("  python scripts/sync_contacts_from_csv.py 1.csv --apply")
        print()


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sincroniza contatos da planilha CSV com Chatwoot",
    )
    parser.add_argument(
        "csv_file",
        help="Caminho do arquivo CSV (ex: 1.csv)",
    )
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Aplica as mudancas no Chatwoot (padrao: dry-run)",
    )
    parser.add_argument(
        "--yes", action="store_true", default=False,
        help="Pula confirmacoes interativas",
    )
    args = parser.parse_args()

    # Valida arquivo
    csv_path = Path(args.csv_file)
    if not csv_path.exists():
        print(f"ERRO: Arquivo {csv_path} nao encontrado.")
        sys.exit(1)

    # Valida Chatwoot
    if not CHATWOOT_URL or not CHATWOOT_TOKEN:
        print("ERRO: CHATWOOT_API_URL e CHATWOOT_API_TOKEN devem estar no .env")
        sys.exit(1)

    # Carrega contatos
    print(f"Carregando {csv_path}...")
    contacts = load_csv(str(csv_path))
    print(f"  {len(contacts)} contatos carregados\n")

    # Executa
    if args.apply and not args.yes:
        print("AVISO: Este comando vai ATUALIZAR/CRIAR contatos no Chatwoot.")
        print("Digite 'confirmar' para continuar:")
        resp = input("> ").strip()
        if resp.lower() != "confirmar":
            print("Cancelado.")
            sys.exit(0)

    run_sync(contacts, apply=args.apply)


if __name__ == "__main__":
    main()
