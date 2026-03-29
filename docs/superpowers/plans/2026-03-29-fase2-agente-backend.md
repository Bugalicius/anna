# Fase 2 — Agente Backend FastAPI + Meta API + Remarketing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend FastAPI em Docker que recebe webhooks da Meta Cloud API, roteia mensagens entre fluxos fixos e IA (Gemini 2.0 Flash / Claude Haiku fallback), e dispara remarketing automatizado por tempo e comportamento via APScheduler com persistência no PostgreSQL.

**Architecture:** FastAPI com background tasks para processamento assíncrono de webhooks; APScheduler com SQLAlchemyJobStore para remarketing persistente; Redis para rate limiting da Meta API; PostgreSQL para estado de conversas, mensagens e fila de remarketing.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic (migrações), APScheduler 3.x, `google-generativeai`, `anthropic` SDK, `httpx`, Redis (`redis-py`), `pytest` + `httpx` TestClient, Docker Compose, Nginx

---

## Pré-requisito

Este plano assume que a **Fase 1 foi concluída** e o arquivo `knowledge_base/system_prompt.md` existe.

---

## Mapa de Arquivos

| Arquivo | Responsabilidade |
|---|---|
| `app/models.py` | SQLAlchemy ORM: Contact, Conversation, Message, RemarketingQueue |
| `app/database.py` | Engine, SessionLocal, Base |
| `app/meta_api.py` | Wrapper Meta Cloud API (send_text, send_template, verify_signature) |
| `app/webhook.py` | Handler POST /webhook: assinatura, dedup, background task |
| `app/router.py` | Decide fluxo fixo vs IA baseado no stage |
| `app/flows.py` | Respostas de fluxo fixo por stage |
| `app/ai_engine.py` | Gemini JSON forçado + fallback Claude Haiku |
| `app/remarketing.py` | APScheduler + fila + rate limiter Redis |
| `app/retry.py` | Job periódico de reprocessamento de mensagens falhas |
| `app/main.py` | FastAPI app, lifespan, roteamento de endpoints |
| `scripts/migrate_contacts.py` | Importa 1.018 contatos do PostgreSQL da Evolution |
| `alembic/` | Migrações do banco |
| `docker-compose.yml` | Serviços: app, postgres, redis, nginx |
| `.env.example` | Todas as variáveis necessárias |
| `nginx/nginx.conf` | Reverse proxy com HTTPS |
| `tests/test_models.py` | Testes dos modelos ORM |
| `tests/test_meta_api.py` | Testes do wrapper Meta (mock HTTP) |
| `tests/test_webhook.py` | Testes de assinatura + dedup |
| `tests/test_router.py` | Testes de roteamento por stage |
| `tests/test_flows.py` | Testes dos fluxos fixos |
| `tests/test_ai_engine.py` | Testes do AI engine (mock Gemini/Claude) |
| `tests/test_remarketing.py` | Testes de fila e proteções anti-spam |
| `tests/test_retry.py` | Testes de retry com backoff exponencial |
| `templates/` | Templates HSM (placeholders para aprovação Meta) |

---

## Task 1: Estrutura do Projeto + Docker Compose

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `app/__init__.py`
- Create: `requirements.txt`

- [ ] **Step 1: Criar `requirements.txt`**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
alembic==1.13.3
psycopg2-binary==2.9.9
apscheduler==3.10.4
redis==5.0.8
httpx[test]==0.27.0
google-generativeai==0.8.6
anthropic>=0.50.0
python-dotenv==1.0.1
pytest==8.3.2
pytest-asyncio==0.24.0
respx==0.22.0
```

- [ ] **Step 2: Criar `.env.example`**

```
# Meta Cloud API
META_ACCESS_TOKEN=seu_token_aqui
META_PHONE_NUMBER_ID=seu_phone_number_id
META_APP_SECRET=seu_app_secret
META_VERIFY_TOKEN=token_webhook_verificacao

# LLMs
GEMINI_API_KEY=sua_chave_gemini
CLAUDE_API_KEY=sua_chave_claude

# Database
DATABASE_URL=postgresql://agente:agente123@postgres:5432/agente_ana

# Redis
REDIS_URL=redis://redis:6379/0

# App
SECRET_KEY=troque-por-uma-string-aleatoria-longa
```

- [ ] **Step 3: Criar `docker-compose.yml`**

```yaml
services:
  app:
    build: .
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./knowledge_base:/app/knowledge_base:ro

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: agente
      POSTGRES_PASSWORD: agente123
      POSTGRES_DB: agente_ana
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U agente"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - certbot_www:/var/www/certbot:ro
      - certbot_conf:/etc/letsencrypt:ro
    depends_on:
      - app

volumes:
  pgdata:
  redisdata:
  certbot_www:
  certbot_conf:
```

- [ ] **Step 4: Criar `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 5: Criar `nginx/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name _;
    ssl_certificate /etc/letsencrypt/live/SEU_DOMINIO/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/SEU_DOMINIO/privkey.pem;

    location /webhook {
        proxy_pass http://app:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 10s;
    }
}
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example Dockerfile requirements.txt nginx/
git commit -m "chore: estrutura do projeto + Docker Compose"
```

---

## Task 2: Modelos do Banco (SQLAlchemy + Alembic)

**Files:**
- Create: `app/database.py`
- Create: `app/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_models.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, Conversation, Message, RemarketingQueue

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

def test_create_contact(db):
    contact = Contact(phone_hash="abc123", push_name="Maria", stage="new")
    db.add(contact)
    db.commit()
    assert contact.id is not None
    assert contact.remarketing_count == 0

def test_contact_stage_values(db):
    valid_stages = ["new", "collecting_info", "presenting", "scheduling",
                    "awaiting_payment", "confirmed", "cold_lead",
                    "remarketing_sequence", "archived"]
    for stage in valid_stages:
        c = Contact(phone_hash=f"hash_{stage}", stage=stage)
        db.add(c)
    db.commit()
    assert db.query(Contact).count() == len(valid_stages)

def test_message_dedup_by_meta_id(db):
    contact = Contact(phone_hash="h1", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()
    msg = Message(meta_message_id="META_MSG_001", conversation_id=conv.id,
                  direction="inbound", content="oi", message_type="text",
                  processing_status="pending")
    db.add(msg)
    db.commit()
    # Deve ter constraint UNIQUE em meta_message_id
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        msg2 = Message(meta_message_id="META_MSG_001", conversation_id=conv.id,
                       direction="inbound", content="oi2", message_type="text")
        db.add(msg2)
        db.commit()

def test_remarketing_queue_counts_flag(db):
    contact = Contact(phone_hash="h2", stage="cold_lead")
    db.add(contact)
    db.flush()
    rq = RemarketingQueue(contact_id=contact.id, template_name="follow_up_geral",
                          status="pending", sequence_position=1,
                          trigger_type="time", counts_toward_limit=True)
    db.add(rq)
    db.commit()
    assert rq.counts_toward_limit is True
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_models.py -v
```

- [ ] **Step 3: Implementar `app/database.py`**

```python
# app/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./test.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4: Implementar `app/models.py`**

```python
# app/models.py
import uuid
from datetime import datetime, UTC
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

def _uuid() -> str:
    return str(uuid.uuid4())

def _now() -> datetime:
    return datetime.now(UTC)


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    phone_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(String(20))  # número real para envio Meta API
    push_name: Mapped[str | None] = mapped_column(String(255))
    stage: Mapped[str] = mapped_column(String(50), default="new")
    collected_name: Mapped[str | None] = mapped_column(String(255))
    patient_type: Mapped[str | None] = mapped_column(String(50))
    interest_score: Mapped[int | None] = mapped_column(Integer)
    remarketing_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="contact")
    remarketing_queue: Mapped[list["RemarketingQueue"]] = relationship(back_populates="contact")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(50), default="new")
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str] = mapped_column(String(50), default="em_aberto")
    # outcome valores: converteu | abandonou | agendou | arquivou | em_aberto

    contact: Mapped["Contact"] = relationship(back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(back_populates="conversation",
                                                      order_by="Message.sent_at")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("meta_message_id", name="uq_meta_message_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meta_message_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"))
    direction: Mapped[str] = mapped_column(String(10))  # inbound | outbound
    content: Mapped[str] = mapped_column(Text)
    message_type: Mapped[str] = mapped_column(String(20), default="text")
    processing_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending → retrying (1ª falha) → retrying (2ª) → failed (3ª) | processed (sucesso)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class RemarketingQueue(Base):
    __tablename__ = "remarketing_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False)
    template_name: Mapped[str] = mapped_column(String(100))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending | sent | cancelled | failed
    sequence_position: Mapped[int] = mapped_column(Integer, default=1)
    trigger_type: Mapped[str] = mapped_column(String(20))  # time | behavior
    counts_toward_limit: Mapped[bool] = mapped_column(Boolean, default=True)

    contact: Mapped["Contact"] = relationship(back_populates="remarketing_queue")
```

- [ ] **Step 5: Rodar testes**

```bash
python -m pytest tests/test_models.py -v
```
Esperado: 4 testes PASS.

- [ ] **Step 6: Criar e rodar migração inicial (Alembic)**

```bash
alembic init alembic
```

Substituir o conteúdo de `alembic/env.py` com:

```python
# alembic/env.py
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

load_dotenv()

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importar Base DEPOIS de carregar o .env
from app.database import Base
import app.models  # garante que todos os modelos são registrados
target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

```bash
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

- [ ] **Step 7: Commit**

```bash
git add app/database.py app/models.py tests/test_models.py alembic/
git commit -m "feat: modelos SQLAlchemy + migração inicial"
```

---

## Task 3: Meta API Wrapper

**Files:**
- Create: `app/meta_api.py`
- Create: `tests/test_meta_api.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_meta_api.py
import hashlib
import hmac
import json
import pytest
import respx
import httpx
from app.meta_api import MetaAPIClient, verify_signature

PHONE_ID = "123456789"
TOKEN = "test-token"
APP_SECRET = "my-secret"

@pytest.fixture
def client():
    return MetaAPIClient(phone_number_id=PHONE_ID, access_token=TOKEN)

def test_verify_signature_valid():
    body = b'{"test": "data"}'
    sig = "sha256=" + hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert verify_signature(body, sig, APP_SECRET) is True

def test_verify_signature_invalid():
    body = b'{"test": "data"}'
    assert verify_signature(body, "sha256=invalido", APP_SECRET) is False

def test_verify_signature_missing_prefix():
    body = b'{"test": "data"}'
    assert verify_signature(body, "sem-prefixo", APP_SECRET) is False

@respx.mock
def test_send_text_calls_meta_api(client):
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.abc"}]}))

    result = client.send_text(to="5531999999999", text="Olá!")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["to"] == "5531999999999"
    assert payload["text"]["body"] == "Olá!"

@respx.mock
def test_send_template_calls_meta_api(client):
    route = respx.post(
        f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
    ).mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.xyz"}]}))

    client.send_template(to="5531999999999", template_name="follow_up_geral", language="pt_BR")
    assert route.called
    payload = json.loads(route.calls[0].request.content)
    assert payload["type"] == "template"
    assert payload["template"]["name"] == "follow_up_geral"
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_meta_api.py -v
```

- [ ] **Step 3: Implementar `app/meta_api.py`**

```python
# app/meta_api.py
import hashlib
import hmac
import httpx

META_API_BASE = "https://graph.facebook.com/v19.0"


def verify_signature(body: bytes, signature: str, app_secret: str) -> bool:
    """Valida X-Hub-Signature-256 da Meta."""
    if not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class MetaAPIClient:
    def __init__(self, phone_number_id: str, access_token: str):
        self._phone_id = phone_number_id
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def send_text(self, to: str, text: str) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }
        return self._post(payload)

    def send_template(self, to: str, template_name: str, language: str = "pt_BR",
                      components: list | None = None) -> dict:
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
                **({"components": components} if components else {}),
            },
        }
        return self._post(payload)

    def _post(self, payload: dict) -> dict:
        url = f"{META_API_BASE}/{self._phone_id}/messages"
        with httpx.Client(headers=self._headers, timeout=10) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_meta_api.py -v
```
Esperado: 5 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add app/meta_api.py tests/test_meta_api.py
git commit -m "feat: Meta Cloud API wrapper com verificação de assinatura"
```

---

## Task 4: Webhook Handler (Assinatura + Deduplicação)

**Files:**
- Create: `app/webhook.py`
- Create: `tests/test_webhook.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_webhook.py
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

APP_SECRET = "test-secret"
VERIFY_TOKEN = "test-verify-token"

# Montar app mínima para testes
from fastapi import FastAPI
app = FastAPI()

from app.webhook import router as webhook_router
app.include_router(webhook_router)

client = TestClient(app)

def make_signature(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

def test_webhook_verification_challenge():
    with patch("app.webhook.VERIFY_TOKEN", VERIFY_TOKEN):
        response = client.get("/webhook", params={
            "hub.mode": "subscribe",
            "hub.verify_token": VERIFY_TOKEN,
            "hub.challenge": "CHALLENGE_CODE",
        })
    assert response.status_code == 200
    assert response.text == "CHALLENGE_CODE"

def test_invalid_signature_returns_403():
    body = b'{"object":"whatsapp_business_account","entry":[]}'
    response = client.post(
        "/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=assinatura_invalida",
        },
    )
    assert response.status_code == 403

def test_valid_empty_payload_returns_200():
    body = json.dumps({
        "object": "whatsapp_business_account",
        "entry": []
    }).encode()
    sig = make_signature(body, APP_SECRET)

    with patch("app.webhook.APP_SECRET", APP_SECRET):
        response = client.post(
            "/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
        )
    assert response.status_code == 200
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_webhook.py -v
```

- [ ] **Step 3: Implementar `app/webhook.py`**

```python
# app/webhook.py
import logging
import os
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from app.meta_api import verify_signature

router = APIRouter()
logger = logging.getLogger(__name__)

APP_SECRET = os.environ.get("META_APP_SECRET", "")
VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "")


@router.get("/webhook")
async def verify_webhook(request: Request):
    """Meta verifica o endpoint ao configurar o webhook."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """Recebe mensagens da Meta. Retorna 200 imediatamente, processa em background."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_signature(body, signature, APP_SECRET):
        raise HTTPException(status_code=403, detail="Invalid signature")

    import json as _json
    payload = _json.loads(body)  # usar body já lido, não re-ler o stream

    # Extrair mensagens do payload aninhado da Meta
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                background_tasks.add_task(process_message, message, value.get("metadata", {}))

    return {"status": "ok"}


async def process_message(message: dict, metadata: dict):
    """Processa uma mensagem em background. Deduplicação + roteamento."""
    from app.database import SessionLocal
    from app.models import Message, Contact, Conversation
    from app.router import route_message
    import hashlib
    from datetime import datetime, UTC

    meta_id = message.get("id", "")
    phone = message.get("from", "")
    text = message.get("text", {}).get("body", "") or "[mídia]"

    with SessionLocal() as db:
        # Deduplicação: se já existe, ignora
        existing = db.query(Message).filter_by(meta_message_id=meta_id).first()
        if existing:
            logger.debug(f"Mensagem duplicada ignorada: {meta_id}")
            return

        # Buscar ou criar contato (usando hash do phone; phone_e164 salvo para uso no remarketing)
        phone_hash = hashlib.sha256(phone.encode()).hexdigest()[:64]
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            contact = Contact(
                phone_hash=phone_hash,
                phone_e164=phone,  # número real, necessário para Meta API
                push_name=message.get("profile", {}).get("name"),
                stage="new",
            )
            db.add(contact)
            db.flush()

        # Buscar ou criar conversa ativa
        conversation = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id, outcome="em_aberto")
            .order_by(Conversation.opened_at.desc())
            .first()
        )
        if not conversation:
            conversation = Conversation(contact_id=contact.id, stage=contact.stage)
            db.add(conversation)
            db.flush()

        # Registrar mensagem
        msg = Message(
            meta_message_id=meta_id,
            conversation_id=conversation.id,
            direction="inbound",
            content=text,
            processing_status="pending",
        )
        db.add(msg)
        db.commit()

    # Rotear e responder (fora do session para evitar lock longo)
    await route_message(phone=phone, phone_hash=phone_hash, text=text, meta_message_id=meta_id)
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_webhook.py -v
```
Esperado: 3 testes PASS (o teste de challenge pode precisar de ajuste por env).

- [ ] **Step 5: Commit**

```bash
git add app/webhook.py tests/test_webhook.py
git commit -m "feat: webhook handler com verificação X-Hub-Signature-256 e deduplicação"
```

---

## Task 5: Router (Fluxo Fixo vs IA)

**Files:**
- Create: `app/router.py`
- Create: `tests/test_router.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_router.py
import pytest
from unittest.mock import AsyncMock, patch
from app.router import decide_route, FIXED_FLOW_STAGES

def test_new_stage_routes_to_flow():
    assert decide_route("new") == "flow"

def test_awaiting_payment_routes_to_flow():
    assert decide_route("awaiting_payment") == "flow"

def test_scheduling_routes_to_flow():
    assert decide_route("scheduling") == "flow"

def test_confirmed_routes_to_flow():
    assert decide_route("confirmed") == "flow"

def test_presenting_routes_to_ai():
    assert decide_route("presenting") == "ai"

def test_collecting_info_routes_to_ai():
    assert decide_route("collecting_info") == "ai"

def test_cold_lead_routes_to_ai():
    assert decide_route("cold_lead") == "ai"

def test_archived_routes_to_flow():
    # Contatos arquivados não devem receber resposta de IA
    assert decide_route("archived") == "flow"

def test_all_fixed_stages():
    for stage in FIXED_FLOW_STAGES:
        assert decide_route(stage) == "flow"
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_router.py -v
```

- [ ] **Step 3: Implementar `app/router.py`**

```python
# app/router.py
import logging
from app.database import SessionLocal
from app.models import Contact
import hashlib

logger = logging.getLogger(__name__)

FIXED_FLOW_STAGES = {"new", "awaiting_payment", "scheduling", "confirmed", "archived"}


def decide_route(stage: str) -> str:
    """Retorna 'flow' ou 'ai' baseado no stage do contato."""
    return "flow" if stage in FIXED_FLOW_STAGES else "ai"


async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str):
    """Busca o contato, decide o roteamento e despacha para flow ou AI engine."""
    from app.flows import handle_flow
    from app.ai_engine import handle_ai
    from app.remarketing import cancel_pending_remarketing
    from datetime import datetime, UTC

    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if not contact:
            logger.error(f"Contato não encontrado para hash {phone_hash}")
            return

        stage = contact.stage
        contact_id = contact.id

        # Se estava em cold_lead ou remarketing_sequence, retoma presenting
        if stage in ("cold_lead", "remarketing_sequence"):
            contact.stage = "presenting"
            stage = "presenting"
            db.commit()
            cancel_pending_remarketing(db, contact_id)

        contact.last_message_at = datetime.now(UTC)
        db.commit()

    route = decide_route(stage)

    if route == "flow":
        await handle_flow(phone=phone, phone_hash=phone_hash, stage=stage, text=text)
    else:
        await handle_ai(phone=phone, phone_hash=phone_hash, stage=stage, text=text)
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_router.py -v
```
Esperado: 9 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add app/router.py tests/test_router.py
git commit -m "feat: router híbrido por stage com transição cold_lead → presenting"
```

---

## Task 6: Flows Engine (Fluxos Fixos)

**Files:**
- Create: `app/flows.py`
- Create: `tests/test_flows.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_flows.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.flows import get_flow_response, FLOWS

def test_new_stage_returns_welcome_message():
    response = get_flow_response("new", "oi")
    assert response is not None
    assert "Ana" in response or "Thaynara" in response

def test_awaiting_payment_returns_pix_info():
    response = get_flow_response("awaiting_payment", "")
    assert response is not None
    assert "PIX" in response or "pix" in response.lower() or "comprovante" in response.lower()

def test_scheduling_returns_available_times():
    response = get_flow_response("scheduling", "")
    assert response is not None
    # Deve conter horários
    assert any(h in response for h in ["08h", "9h", "10h", "15h", "16h", "17h", "18h", "19h"])

def test_confirmed_returns_confirmation():
    response = get_flow_response("confirmed", "")
    assert response is not None
    assert len(response) > 20

def test_archived_returns_none():
    response = get_flow_response("archived", "")
    assert response is None
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_flows.py -v
```

- [ ] **Step 3: Implementar `app/flows.py`**

```python
# app/flows.py
import logging
import os

logger = logging.getLogger(__name__)

FLOWS: dict[str, str] = {
    "new": (
        "Olá! Que bom ter você por aqui 💚\n\n"
        "Sou a Ana, responsável pelos agendamentos da nutricionista Thaynara Teixeira.\n\n"
        "Pra começar, você poderia me informar:\n"
        " • Qual seu nome e sobrenome?\n"
        " • É sua primeira consulta ou você já é paciente?"
    ),
    "awaiting_payment": (
        "Para confirmar seu agendamento, é necessário realizar o pagamento antecipado:\n\n"
        "• *PIX*: sinal de 50% do valor\n"
        "• *Cartão*: pagamento integral (parcelamento disponível)\n\n"
        "Me informe qual opção prefere para eu providenciar o necessário. 👇"
    ),
    "scheduling": (
        "Para seguirmos com o agendamento, qual horário atende melhor à sua rotina?\n\n"
        "*Segunda a Sexta-feira:*\n"
        "Manhã: 08h, 09h e 10h\n"
        "Tarde: 15h, 16h e 17h\n"
        "Noite: 18h e 19h _(exceto sexta à noite)_"
    ),
    "confirmed": (
        "✅ Agendamento confirmado!\n\n"
        "Em breve a Thaynara entrará em contato com as orientações para sua consulta.\n"
        "Qualquer dúvida, pode me chamar aqui! 💚"
    ),
    "archived": None,  # Não responde
}


def get_flow_response(stage: str, text: str) -> str | None:
    return FLOWS.get(stage)


async def handle_flow(phone: str, phone_hash: str, stage: str, text: str):
    """Envia resposta do fluxo fixo e atualiza stage se necessário."""
    from app.meta_api import MetaAPIClient
    from app.database import SessionLocal
    from app.models import Contact
    import os

    response_text = get_flow_response(stage, text)
    if response_text is None:
        return

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("META_ACCESS_TOKEN", ""),
    )
    meta.send_text(to=phone, text=response_text)

    # Avançar stage após boas-vindas
    if stage == "new":
        with SessionLocal() as db:
            contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if contact:
                contact.stage = "collecting_info"
                db.commit()
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_flows.py -v
```
Esperado: 5 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add app/flows.py tests/test_flows.py
git commit -m "feat: flows engine com respostas fixas por stage"
```

---

## Task 7: AI Engine (Gemini + Claude Fallback)

**Files:**
- Create: `app/ai_engine.py`
- Create: `tests/test_ai_engine.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_ai_engine.py
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.ai_engine import AIEngine, parse_gemini_response, VALID_SIGNALS

VALID_RESPONSE = {
    "message": "Entendo sua preocupação! O investimento cabe bem no orçamento de quem...",
    "confidence": 0.85,
    "fallback_to_claude": False,
    "suggested_stage": "presenting",
    "behavioral_signals": ["pediu_preco"]
}

def test_parse_valid_json_response():
    result = parse_gemini_response(json.dumps(VALID_RESPONSE))
    assert result["message"] == VALID_RESPONSE["message"]
    assert result["confidence"] == 0.85
    assert result["fallback_to_claude"] is False

def test_parse_invalid_json_returns_fallback():
    result = parse_gemini_response("não é JSON válido")
    assert result["fallback_to_claude"] is True
    assert result["confidence"] == 0.0
    assert "message" in result

def test_parse_filters_invalid_signals():
    response = {**VALID_RESPONSE, "behavioral_signals": ["pediu_preco", "sinal_invalido"]}
    result = parse_gemini_response(json.dumps(response))
    assert "sinal_invalido" not in result["behavioral_signals"]
    assert "pediu_preco" in result["behavioral_signals"]

def test_low_confidence_triggers_fallback():
    response = {**VALID_RESPONSE, "confidence": 0.4, "fallback_to_claude": False}
    result = parse_gemini_response(json.dumps(response))
    # confidence < 0.6 deve forçar fallback
    assert result["fallback_to_claude"] is True

def test_engine_uses_claude_when_fallback_requested():
    mock_gemini = MagicMock()
    mock_gemini.generate_content.return_value.text = json.dumps(
        {**VALID_RESPONSE, "fallback_to_claude": True, "confidence": 0.3}
    )
    mock_claude = MagicMock()
    mock_claude.messages.create.return_value.content = [MagicMock(text="Resposta do Claude com empatia")]

    engine = AIEngine(gemini_model=mock_gemini, claude_client=mock_claude)
    result = engine.generate_response(
        stage="presenting",
        recent_messages=[{"role": "user", "content": "Tô com medo de não conseguir"}],
        contact_data={},
        system_prompt="Você é Ana...",
    )
    assert mock_claude.messages.create.called
    assert "Claude" in result["source"] or len(result["message"]) > 0
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_ai_engine.py -v
```

- [ ] **Step 3: Implementar `app/ai_engine.py`**

```python
# app/ai_engine.py
import json
import logging
import os
from pathlib import Path

import google.generativeai as genai
import anthropic

logger = logging.getLogger(__name__)

VALID_SIGNALS = ["pediu_preco", "mencionou_concorrente", "pediu_parcelamento", "disse_vou_pensar"]
CONFIDENCE_THRESHOLD = 0.6

SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "knowledge_base" / "system_prompt.md"

GEMINI_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "message": {"type": "string"},
        "confidence": {"type": "number"},
        "fallback_to_claude": {"type": "boolean"},
        "suggested_stage": {"type": "string"},
        "behavioral_signals": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["message", "confidence", "fallback_to_claude"],
}

FALLBACK_RESPONSE = {
    "message": "Desculpe, tive um probleminha técnico. Pode repetir sua mensagem?",
    "confidence": 0.0,
    "fallback_to_claude": True,
    "suggested_stage": None,
    "behavioral_signals": [],
    "source": "fallback",
}


def parse_gemini_response(text: str) -> dict:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, Exception):
        logger.warning("Gemini retornou JSON inválido, forçando fallback Claude")
        return {**FALLBACK_RESPONSE}

    # Forçar fallback se confiança baixa
    if float(data.get("confidence", 0)) < CONFIDENCE_THRESHOLD:
        data["fallback_to_claude"] = True

    # Filtrar sinais inválidos
    data["behavioral_signals"] = [
        s for s in data.get("behavioral_signals", []) if s in VALID_SIGNALS
    ]
    data.setdefault("source", "gemini")
    return data


class AIEngine:
    def __init__(self, gemini_model=None, claude_client=None):
        if gemini_model is None:
            genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
            self._gemini = genai.GenerativeModel(
                "gemini-2.0-flash",
                generation_config={"response_mime_type": "application/json"},
            )
        else:
            self._gemini = gemini_model

        if claude_client is None:
            self._claude = anthropic.Anthropic(api_key=os.environ.get("CLAUDE_API_KEY", ""))
        else:
            self._claude = claude_client

        self._system_prompt = (
            SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
            if SYSTEM_PROMPT_PATH.exists()
            else "Você é Ana, assistente de agendamento da nutricionista Thaynara."
        )

    def generate_response(
        self,
        stage: str,
        recent_messages: list[dict],
        contact_data: dict,
        system_prompt: str | None = None,
    ) -> dict:
        sys = system_prompt or self._system_prompt
        conversation_text = "\n".join(
            f"{'Paciente' if m['role'] == 'user' else 'Ana'}: {m['content']}"
            for m in recent_messages[-10:]
        )
        prompt = (
            f"{sys}\n\n"
            f"Stage atual: {stage}\n"
            f"Dados coletados: {contact_data}\n\n"
            f"Conversa recente:\n{conversation_text}\n\n"
            f"Responda em JSON com os campos: message, confidence (0.0-1.0), "
            f"fallback_to_claude (bool), suggested_stage, behavioral_signals "
            f"(lista de: {', '.join(VALID_SIGNALS)})"
        )

        try:
            response = self._gemini.generate_content(prompt)
            result = parse_gemini_response(response.text)
        except Exception as e:
            logger.error(f"Gemini falhou: {e}")
            result = {**FALLBACK_RESPONSE}

        if result.get("fallback_to_claude"):
            return self._call_claude(sys, recent_messages, result)

        return result

    def _call_claude(self, system_prompt: str, messages: list[dict], gemini_result: dict) -> dict:
        try:
            response = self._claude.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": m["role"], "content": m["content"]} for m in messages[-10:]],
            )
            text = response.content[0].text
            return {
                "message": text,
                "confidence": 0.9,
                "fallback_to_claude": False,
                "suggested_stage": gemini_result.get("suggested_stage"),
                "behavioral_signals": gemini_result.get("behavioral_signals", []),
                "source": "claude",
            }
        except Exception as e:
            logger.error(f"Claude também falhou: {e}")
            return {**FALLBACK_RESPONSE, "source": "fallback"}


async def handle_ai(phone: str, phone_hash: str, stage: str, text: str):
    """Chama AI engine, envia resposta e atualiza estado do contato."""
    from app.meta_api import MetaAPIClient
    from app.database import SessionLocal
    from app.models import Contact, Conversation, Message, RemarketingQueue
    from app.remarketing import schedule_behavioral_remarketing
    from datetime import datetime, UTC
    import os

    engine = AIEngine()

    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        conversation = (
            db.query(Conversation)
            .filter_by(contact_id=contact.id, outcome="em_aberto")
            .order_by(Conversation.opened_at.desc())
            .first()
        )
        recent = [
            {"role": "user" if m.direction == "inbound" else "assistant", "content": m.content}
            for m in conversation.messages[-10:]
        ] if conversation else []
        contact_data = {
            "name": contact.collected_name,
            "patient_type": contact.patient_type,
        }
        contact_id = contact.id

    result = engine.generate_response(stage=stage, recent_messages=recent, contact_data=contact_data)

    meta = MetaAPIClient(
        phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("META_ACCESS_TOKEN", ""),
    )
    meta.send_text(to=phone, text=result["message"])

    # Atualizar stage sugerido e disparar remarketing comportamental
    with SessionLocal() as db:
        contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
        if result.get("suggested_stage") and result["suggested_stage"] != contact.stage:
            contact.stage = result["suggested_stage"]
        db.commit()

    if result.get("behavioral_signals"):
        with SessionLocal() as db:
            schedule_behavioral_remarketing(db, contact_id, result["behavioral_signals"])
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_ai_engine.py -v
```
Esperado: 5 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add app/ai_engine.py tests/test_ai_engine.py
git commit -m "feat: AI engine Gemini JSON + fallback Claude Haiku com threshold de confiança"
```

---

## Task 8: Remarketing Engine

**Files:**
- Create: `app/remarketing.py`
- Create: `tests/test_remarketing.py`

- [ ] **Step 1: Escrever testes**

```python
# tests/test_remarketing.py
import pytest
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, RemarketingQueue
from app.remarketing import (
    can_schedule_remarketing,
    schedule_time_remarketing,
    schedule_behavioral_remarketing,
    cancel_pending_remarketing,
    REMARKETING_SEQUENCE,
)

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session

@pytest.fixture
def contact(db):
    c = Contact(phone_hash="test_hash", stage="cold_lead", remarketing_count=0)
    db.add(c)
    db.commit()
    return c

def test_can_schedule_when_no_history(db, contact):
    assert can_schedule_remarketing(db, contact.id) is True

def test_cannot_schedule_when_count_is_5(db, contact):
    contact.remarketing_count = 5
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is False

def test_cannot_schedule_when_sent_today(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC),
        sent_at=datetime.now(UTC),
        status="sent",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(rq)
    db.commit()
    assert can_schedule_remarketing(db, contact.id) is False

def test_schedule_time_remarketing_creates_queue_entry(db, contact):
    schedule_time_remarketing(db, contact.id, template="follow_up_geral",
                              delay_hours=2, position=1)
    queue = db.query(RemarketingQueue).filter_by(contact_id=contact.id).all()
    assert len(queue) == 1
    assert queue[0].template_name == "follow_up_geral"
    assert queue[0].trigger_type == "time"

def test_cancel_pending_removes_pending_entries(db, contact):
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="follow_up_geral",
        scheduled_for=datetime.now(UTC) + timedelta(hours=2),
        status="pending",
        sequence_position=1,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(rq)
    db.commit()

    cancel_pending_remarketing(db, contact.id)
    cancelled = db.query(RemarketingQueue).filter_by(contact_id=contact.id, status="cancelled").first()
    assert cancelled is not None

def test_informational_templates_dont_count(db, contact):
    # Templates informativos (counts_toward_limit=False) não incrementam o contador
    rq = RemarketingQueue(
        contact_id=contact.id,
        template_name="opcoes_pagamento",
        scheduled_for=datetime.now(UTC),
        sent_at=datetime.now(UTC),
        status="sent",
        sequence_position=0,
        trigger_type="behavior",
        counts_toward_limit=False,
    )
    db.add(rq)
    db.commit()
    # Ainda deve poder agendar
    assert can_schedule_remarketing(db, contact.id) is True
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_remarketing.py -v
```

- [ ] **Step 3: Implementar `app/remarketing.py`**

```python
# app/remarketing.py
import logging
import os
from datetime import datetime, UTC, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from sqlalchemy.orm import Session
from app.models import Contact, RemarketingQueue

logger = logging.getLogger(__name__)

REMARKETING_SEQUENCE = [
    {"position": 1, "template": "follow_up_geral", "delay_hours": 2},
    {"position": 2, "template": "objecao_preco", "delay_hours": 24},
    {"position": 3, "template": "urgencia_vagas", "delay_hours": 48},
    {"position": 4, "template": "depoimento", "delay_hours": 72},
    {"position": 5, "template": "oferta_especial", "delay_hours": 168},
]

BEHAVIORAL_TEMPLATES = {
    "pediu_preco": ("objecao_preco", True),
    "disse_vou_pensar": ("follow_up_geral", True),
    "pediu_parcelamento": ("opcoes_pagamento", False),
    "mencionou_concorrente": ("diferenciacao", False),
}

MAX_REMARKETING = 5
RATE_LIMIT_PER_MIN = 30


def can_schedule_remarketing(db: Session, contact_id: str) -> bool:
    """Verifica se o contato pode receber mais mensagens de remarketing."""
    contact = db.get(Contact, contact_id)
    if not contact or contact.remarketing_count >= MAX_REMARKETING:
        return False

    # Verifica se já foi enviada alguma mensagem hoje
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = (
        db.query(RemarketingQueue)
        .filter(
            RemarketingQueue.contact_id == contact_id,
            RemarketingQueue.sent_at >= today_start,
            RemarketingQueue.counts_toward_limit.is_(True),
        )
        .first()
    )
    return sent_today is None


def schedule_time_remarketing(db: Session, contact_id: str, template: str,
                               delay_hours: float, position: int) -> RemarketingQueue | None:
    if not can_schedule_remarketing(db, contact_id):
        return None
    scheduled = datetime.now(UTC) + timedelta(hours=delay_hours)
    entry = RemarketingQueue(
        contact_id=contact_id,
        template_name=template,
        scheduled_for=scheduled,
        status="pending",
        sequence_position=position,
        trigger_type="time",
        counts_toward_limit=True,
    )
    db.add(entry)
    db.commit()
    return entry


def schedule_behavioral_remarketing(db: Session, contact_id: str, signals: list[str]):
    for signal in signals:
        if signal not in BEHAVIORAL_TEMPLATES:
            continue
        template, counts = BEHAVIORAL_TEMPLATES[signal]
        if counts and not can_schedule_remarketing(db, contact_id):
            continue
        entry = RemarketingQueue(
            contact_id=contact_id,
            template_name=template,
            scheduled_for=datetime.now(UTC) + timedelta(minutes=5),
            status="pending",
            sequence_position=0,
            trigger_type="behavior",
            counts_toward_limit=counts,
        )
        db.add(entry)
    db.commit()


def cancel_pending_remarketing(db: Session, contact_id: str):
    pending = (
        db.query(RemarketingQueue)
        .filter_by(contact_id=contact_id, status="pending")
        .all()
    )
    for entry in pending:
        entry.status = "cancelled"
    db.commit()


def _dispatch_due_messages():
    """Job APScheduler: processa entradas pendentes da fila de remarketing."""
    from app.database import SessionLocal
    from app.meta_api import MetaAPIClient
    import redis

    redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    meta = MetaAPIClient(
        phone_number_id=os.environ.get("META_PHONE_NUMBER_ID", ""),
        access_token=os.environ.get("META_ACCESS_TOKEN", ""),
    )

    with SessionLocal() as db:
        now = datetime.now(UTC)
        due = (
            db.query(RemarketingQueue)
            .filter(RemarketingQueue.status == "pending", RemarketingQueue.scheduled_for <= now)
            .order_by(RemarketingQueue.scheduled_for)
            .limit(50)
            .all()
        )

        for entry in due:
            # Rate limit Redis: máx 30/min
            minute_key = f"meta:rate:{now.strftime('%Y%m%d%H%M')}"
            count = redis_client.incr(minute_key)
            if count == 1:
                redis_client.expire(minute_key, 60)
            if count > RATE_LIMIT_PER_MIN:
                # Reagendar para próximo minuto
                entry.scheduled_for = now + timedelta(minutes=1)
                db.commit()
                continue

            contact = db.get(Contact, entry.contact_id)
            if not contact or contact.stage == "archived":
                entry.status = "cancelled"
                db.commit()
                continue

            if not contact.phone_e164:
                logger.error(f"Contato {contact.id} sem phone_e164, pulando")
                entry.status = "cancelled"
                db.commit()
                continue

            try:
                meta.send_template(to=contact.phone_e164, template_name=entry.template_name)
                entry.status = "sent"
                entry.sent_at = now
                if entry.counts_toward_limit:
                    contact.remarketing_count += 1
                if contact.remarketing_count >= MAX_REMARKETING:
                    contact.stage = "archived"
                db.commit()
                import time; time.sleep(2)  # intervalo mínimo de 2s entre disparos
            except Exception as e:
                logger.error(f"Falha ao enviar remarketing {entry.id}: {e}")
                entry.status = "failed"
                db.commit()


def create_scheduler() -> BackgroundScheduler:
    jobstores = {"default": SQLAlchemyJobStore(url=os.environ.get("DATABASE_URL", ""))}
    scheduler = BackgroundScheduler(jobstores=jobstores)
    scheduler.add_job(_dispatch_due_messages, "interval", minutes=1, id="remarketing_dispatcher",
                      replace_existing=True)
    return scheduler
```

- [ ] **Step 4: Rodar testes**

```bash
python -m pytest tests/test_remarketing.py -v
```
Esperado: 6 testes PASS.

- [ ] **Step 5: Commit**

```bash
git add app/remarketing.py tests/test_remarketing.py
git commit -m "feat: remarketing engine com fila, proteções anti-spam e rate limiter Redis"
```

---

## Task 9: Retry de Mensagens Falhas

**Files:**
- Create: `app/retry.py`

- [ ] **Step 1: Escrever teste**

```python
# tests/test_retry.py
import pytest
from datetime import datetime, UTC, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import Contact, Conversation, Message
from app.retry import get_messages_to_retry, compute_backoff_seconds, MAX_RETRIES

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s

def test_gets_retrying_messages_older_than_30s(db):
    contact = Contact(phone_hash="h1", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()

    old_msg = Message(
        meta_message_id="old_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=1,
        sent_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    recent_msg = Message(
        meta_message_id="recent_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=1,
        sent_at=datetime.now(UTC) - timedelta(seconds=10),
    )
    db.add_all([old_msg, recent_msg])
    db.commit()

    result = get_messages_to_retry(db)
    assert len(result) == 1
    assert result[0].meta_message_id == "old_001"

def test_backoff_exponential():
    assert compute_backoff_seconds(1) == 1    # 4^0
    assert compute_backoff_seconds(2) == 4    # 4^1
    assert compute_backoff_seconds(3) == 16   # 4^2

def test_message_marked_failed_after_max_retries(db):
    contact = Contact(phone_hash="h2", stage="new")
    db.add(contact)
    db.flush()
    conv = Conversation(contact_id=contact.id, stage="new", outcome="em_aberto")
    db.add(conv)
    db.flush()
    msg = Message(
        meta_message_id="fail_001", conversation_id=conv.id,
        direction="inbound", content="oi",
        processing_status="retrying", retry_count=MAX_RETRIES,
        sent_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    db.add(msg)
    db.commit()

    from app.retry import mark_exhausted_as_failed
    mark_exhausted_as_failed(db)
    db.refresh(msg)
    assert msg.processing_status == "failed"
```

- [ ] **Step 2: Verificar falha**

```bash
python -m pytest tests/test_retry.py -v
```
Esperado: FAIL com ImportError ou AttributeError.

- [ ] **Step 3: Adicionar campo `retry_count` ao modelo `Message`**

Em `app/models.py`, adicionar após `processing_status`:
```python
retry_count: Mapped[int] = mapped_column(Integer, default=0)
```

Gerar e rodar migration:
```bash
alembic revision --autogenerate -m "add retry_count to messages"
alembic upgrade head
```

- [ ] **Step 4: Implementar `app/retry.py`**

```python
# app/retry.py
import logging
import time
from datetime import datetime, UTC, timedelta
from sqlalchemy.orm import Session
from app.models import Message

logger = logging.getLogger(__name__)
RETRY_AFTER_SECONDS = 30
MAX_RETRIES = 3
BACKOFF_BASE = 4  # 4^0=1s, 4^1=4s, 4^2=16s


def compute_backoff_seconds(retry_count: int) -> int:
    return BACKOFF_BASE ** (retry_count - 1)


def get_messages_to_retry(db: Session) -> list[Message]:
    cutoff = datetime.now(UTC) - timedelta(seconds=RETRY_AFTER_SECONDS)
    return (
        db.query(Message)
        .filter(
            Message.processing_status == "retrying",
            Message.retry_count < MAX_RETRIES,
            Message.sent_at <= cutoff,
        )
        .all()
    )


def mark_exhausted_as_failed(db: Session) -> None:
    """Marca como 'failed' mensagens que já atingiram MAX_RETRIES."""
    exhausted = (
        db.query(Message)
        .filter(Message.processing_status == "retrying", Message.retry_count >= MAX_RETRIES)
        .all()
    )
    for msg in exhausted:
        msg.processing_status = "failed"
        logger.error(f"Mensagem {msg.meta_message_id} falhou após {MAX_RETRIES} tentativas")
    db.commit()


def _retry_failed_messages():
    """Job APScheduler a cada 5 min: reprocessa mensagens em retry com backoff."""
    from app.database import SessionLocal
    with SessionLocal() as db:
        mark_exhausted_as_failed(db)
        messages = get_messages_to_retry(db)
        logger.info(f"Reprocessando {len(messages)} mensagens em retry")
        for msg in messages:
            backoff = compute_backoff_seconds(msg.retry_count + 1)
            msg.retry_count += 1
            msg.processing_status = "retrying"
            db.commit()
            time.sleep(backoff)
            # Reimportar para evitar circular import
            from app.router import route_message
            import asyncio
            # Extrair phone do conversation → contact
            contact = msg.conversation.contact
            if contact and contact.phone_e164:
                asyncio.run(route_message(
                    phone=contact.phone_e164,
                    phone_hash=contact.phone_hash,
                    text=msg.content,
                    meta_message_id=msg.meta_message_id,
                ))
```

- [ ] **Step 5: Rodar testes**

```bash
python -m pytest tests/test_retry.py -v
```
Esperado: 3 testes PASS.

- [ ] **Step 6: Commit**

```bash
git add app/retry.py tests/test_retry.py
git commit -m "feat: job de retry com backoff exponencial 1s/4s/16s e campo retry_count"
```

---

## Task 10: FastAPI Main + Lifespan

**Files:**
- Create: `app/main.py`

- [ ] **Step 1: Implementar `app/main.py`**

```python
# app/main.py
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.webhook import router as webhook_router
from app.remarketing import create_scheduler
from app.retry import _retry_failed_messages
from app.database import engine, Base

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    Base.metadata.create_all(bind=engine)  # Fallback se Alembic não rodou

    scheduler = create_scheduler()
    # Adicionar job de retry
    scheduler.add_job(
        _retry_failed_messages, "interval", minutes=5,
        id="retry_processor", replace_existing=True
    )
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    # Shutdown
    scheduler.shutdown(wait=False)


app = FastAPI(title="Agente Ana — Nutri Thaynara", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 2: Testar localmente**

```bash
# Sem Docker, com variáveis mínimas para teste de inicialização
META_APP_SECRET=test META_VERIFY_TOKEN=test DATABASE_URL=sqlite:///./test.db \
  REDIS_URL=redis://localhost:6379/0 \
  uvicorn app.main:app --reload
```

Esperado: servidor inicia sem erros na porta 8000. Acesse `http://localhost:8000/health` → `{"status":"ok"}`.

- [ ] **Step 3: Rodar todos os testes**

```bash
python -m pytest tests/ -v --tb=short
```
Esperado: todos os testes PASS.

- [ ] **Step 4: Commit**

```bash
git add app/main.py
git commit -m "feat: FastAPI app com lifespan APScheduler + health endpoint"
```

---

## Task 11: Script de Migração de Contatos (Evolution → Novo Banco)

**Files:**
- Create: `scripts/migrate_contacts.py`

- [ ] **Step 1: Implementar**

```python
# scripts/migrate_contacts.py
"""
Importa os contatos históricos do PostgreSQL da Evolution API
para o novo banco do agente Ana.

Executar UMA VEZ antes do go-live.
"""
import hashlib
import os
import sys
from datetime import datetime, UTC

import psycopg2
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_DB = os.environ.get(
    "EVOLUTION_DATABASE_URL",
    "postgresql://evolution:evolution123@localhost:5432/evolution"
)
NEW_DB = os.environ.get("DATABASE_URL", "")


def migrate():
    from app.database import SessionLocal, engine, Base
    from app.models import Contact

    Base.metadata.create_all(bind=engine)

    # Conectar ao banco da Evolution
    evo_conn = psycopg2.connect(EVOLUTION_DB)
    evo_cursor = evo_conn.cursor()

    # Buscar contatos (tabela Contact da Evolution API)
    evo_cursor.execute("""
        SELECT "remoteJid", "pushName", "updatedAt"
        FROM "Contact"
        WHERE "instanceId" = (SELECT id FROM "Instance" WHERE name = 'thay' LIMIT 1)
        AND "remoteJid" LIKE '%@s.whatsapp.net'
        ORDER BY "updatedAt" DESC
    """)
    rows = evo_cursor.fetchall()
    print(f"Contatos encontrados na Evolution: {len(rows)}")

    imported = 0
    with SessionLocal() as db:
        for jid, push_name, updated_at in rows:
            phone_hash = hashlib.sha256(jid.encode()).hexdigest()[:64]
            existing = db.query(Contact).filter_by(phone_hash=phone_hash).first()
            if not existing:
                contact = Contact(
                    phone_hash=phone_hash,
                    push_name=push_name,
                    stage="cold_lead",  # Contatos históricos são leads potenciais
                    last_message_at=updated_at,
                    created_at=datetime.now(UTC),
                )
                db.add(contact)
                imported += 1
        db.commit()

    print(f"Contatos importados: {imported}")
    evo_conn.close()


if __name__ == "__main__":
    migrate()
```

- [ ] **Step 2: Testar dry-run (quando Evolution ainda estiver ativa)**

```bash
# Verificar conexão com banco da Evolution
python -c "
import psycopg2
conn = psycopg2.connect('postgresql://evolution:evolution123@localhost:5432/evolution')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM \"Contact\"')
print('Contatos na Evolution:', cur.fetchone()[0])
conn.close()
"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/migrate_contacts.py
git commit -m "feat: script de migração de contatos Evolution → novo banco"
```

---

## Task 12: Build Docker e Smoke Test

- [ ] **Step 1: Build da imagem**

```bash
docker compose build
```

- [ ] **Step 2: Subir serviços**

```bash
docker compose up -d
```

- [ ] **Step 3: Verificar health**

```bash
curl http://localhost:8000/health
```
Esperado: `{"status":"ok"}`

- [ ] **Step 4: Testar verificação de webhook Meta**

```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=SEU_TOKEN&hub.challenge=TESTE123"
```
Esperado: `TESTE123`

- [ ] **Step 5: Rodar todos os testes dentro do container**

```bash
docker compose exec app python -m pytest tests/ -v --tb=short
```

- [ ] **Step 6: Commit final**

```bash
git add .
git commit -m "feat: build Docker completo, smoke test passando"
```

---

*Plano gerado em 2026-03-29. Referência: spec `docs/superpowers/specs/2026-03-29-agente-atendimento-nutricionista-design.md` Seções 3-12.*
