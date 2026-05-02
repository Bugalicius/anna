#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/importar_chatwoot.py

Importa historico do conversas_export.json (Evolution API) para o Chatwoot.

Modos de execucao:
  python scripts/importar_chatwoot.py                       # dry-run (padrao)
  python scripts/importar_chatwoot.py --dry-run             # idem
  python scripts/importar_chatwoot.py --dry-run --limit 10  # simula 10 contatos
  python scripts/importar_chatwoot.py --limit 3 --apply     # importa 3 contatos
  python scripts/importar_chatwoot.py --apply               # importa tudo (pede confirmacao)
  python scripts/importar_chatwoot.py --redis-preload       # so precarrega Redis

Variaveis de ambiente necessarias (.env):
  CHATWOOT_API_URL, CHATWOOT_API_TOKEN, CHATWOOT_ACCOUNT_ID, CHATWOOT_INBOX_ID
  REDIS_URL (para --redis-preload)
  DIETBOX_EMAIL, DIETBOX_SENHA (para --redis-preload)

Saida:
  scripts/importacao_resultado.json  — relatorio do dry-run
  scripts/checkpoint.json            — mapeamento {telefone: dados_chatwoot} persistido
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv

# Força UTF-8 no stdout/stderr para não quebrar com emojis no Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Caminhos ──────────────────────────────────────────────────────────────────

ROOT    = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

EXPORT_FILE     = ROOT / "conversas_export.json"
CHECKPOINT_FILE = SCRIPTS / "checkpoint.json"
RESULTADO_FILE  = SCRIPTS / "importacao_resultado.json"

# ── Variaveis de ambiente ─────────────────────────────────────────────────────

# Carrega .env raiz primeiro, depois scripts/.env sem sobrescrever
load_dotenv(ROOT / ".env")
load_dotenv(SCRIPTS / ".env", override=False)

CHATWOOT_URL   = os.environ.get("CHATWOOT_API_URL", "").rstrip("/")
CHATWOOT_TOKEN = os.environ.get("CHATWOOT_API_TOKEN", "")
ACCOUNT_ID     = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
INBOX_ID       = int(os.environ.get("CHATWOOT_INBOX_ID", "1"))
REDIS_URL      = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Numeros internos — nunca importar
BLOCKED_PHONES = {
    os.environ.get("THAYNARA_PHONE", "5531991394759"),
    os.environ.get("BRENO_PHONE",    "5531992059211"),
}

IMPORT_LABEL = "importado_evolution"
BOT_PUSHNAME = "Ana - Atendente Nutri Thaynara Teixeira"
ADD_IMPORT_LABEL = False  # Evita mensagens de atividade no Chatwoot; o checkpoint garante idempotencia.


# ══════════════════════════════════════════════════════════════════════════════
# Chatwoot API Client
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

    # ── Chamadas HTTP ─────────────────────────────────────────────────────────

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

    def _delete(self, path: str) -> None:
        httpx.delete(f"{self.base}{path}", headers=self.headers, timeout=30)

    # ── Contatos ──────────────────────────────────────────────────────────────

    def search_contact(self, phone: str) -> Optional[dict]:
        """Busca contato por telefone. Retorna None se nao encontrado."""
        try:
            data = self._get("/contacts/search", {"q": phone, "include_contacts": "true"})
        except httpx.HTTPStatusError:
            return None
        for c in data.get("payload", []):
            cp = (c.get("phone_number") or "").lstrip("+").replace(" ", "")
            if cp == phone:
                return c
        return None

    def create_contact(self, phone: str, name: str) -> dict:
        payload = self._post("/contacts", {
            "name": name,
            "phone_number": f"+{phone}",
            "identifier": phone,
        })
        # Chatwoot pode retornar várias estruturas dependendo da versão:
        #   {payload: {contact: {id, ...}}}   ← v3 (observado em produção)
        #   {contact: {id, ...}}
        #   {id, ...}
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
            # 422 = contato ja existe (criado por outro processo concorrente)
            if e.response.status_code == 422:
                time.sleep(0.5)
                found = self.search_contact(phone)
                if found:
                    return found
            raise
        # Pequena pausa para o Chatwoot persistir o contato antes de criar conversa
        time.sleep(0.3)
        return contact

    # ── Conversas ─────────────────────────────────────────────────────────────

    def get_existing_imported_conversation(self, contact_id: int) -> Optional[int]:
        """
        Retorna o conversation_id de uma conversa ja importada para este contato,
        ou None se nao existir. Evita criar conversas duplicadas em re-runs.
        """
        try:
            data = self._get(f"/contacts/{contact_id}/conversations")
            convos = data.get("payload", {}).get("conversations", []) or data.get("payload", [])
            for c in convos:
                labels = c.get("labels", [])
                if IMPORT_LABEL in labels:
                    return c.get("id")
        except Exception:
            pass
        return None

    def create_conversation(self, contact_id: int) -> dict:
        """
        Cria conversa com status resolved para nao disparar notificacoes.
        Tenta duas vezes em caso de 404 (race condition apos criacao de contato).
        """
        body = {
            "contact_id": contact_id,
            "inbox_id":   INBOX_ID,
            "status":     "resolved",
        }
        try:
            return self._post("/conversations", body)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                time.sleep(1.0)
                return self._post("/conversations", body)
            raise

    def add_label(self, conversation_id: int, label: str) -> None:
        try:
            self._post(f"/conversations/{conversation_id}/labels", {"labels": [label]})
        except Exception as e:
            print(f"      Aviso: nao foi possivel adicionar label: {e}")

    # ── Mensagens ─────────────────────────────────────────────────────────────

    def create_message(
        self,
        conversation_id: int,
        content: str,
        message_type: str,       # "incoming" | "outgoing"
        created_at: int | None = None,
        private: bool = False,
    ) -> dict:
        body: dict = {
            "content":      content,
            "message_type": message_type,
            "private":      private,
        }
        if created_at:
            body["created_at"] = created_at
        return self._post(f"/conversations/{conversation_id}/messages", body)

    def create_note(self, conversation_id: int, content: str) -> dict:
        """Cria nota privada consolidada do historico."""
        return self._post(f"/conversations/{conversation_id}/messages", {
            "content":      content,
            "message_type": "outgoing",
            "private":      True,
        })

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

    # ── Labels ────────────────────────────────────────────────────────────────

    def ensure_label_exists(self) -> None:
        """Cria o label importado_evolution no Chatwoot se ainda nao existir."""
        try:
            labels   = self._get("/labels")
            existing = {l["title"] for l in labels.get("payload", [])}
            if IMPORT_LABEL not in existing:
                self._post("/labels", {
                    "title":       IMPORT_LABEL,
                    "color":       "#1F93FF",
                    "description": "Conversa importada da Evolution API",
                    "show_on_sidebar": False,
                })
                print(f"  Label '{IMPORT_LABEL}' criado no Chatwoot.")
            else:
                print(f"  Label '{IMPORT_LABEL}' ja existe.")
        except Exception as e:
            print(f"  Aviso: nao foi possivel verificar/criar label: {e}")

    # ── Teste de timestamp historico ──────────────────────────────────────────

    def test_historical_timestamp(self, conversation_id: int) -> bool:
        """
        Envia mensagem de teste com created_at de 2025-01-01 e verifica
        se o Chatwoot honra o timestamp historico.
        Retorna True se aceitar, False se ignorar.
        """
        test_ts = int(datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())
        try:
            msg = self.create_message(
                conversation_id,
                "[teste timestamp historico — pode ignorar]",
                "outgoing",
                created_at=test_ts,
            )
            returned_ts = int(msg.get("created_at", 0))
            return abs(returned_ts - test_ts) < 60
        except Exception:
            return False


# ══════════════════════════════════════════════════════════════════════════════
# Extracao de dados do JSON
# ══════════════════════════════════════════════════════════════════════════════

def extract_phone(conv: dict) -> Optional[str]:
    """
    Extrai numero de telefone da conversa (so digitos, sem prefixo @).

    Prioridade:
      1. chat.remoteJid se termina em @s.whatsapp.net
      2. chat.lastMessage.key.remoteJidAlt
      3. Primeiro remoteJidAlt encontrado nas mensagens
    Retorna None se impossivel extrair numero valido.
    """
    chat       = conv.get("chat", {})
    remote_jid = chat.get("remoteJid", "")

    # Caso 1: JID ja e numero real
    if remote_jid.endswith("@s.whatsapp.net"):
        return _normalize_phone(remote_jid.replace("@s.whatsapp.net", ""))

    # Caso 2: @lid — usa remoteJidAlt da ultima mensagem no cabecalho do chat
    alt = (
        chat.get("lastMessage", {})
            .get("key", {})
            .get("remoteJidAlt", "")
    )
    if alt.endswith("@s.whatsapp.net"):
        return _normalize_phone(alt.replace("@s.whatsapp.net", ""))

    # Caso 3: percorre primeiras 5 mensagens
    for msg in conv.get("messages", [])[:5]:
        raw_alt = msg.get("raw", {}).get("key", {}).get("remoteJidAlt", "")
        if raw_alt.endswith("@s.whatsapp.net"):
            return _normalize_phone(raw_alt.replace("@s.whatsapp.net", ""))

    return None


def _normalize_phone(phone: str) -> Optional[str]:
    """Mantem apenas telefones minimamente validos para importacao no Chatwoot."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits


_GREETINGS_BLOCKLIST = {
    "bom dia", "boa tarde", "boa noite", "boa tarde ana", "bom dia ana",
    "boa noite ana", "ha sim", "há sim", "sim", "ok", "oi", "ola", "olá",
    "tudo bem", "tudo bom", "ana sim", "claro", "pode ser", "com certeza",
    "primeira consulta", "retorno", "sou paciente", "já sou paciente",
    "ah sim", "por favor", "muito obrigada", "muito obrigado", "oh deus",
}

def _looks_like_name(text: str) -> bool:
    """
    Heuristica: o texto parece ser um nome proprio (Nome Sobrenome)?
    Aceita 2 a 5 palavras, maioria iniciando em maiuscula, sem URLs/numeros/simbolos.
    """
    import re
    # Pega apenas a primeira linha (antes de \n)
    text = text.split("\n")[0].strip()
    # Remove prefixo "Nome: " ou "Nome:"
    if text.lower().startswith("nome:"):
        text = text[5:].strip()
    text = re.sub(r"^(ol[aá]|oi|bom dia|boa tarde|boa noite)[,!.\s]+", "", text, flags=re.I).strip()
    if not text or len(text) > 70:
        return False
    # Rejeita saudacoes e frases comuns
    if text.lower().strip(".,! ") in _GREETINGS_BLOCKLIST:
        return False
    words = text.split()
    if len(words) < 2 or len(words) > 5:
        return False
    stopwords = {
        "ah", "sim", "nao", "não", "por", "favor", "obrigada", "obrigado",
        "moro", "tenho", "quero", "gostaria", "consulta", "primeira",
        "retorno", "valor", "pagamento", "cartao", "cartão", "pix", "oh",
        "oie", "isso", "sexta", "sábado", "sabado", "domingo", "segunda",
        "terça", "terca", "quarta", "quinta", "eu", "insta",
    }
    if any(w.lower().strip(".,! ") in stopwords for w in words):
        return False
    # Rejeita se tiver simbolos, numeros, virgulas ou marcadores de lista
    if re.search(r"[!?@#$%&*()\[\]{}<>\\/|=+_0-9•\-,;:]", text):
        return False
    # Rejeita URLs e domínios
    if any(tok in text.lower() for tok in ("http", "www.", ".com", "whatsapp", "instagram")):
        return False
    lowercase_connectors = {"da", "de", "do", "das", "dos", "e"}
    meaningful = [w for w in words if w.lower() not in lowercase_connectors]
    if len(meaningful) < 2:
        return False
    if not all(w and w[0].isupper() for w in meaningful):
        return False
    if "." in text.strip("."):
        return False
    return True


def _is_phone_number(s: str) -> bool:
    """Retorna True se a string parece ser um numero de telefone."""
    clean = (
        s.strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("+", "")
        .replace("(", "")
        .replace(")", "")
    )
    return len(clean) >= 7 and clean.isdigit()


def _is_suspicious_name(name: str, phone: str | None = None) -> bool:
    """Detecta nomes que nao parecem ser nome humano util no Chatwoot."""
    import re

    value = (name or "").strip()
    if not value:
        return True
    if phone and value in {phone, f"+{phone}", f"Contato {phone}"}:
        return True
    if value.startswith("Contato "):
        return True
    if value.startswith("Sem nome "):
        return True
    if _is_phone_number(value):
        return True
    if value == BOT_PUSHNAME:
        return True
    if "nutricionista thaynara" in value.lower():
        return False

    # Emoji/simbolo/apelido muito curto: exemplos "🤍", ".", "M".
    letters = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", value)
    if len(letters) < 2:
        return True

    phrase_markers = {
        "entendi", "obrigada", "obrigado", "pode sim", "estou bem",
        "bom dia", "boa tarde", "boa noite", "isso mesmo", "tudo bem",
        "oie", "confirmado",
    }
    lowered = value.lower().replace("\n", " ").strip(" .,!;:")
    if any(marker in lowered for marker in phrase_markers):
        return True

    return False


def _clean_name(text: str) -> str:
    """Retorna apenas a primeira linha e remove prefixo 'Nome:'."""
    import re

    text = text.split("\n")[0].strip()
    if text.lower().startswith("nome:"):
        text = text[5:].strip()
    text = re.sub(r"^(ol[aá]|oi|bom dia|boa tarde|boa noite)[,!.\s]+", "", text, flags=re.I).strip()
    return text.strip(" .,!;:")


def extract_name(conv: dict) -> str:
    """
    Extrai nome e sobrenome do paciente.

    Prioridade:
      1. chat.pushName (excluindo nome do bot)
      2. pushName de qualquer mensagem incoming
      3. Resposta do paciente imediatamente apos o bot pedir nome/sobrenome
      4. Primeira mensagem incoming curta que parece um nome proprio
    Retorna string vazia se nenhuma heuristica funcionar.
    """
    chat     = conv.get("chat", {})
    messages = conv.get("messages", [])

    # 1. Resposta do paciente apos bot pedir nome/sobrenome.
    # Este sinal e mais confiavel que pushName, que pode ser emoji/apelido.
    ask_keywords = ("nome e sobrenome", "nome completo", "qual seu nome", "seu nome e sobrenome")
    for i, msg in enumerate(messages):
        if not msg.get("fromMe"):
            continue
        bot_text = (msg.get("text") or "").lower()
        if not any(kw in bot_text for kw in ask_keywords):
            continue
        # Procura a próxima mensagem do paciente (até 3 posições à frente)
        for j in range(i + 1, min(i + 4, len(messages))):
            nxt = messages[j]
            if nxt.get("fromMe"):
                continue
            candidate = (nxt.get("text") or "").strip()
            if _looks_like_name(candidate):
                return _clean_name(candidate)
            break  # paciente respondeu mas não parece nome — para

    # 2. Paciente se identificando explicitamente em texto livre.
    import re
    intro_patterns = (
        r"\bmeu nome (?:é|e)\s+(.+)$",
        r"\bme chamo\s+(.+)$",
        r"\bsou (?:a|o)?\s*(.+)$",
        r"\baqui (?:é|e)\s+(.+)$",
    )
    for msg in messages:
        if msg.get("fromMe"):
            continue
        text = (msg.get("text") or "").strip()
        for pattern in intro_patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            candidate = _clean_name(m.group(1))
            if _looks_like_name(candidate):
                return candidate

    # 3. Primeira mensagem incoming que parece nome proprio.
    for msg in messages:
        if msg.get("fromMe"):
            continue
        candidate = (msg.get("text") or "").strip()
        if _looks_like_name(candidate):
            return _clean_name(candidate)

    # 4. pushName do chat, apenas quando parece nome humano.
    push = chat.get("pushName") or ""
    if (
        push
        and push != BOT_PUSHNAME
        and not _is_phone_number(push)
        and not _is_suspicious_name(push)
    ):
        return _clean_name(push)

    # 5. pushName de mensagem incoming, com os mesmos filtros.
    for msg in messages:
        if msg.get("fromMe"):
            continue
        pn = msg.get("pushName") or ""
        if (
            pn
            and pn != BOT_PUSHNAME
            and not _is_phone_number(pn)
            and not _is_suspicious_name(pn)
        ):
            return _clean_name(pn)

    return ""


def nameless_label(index: int) -> str:
    """Nome padrao para contatos sem identificacao confiavel no historico."""
    return f"Sem nome {index:03d}"


def extract_messages(conv: dict) -> list[dict]:
    """
    Retorna mensagens normalizadas com texto (descarta midias).
    Cada item: {text, from_me, timestamp}
    """
    result = []
    for msg in conv.get("messages", []):
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        # Tambem descarta mensagens que sao apenas descricao de midia
        if text in ("[midia]", "[mídia]"):
            continue
        result.append({
            "text":      text,
            "from_me":   bool(msg.get("fromMe")),
            "timestamp": int(msg.get("messageTimestamp", 0)),
        })
    return result


def format_note(messages: list[dict], phone: str) -> str:
    """
    Formata historico completo como nota privada consolidada.
    Formato: [DD/MM HH:mm] Paciente: texto / [DD/MM HH:mm] Ana: texto
    """
    if not messages:
        return f"[Historico da conversa — sem mensagens de texto]\nTelefone: {phone}"

    lines = [f"Historico da conversa\nTelefone: {phone}\n"]
    for m in messages:
        if m["timestamp"]:
            dt    = datetime.fromtimestamp(m["timestamp"], tz=timezone.utc)
            label = f"[{dt.strftime('%d/%m %H:%M')}]"
        else:
            label = "[?]"
        role = "Ana" if m["from_me"] else "Paciente"
        lines.append(f"{label} {role}: {m['text']}")
    return "\n".join(lines)


def phone_hash(phone: str) -> str:
    """Gera hash SHA-256 do JID — mesmo padrao do agente Ana."""
    jid = f"{phone}@s.whatsapp.net"
    return hashlib.sha256(jid.encode()).hexdigest()[:64]


def is_group(conv: dict) -> bool:
    return "@g.us" in conv.get("chat", {}).get("remoteJid", "")


# ══════════════════════════════════════════════════════════════════════════════
# Checkpoint
# ══════════════════════════════════════════════════════════════════════════════

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(
        json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 1 — Validacao da estrutura
# ══════════════════════════════════════════════════════════════════════════════

def validate_structure(conversations: list[dict]) -> None:
    """Le as 5 primeiras conversas e imprime a estrutura real encontrada."""
    print()
    print("=" * 64)
    print("ETAPA 1 — VALIDACAO DA ESTRUTURA DO JSON")
    print("=" * 64)
    print(f"Total de conversas no arquivo : {len(conversations)}")
    total_msgs = sum(len(c.get("messages", [])) for c in conversations)
    print(f"Total de mensagens no arquivo : {total_msgs}")
    print()

    sample = conversations[:5]
    for i, conv in enumerate(sample, 1):
        chat     = conv.get("chat", {})
        messages = conv.get("messages", [])
        phone    = extract_phone(conv)
        name     = extract_name(conv)
        msgs     = extract_messages(conv)

        print(f"  Conversa {i}/{len(sample)}")
        print(f"    remoteJid       : {chat.get('remoteJid', '?')}")
        remote_alt = (
            chat.get("lastMessage", {}).get("key", {}).get("remoteJidAlt", "(nao disponivel)")
        )
        print(f"    remoteJidAlt    : {remote_alt}")
        print(f"    chat.pushName   : {chat.get('pushName') or '(null)'}")
        print(f"    Telefone extrai : {phone or '(NAO EXTRAIDO)'}")
        print(f"    Nome extraido   : {name or '(nao encontrado)'}")
        print(f"    Msgs raw/texto  : {len(messages)} / {len(msgs)}")

        if msgs:
            first = msgs[0]
            last  = msgs[-1]
            dt_f  = datetime.fromtimestamp(first["timestamp"], tz=timezone.utc).strftime("%d/%m/%Y %H:%M")
            dt_l  = datetime.fromtimestamp(last["timestamp"],  tz=timezone.utc).strftime("%d/%m/%Y %H:%M")
            dir_f = "Ana (outgoing)" if first["from_me"] else "Paciente (incoming)"
            print(f"    Periodo         : {dt_f}  ->  {dt_l}")
            print(f"    1a msg [{dir_f}]: {first['text'][:70]!r}")
        print()

    print("Estrutura validada. Campos confirmados:")
    print("  remoteJid, remoteJidAlt, pushName, fromMe, messageTimestamp, text")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 2 — Dry-run
# ══════════════════════════════════════════════════════════════════════════════

def run_dry_run(conversations: list[dict], limit: Optional[int]) -> None:
    print("=" * 64)
    print("ETAPA 2 — DRY-RUN (nenhuma escrita no Chatwoot)")
    print("=" * 64)

    checkpoint = load_checkpoint()
    subset     = conversations[:limit] if limit else conversations

    report: dict = {
        "mode":            "dry-run",
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "total_no_arquivo": len(conversations),
        "processados":    len(subset),
        "resumo": {
            "sem_telefone":  0,
            "bloqueados":    0,
            "grupos":        0,
            "ja_importados": 0,
            "novos":         0,
            "msgs_texto_total": 0,
        },
        "contatos": [],
    }

    for conv in subset:
        chat = conv.get("chat", {})

        if is_group(conv):
            report["resumo"]["grupos"] += 1
            continue

        phone = extract_phone(conv)

        if not phone:
            report["resumo"]["sem_telefone"] += 1
            report["contatos"].append({
                "remoteJid": chat.get("remoteJid"),
                "status":    "sem_telefone",
                "pushName":  chat.get("pushName"),
            })
            continue

        if phone in BLOCKED_PHONES:
            report["resumo"]["bloqueados"] += 1
            continue

        name  = extract_name(conv)
        msgs  = extract_messages(conv)
        h     = phone_hash(phone)

        report["resumo"]["msgs_texto_total"] += len(msgs)

        if phone in checkpoint:
            report["resumo"]["ja_importados"] += 1
            report["contatos"].append({
                "phone":              phone,
                "name":               name or f"Contato {phone}",
                "status":             "ja_importado",
                "chatwoot_contact_id": checkpoint[phone].get("contact_id"),
                "mensagens_texto":    len(msgs),
            })
            continue

        report["resumo"]["novos"] += 1
        report["contatos"].append({
            "phone":           phone,
            "name":            name or f"Contato {phone}",
            "status":          "novo",
            "mensagens_texto": len(msgs),
            "phone_hash":      h,
        })

    RESULTADO_FILE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    r = report["resumo"]
    print()
    print(f"  Conversas no arquivo   : {report['total_no_arquivo']}")
    print(f"  Processadas (subset)   : {report['processados']}")
    print(f"  Grupos (ignorados)     : {r['grupos']}")
    print(f"  Sem telefone           : {r['sem_telefone']}")
    print(f"  Bloqueados             : {r['bloqueados']}")
    print(f"  Ja importados          : {r['ja_importados']}")
    print(f"  Novos para importar    : {r['novos']}")
    print(f"  Total msgs com texto   : {r['msgs_texto_total']}")
    print()
    print(f"  Relatorio salvo em: {RESULTADO_FILE}")
    print()


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 3 — Importacao real
# ══════════════════════════════════════════════════════════════════════════════

def run_import(conversations: list[dict], limit: Optional[int]) -> dict:
    """
    Importa contatos e historico para o Chatwoot.
    Retorna estatisticas da execucao.
    """
    print("=" * 64)
    print("ETAPA 3 — IMPORTACAO REAL")
    print("=" * 64)

    client     = ChatwootClient()
    checkpoint = load_checkpoint()

    # Label desativado: o Chatwoot cria uma mensagem de atividade para cada label.
    if ADD_IMPORT_LABEL:
        client.ensure_label_exists()

    # Filtra conversas validas que ainda nao foram importadas
    to_import: list[dict] = []
    skipped_already = 0

    subset = conversations[:limit] if limit else conversations
    for conv in subset:
        if is_group(conv):
            continue
        phone = extract_phone(conv)
        if not phone or phone in BLOCKED_PHONES:
            continue
        if phone in checkpoint:
            skipped_already += 1
            continue
        to_import.append(conv)

    print(f"\n  {skipped_already} ja importados (checkpoint) — pulados")
    print(f"  {len(to_import)} contatos para importar agora\n")

    if not to_import:
        print("  Nada a fazer.")
        return {"importados": 0, "erros": 0}

    # ── Historico ─────────────────────────────────────────────────────────────
    # Usa sempre uma unica nota privada consolidada. O teste de timestamp criava
    # uma mensagem extra visivel no Chatwoot, entao foi desativado.
    accepts_historical_ts = False
    print("  Usando nota privada consolidada para o historico importado.")

    test_conv  = to_import[0]
    test_phone = extract_phone(test_conv)
    test_name  = extract_name(test_conv) or f"Contato {test_phone}"

    try:
        test_contact    = client.get_or_create_contact(test_phone, test_name)
        test_contact_id = test_contact.get("id")
        test_convo      = client.create_conversation(test_contact_id)
        test_convo_id   = test_convo.get("id")

        # Ja importa as mensagens reais desta primeira conversa
        test_msgs = extract_messages(test_conv)
        note = format_note(test_msgs, test_phone)
        client.create_note(test_convo_id, note)

        # Salva no checkpoint
        checkpoint[test_phone] = {
            "contact_id":      test_contact_id,
            "conversation_id": test_convo_id,
            "name":            test_name,
            "message_count":   len(test_msgs),
            "imported_at":     datetime.now(tz=timezone.utc).isoformat(),
        }
        save_checkpoint(checkpoint)

        # Remove da lista (ja foi processada)
        to_import = to_import[1:]

        print("  OK — nota privada consolidada criada")

    except Exception as e:
        print(f"  Aviso no teste: {e}")
        print("  Continuando com nota privada por seguranca...")

    # ── Loop principal ────────────────────────────────────────────────────────
    imported = 0
    errors   = 0

    for conv in to_import:
        phone = extract_phone(conv)
        name  = extract_name(conv) or f"Contato {phone}"
        msgs  = extract_messages(conv)

        print(f"  -> {phone} | {name!r} | {len(msgs)} msgs de texto")

        try:
            # 1. Contato
            contact    = client.get_or_create_contact(phone, name)
            contact_id = contact.get("id")

            # 2. Conversa — evita duplicata se contato ja tem conversa importada
            existing_conv_id = client.get_existing_imported_conversation(contact_id)
            if existing_conv_id:
                print(f"     (conversa importada ja existe: {existing_conv_id} — salvando no checkpoint)")
                checkpoint[phone] = {
                    "contact_id":      contact_id,
                    "conversation_id": existing_conv_id,
                    "name":            name,
                    "message_count":   len(msgs),
                    "imported_at":     datetime.now(tz=timezone.utc).isoformat(),
                    "recovered":       True,
                }
                save_checkpoint(checkpoint)
                imported += 1
                continue

            convo    = client.create_conversation(contact_id)
            convo_id = convo.get("id")

            # 3. Label
            if ADD_IMPORT_LABEL:
                client.add_label(convo_id, IMPORT_LABEL)

            # 4. Historico
            note = format_note(msgs, phone)
            client.create_note(convo_id, note)

            # 5. Checkpoint
            checkpoint[phone] = {
                "contact_id":      contact_id,
                "conversation_id": convo_id,
                "name":            name,
                "message_count":   len(msgs),
                "imported_at":     datetime.now(tz=timezone.utc).isoformat(),
            }
            save_checkpoint(checkpoint)

            imported += 1
            print(f"     OK contact_id={contact_id} conversation_id={convo_id}")

        except httpx.HTTPStatusError as e:
            print(f"     ERRO HTTP {e.response.status_code}: {e.response.text[:120]}")
            errors += 1

        except Exception as e:
            print(f"     ERRO: {e}")
            errors += 1

        time.sleep(0.5)  # 500ms entre conversas

    stats = {"importados": imported + (1 if accepts_historical_ts is not None else 0), "erros": errors}
    print(f"\n  Importados : {imported}  |  Erros : {errors}")
    return stats


# ══════════════════════════════════════════════════════════════════════════════
# ETAPA 4 — Pre-carregamento do Redis
# ══════════════════════════════════════════════════════════════════════════════

def preload_redis() -> None:
    """
    Para cada telefone no checkpoint, verifica no Dietbox se o paciente
    tem consulta ativa e pre-carrega o estado inicial no Redis.
    Nao sobrescreve estados existentes.
    """
    print()
    print("=" * 64)
    print("ETAPA 4 — PRE-CARREGAMENTO DO REDIS")
    print("=" * 64)

    # Importa redis
    try:
        import redis as redis_lib
    except ImportError:
        print("  ERRO: biblioteca 'redis' nao instalada.")
        print("  Instale com: pip install redis")
        return

    # Conecta no Redis
    try:
        r = redis_lib.Redis.from_url(REDIS_URL, decode_responses=True)
        r.ping()
        print(f"  Redis conectado: {REDIS_URL}")
    except Exception as e:
        print(f"  ERRO ao conectar no Redis: {e}")
        return

    # Importa funcoes do Dietbox
    sys.path.insert(0, str(ROOT))
    try:
        from app.agents.dietbox_worker import (
            buscar_paciente_por_telefone,
            consultar_agendamento_ativo,
        )
        dietbox_ok = True
        print("  Modulo Dietbox carregado.")
    except ImportError as e:
        print(f"  Aviso: Dietbox indisponivel ({e})")
        print("  Pre-carga sera feita com dados basicos do checkpoint (sem consulta ativa).")
        dietbox_ok = False

    checkpoint = load_checkpoint()
    if not checkpoint:
        print("  Checkpoint vazio. Rode --apply primeiro.")
        return

    seeded = 0
    skipped = 0
    erros = 0

    for phone, dados in checkpoint.items():
        key = f"conv_state:{phone_hash(phone)}"

        # Nao sobrescreve estado ativo existente
        if r.exists(key):
            skipped += 1
            continue

        nome = dados.get("name", "")

        # Tenta buscar dados do Dietbox
        id_paciente = None
        plano       = None
        consulta    = None

        if dietbox_ok:
            try:
                paciente = buscar_paciente_por_telefone(phone)
                if paciente:
                    id_paciente = paciente.get("id")
                    plano       = paciente.get("plano")
                    nome        = nome or paciente.get("nome", "")
                    agenda      = consultar_agendamento_ativo(id_paciente=int(id_paciente)) if id_paciente else None
                    if agenda:
                        consulta = agenda
                    else:
                        # Sem consulta ativa — nao precarregar (paciente nao e retorno)
                        continue
            except Exception as e:
                print(f"  Aviso Dietbox ({phone}): {e}")

        state = {
            "_tipo":      "conversation",
            "phone_hash": phone_hash(phone),
            "phone":      phone,
            "goal":       "remarcar",
            "status":     "coletando",
            "collected_data": {
                "nome":               nome or None,
                "status_paciente":    "retorno",
                "objetivo":           None,
                "plano":              plano,
                "modalidade":         None,
                "preferencia_horario": None,
                "forma_pagamento":    None,
                "data_nascimento":    None,
                "email":              None,
                "telefone_contato":   None,
                "instagram":          None,
                "profissao":          None,
                "cep_endereco":       None,
                "indicacao_origem":   None,
                "motivo_cancelamento": None,
            },
            "appointment": {
                "slot_escolhido":  None,
                "id_paciente":     id_paciente,
                "id_agenda":       consulta.get("id") if consulta else None,
                "id_transacao":    None,
                "consulta_atual":  consulta,
            },
            "flags": {
                "upsell_oferecido":           False,
                "planos_enviados":            False,
                "pagamento_confirmado":        False,
                "aguardando_motivo_cancel":    False,
                "aguardando_escolha_telefone": False,
                "telefone_opcoes":             [],
            },
            "last_action":        None,
            "last_tool_success":  None,
            "last_slots_offered": [],
            "slots_pool":         [],
            "rodada_negociacao":  0,
            "remarcacoes_count":  0,
            "tipo_remarcacao":    None,
            "fim_janela_remarcar": None,
            "link_pagamento":     None,
            "history":            [],
        }

        try:
            r.set(key, json.dumps(state, ensure_ascii=False, default=str))
            seeded += 1
            print(f"  OK {nome or phone} ({phone}) — id_paciente={id_paciente}")
        except Exception as e:
            print(f"  ERRO ao salvar Redis para {phone}: {e}")
            erros += 1

    print()
    print(f"  Pre-carregados : {seeded}")
    print(f"  Ja existiam    : {skipped}")
    print(f"  Erros          : {erros}")


# ══════════════════════════════════════════════════════════════════════════════
# Correcao de nomes
# ══════════════════════════════════════════════════════════════════════════════

def update_names(conversations: list[dict]) -> None:
    """
    Revisa todos os contatos do checkpoint e atualiza o Chatwoot com:
      - nome identificado no historico, quando houver sinal confiavel;
      - "Sem nome 001", "Sem nome 002"... quando nao houver nome confiavel.
    Tambem atualiza o checkpoint com o nome final.
    """
    print()
    print("=" * 64)
    print("CORRECAO DE NOMES — revisando contatos importados no Chatwoot")
    print("=" * 64)

    client     = ChatwootClient()
    checkpoint = load_checkpoint()

    # Indexa conversas por telefone para busca rapida
    conv_by_phone: dict[str, dict] = {}
    for conv in conversations:
        phone = extract_phone(conv)
        if phone:
            conv_by_phone[phone] = conv

    to_review = {
        phone: dados
        for phone, dados in checkpoint.items()
        if phone not in BLOCKED_PHONES
        and "nutricionista thaynara" not in (dados.get("name") or "").lower()
    }

    print(f"  Contatos no checkpoint para revisar: {len(to_review)}")
    print()

    updated = 0
    unchanged = 0
    nao_encontrado = 0
    sem_nome_no_historico = 0
    sem_nome_index = 1

    for phone in sorted(to_review):
        dados = to_review[phone]
        conv = conv_by_phone.get(phone)
        current_name = (dados.get("name") or "").strip()
        if not conv:
            nao_encontrado += 1
            continue

        extracted_name = extract_name(conv)
        if extracted_name:
            desired_name = extracted_name
        else:
            desired_name = nameless_label(sem_nome_index)
            sem_nome_index += 1
            sem_nome_no_historico += 1

        # Mantem nomes atuais que ja parecem melhores que uma ausencia de nome.
        if not extracted_name and not _is_suspicious_name(current_name, phone):
            unchanged += 1
            continue

        if current_name == desired_name:
            unchanged += 1
            continue

        contact_id = dados.get("contact_id")
        if not contact_id:
            continue

        try:
            client.update_contact_name(contact_id, desired_name)
            checkpoint[phone]["name"] = desired_name
            save_checkpoint(checkpoint)
            updated += 1
            print(f"  OK {phone} | {current_name!r} -> {desired_name!r}")
        except Exception as e:
            print(f"  ERRO {phone}: {e}")

        time.sleep(0.15)  # 150ms entre patches

    print()
    print(f"  Nomes atualizados       : {updated}")
    print(f"  Ja estavam adequados    : {unchanged}")
    print(f"  Sem nome no historico   : {sem_nome_no_historico}")
    print(f"  Nao encontrados no JSON : {nao_encontrado}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa historico Evolution API -> Chatwoot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python scripts/importar_chatwoot.py                       # dry-run completo
  python scripts/importar_chatwoot.py --dry-run --limit 20  # simula 20 contatos
  python scripts/importar_chatwoot.py --limit 3 --apply     # importa 3 contatos
  python scripts/importar_chatwoot.py --apply               # importa tudo (confirma antes)
  python scripts/importar_chatwoot.py --redis-preload       # so precarrega Redis
        """,
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Simula sem escrever nada no Chatwoot (padrao se nenhuma flag)",
    )
    parser.add_argument(
        "--apply", action="store_true", default=False,
        help="Executa importacao real",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Processa apenas os primeiros N contatos",
    )
    parser.add_argument(
        "--redis-preload", action="store_true", default=False,
        help="Pre-carrega estados do Redis para pacientes do Dietbox (requer --apply feito antes)",
    )
    parser.add_argument(
        "--yes", action="store_true", default=False,
        help="Confirma automaticamente todas as perguntas interativas (uso em scripts/CI)",
    )
    parser.add_argument(
        "--update-names", action="store_true", default=False,
        help="Corrige nomes de contatos importados com numero como nome (usa PATCH no Chatwoot)",
    )
    args = parser.parse_args()

    # Padrao: dry-run se nenhuma flag de execucao
    if not args.dry_run and not args.apply and not args.redis_preload and not args.update_names:
        args.dry_run = True

    # Valida variaveis criticas — so bloqueia no --apply (dry-run nao precisa)
    if args.apply and not args.redis_preload:
        if not CHATWOOT_URL or not CHATWOOT_TOKEN:
            print("ERRO: CHATWOOT_API_URL e CHATWOOT_API_TOKEN devem estar no .env")
            sys.exit(1)

    # Carrega o JSON
    if not EXPORT_FILE.exists():
        print(f"ERRO: {EXPORT_FILE} nao encontrado.")
        print("Execute o script a partir da raiz do projeto.")
        sys.exit(1)

    print(f"Carregando {EXPORT_FILE} ...")
    try:
        data          = json.loads(EXPORT_FILE.read_text(encoding="utf-8"))
        conversations = data.get("conversations", [])
    except Exception as e:
        print(f"ERRO ao ler JSON: {e}")
        sys.exit(1)

    print(f"  {len(conversations)} conversas carregadas.")

    # ── ETAPA 1: sempre roda ──────────────────────────────────────────────────
    validate_structure(conversations)

    # ── Apenas Redis preload ──────────────────────────────────────────────────
    if args.redis_preload and not args.apply and not args.dry_run and not args.update_names:
        preload_redis()
        return

    # ── Correcao de nomes ─────────────────────────────────────────────────────
    if args.update_names:
        update_names(conversations)
        return

    # ── Dry-run ───────────────────────────────────────────────────────────────
    if args.dry_run:
        run_dry_run(conversations, args.limit)
        print("Dry-run concluido.")
        print("Proximo passo: python scripts/importar_chatwoot.py --limit 3 --apply")
        return

    # ── Apply ─────────────────────────────────────────────────────────────────
    if args.apply:
        if not args.limit:
            # Importacao total: exige confirmacao explicita
            checkpoint    = load_checkpoint()
            ja_importados = len(checkpoint)
            pendentes     = sum(
                1 for c in conversations
                if not is_group(c)
                and extract_phone(c) not in BLOCKED_PHONES
                and extract_phone(c) is not None
                and extract_phone(c) not in checkpoint
            )
            print("=" * 64)
            print("ATENCAO: importacao sem --limit")
            print(f"  Ja importados (checkpoint) : {ja_importados}")
            print(f"  Pendentes estimados        : {pendentes}")
            print()
            print("  Para continuar, digite exatamente: CONFIRMAR  (ou use --yes para pular)")
            if args.yes:
                print("  > CONFIRMAR  [--yes ativo]")
            else:
                resp = input("  > ").strip()
                if resp != "CONFIRMAR":
                    print("Importacao cancelada.")
                    sys.exit(0)
            print()

        run_import(conversations, args.limit)

        if args.limit:
            # Pausa para validacao visual antes de continuar
            print()
            print("=" * 64)
            print("Valida os contatos importados no Chatwoot.")
            print("Confirma para continuar com o lote completo.")
            print("  (s = continuar | qualquer outra tecla = encerrar | --yes para pular)")
            if args.yes:
                resp = "s"
                print("  > s  [--yes ativo]")
            else:
                resp = input("  > ").strip().lower()
            if resp == "s":
                print()
                print("Continuando com lote completo...")
                if not args.yes:
                    print("  Digite CONFIRMAR para importar todos os contatos restantes:")
                    resp2 = input("  > ").strip()
                    if resp2 != "CONFIRMAR":
                        print("Lote completo cancelado.")
                        sys.exit(0)
                run_import(conversations, limit=None)
                preload_redis()
            else:
                print("Encerrado. Rode sem --limit quando estiver pronto.")
        else:
            # Pos-importacao total: oferece preload Redis
            print()
            if args.yes:
                print("Redis preload pulado (--yes ativo). Rode --redis-preload separadamente.")
            else:
                print("Deseja pre-carregar o Redis com pacientes do Dietbox? (s/N)")
                resp = input("  > ").strip().lower()
                if resp == "s":
                    preload_redis()


if __name__ == "__main__":
    main()
