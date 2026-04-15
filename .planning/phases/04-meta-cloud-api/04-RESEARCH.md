# Phase 4: Meta Cloud API - Research

**Researched:** 2026-04-15
**Domain:** Meta Cloud API (WhatsApp Business), Redis deduplication, LGPD pseudonimização
**Confidence:** HIGH (código existente analisado diretamente; API Meta verificada via web; padrões Redis verificados via docs oficiais)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| META-01 | Webhook recebe e valida mensagens do Meta Cloud API (verificação de assinatura HMAC) | HMAC já implementado em `meta_api.verify_signature()` e `webhook.py` — análise de gaps abaixo |
| META-02 | Agente envia mensagens de texto via Meta Cloud API | `MetaAPIClient.send_text()` já funcional; bug de instanciação em `router.py` identificado |
| META-03 | Agente envia arquivos (PDF, imagens) via Meta Cloud API | Não implementado — apenas placeholders `[PDF: ...]` e `[IMG: ...]` em `atendimento.py` |
| META-04 | Deduplicação de mensagens (webhook at-least-once) para evitar processamento duplicado | Dedup por DB existe mas tem race condition; Redis SET NX é o padrão correto |
</phase_requirements>

---

## Summary

A integração Meta Cloud API já possui uma base sólida no projeto, mas com três gaps críticos para produção: (1) deduplicação por banco de dados com potencial race condition entre o `db.query().filter_by()` e o `db.add()`, sem proteção atômica; (2) ausência completa de envio de mídia real — `_etapa_confirmacao()` retorna strings literais `[IMG: ...]` e `[PDF: ...]` que chegam ao paciente como texto puro; (3) ausência de pseudonimização de dados do paciente antes de chamadas à Anthropic — `self.telefone` (número real E164) é armazenado no estado do agente e `self.nome` (nome real) aparece no `historico` que vai ao LLM.

O `verify_signature()` em `meta_api.py` está correto para META-01. O `MetaAPIClient.send_text()` e `send_template()` funcionam para META-02, mas `router.py:71` chama `MetaAPIClient()` sem argumentos — bug que quebra em produção quando o módulo for exercitado por fluxo real (os testes de router usam mock). Os planos devem endereçar cada gap com mínimo de modificação no que já funciona.

**Primary recommendation:** Implementar em 3 planos sequenciais: (1) deduplicação Redis atômica com SET NX + 4h TTL; (2) `MetaAPIClient.send_document()` e `send_image()` + substituir placeholders em `atendimento.py`; (3) sanitizer de PII aplicado no `historico` antes de chamar Anthropic + detecção de prompt injection.

---

## Project Constraints (from CLAUDE.md)

- LLM: `claude-haiku-4-5-20251001` — não alterar modelo
- Stack: Python 3.12 + FastAPI — não mudar
- Todos os novos módulos devem ter testes em `tests/`
- Rodar `python -m pytest tests/ -q` antes de cada commit
- Número `31 99205-9211` NUNCA exposto ao paciente
- Privacidade LGPD: nunca armazenar dados sensíveis fora do Dietbox, pseudonimização para LLM
- Mensagens curtas e objetivas, tom informal/acolhedor

---

## Current State Analysis (Code Audit)

### O que já funciona (não refazer)

| Feature | Arquivo | Estado |
|---------|---------|--------|
| HMAC-SHA256 verification | `app/meta_api.py:verify_signature()` | Correto e testado |
| Webhook endpoint GET (challenge) | `app/webhook.py` | Funcional |
| Webhook endpoint POST (receive) | `app/webhook.py` | Funcional, HMAC verificado |
| Envio de texto | `MetaAPIClient.send_text()` | Funcional |
| Envio de template | `MetaAPIClient.send_template()` | Funcional |
| Envio de contato | `MetaAPIClient.send_contact()` | Funcional |
| Download de mídia recebida | `app/media_handler.download_media()` | Funcional |
| Dedup DB (parcial) | `webhook.py:process_message()` | Race condition — ver gap abaixo |
| phone_hash para LGPD | `models.py:Contact.phone_hash` | Correto — telefone hasheado no DB |
| phone_e164 separado do hash | `models.py:Contact.phone_e164` | Correto — armazenado só onde necessário |

### Gaps críticos identificados (o que 04-0x deve construir)

**GAP-1 (04-01): Deduplicação tem race condition**

`webhook.py:process_message()` faz `db.query(Message).filter_by(meta_message_id=meta_id).first()` seguido de `db.add(msg)`. Com at-least-once delivery da Meta, duas instâncias do background task podem correr em paralelo, ambas passarem pelo `filter_by` antes do `db.add()` e criarem dois registros. O `UniqueConstraint("meta_message_id")` em `Message` captura isso como IntegrityError, mas o processamento duplicado (LLM call + possível agendamento) já ocorreu. Redis SET NX antes do processamento é a solução correta — atômica, 4h TTL, sem afetar o banco.

**GAP-2 (04-02): Envio de mídia não implementado**

`app/agents/atendimento.py:_etapa_confirmacao()` retorna:
```python
"[IMG: COMO-SE-PREPARAR---ONLINE.jpg]"
"[PDF: Guia Circunferências Corporais]"
"[PDF: Thaynara - Nutricionista.pdf]"  # em _etapa_apresentacao_planos
```
Essas strings chegam ao paciente literalmente via `send_text()`. Os arquivos existem em `docs/`. Precisam ser enviados como document/image via `send_document()` e `send_image()` — métodos que não existem em `MetaAPIClient`.

**GAP-3 (04-02): Bug de instanciação em router.py**

`router.py:71` chama `MetaAPIClient()` sem argumentos. `MetaAPIClient.__init__` exige `phone_number_id` e `access_token`. Isso quebra em produção no primeiro request real que chega ao `route_message()`. Os testes de router usam `patch("app.meta_api.MetaAPIClient", CapturingMeta)`, mascarando o bug. Correção simples: ler env vars no `__init__` com defaults ou exigir args com defaults.

**GAP-4 (04-03): Dados do paciente em chamadas ao LLM**

O `historico` do `AgenteAtendimento` contém as mensagens brutas do paciente (podem incluir nome, telefone de terceiros, dados bancários). O `self.telefone` (número E164 real) é serializado em `to_dict()` e salvo no Redis. Quando `_gerar_resposta_llm()` é chamado, o `historico[-10:]` vai diretamente para a Anthropic API — sem sanitização. O `self.nome` (nome real) aparece em mensagens fixas que entram no historico. Risco: CPF que o paciente digitar no chat vai ao LLM sem mascaramento.

**GAP-5 (04-03): Sem proteção contra prompt injection**

Mensagem do paciente vai direto para `historico.append({"role": "user", "content": mensagem_usuario})` sem nenhuma sanitização. Padrões como `\n\nHuman:`, `\n\nAssistant:`, `Ignore previous instructions` podem tentar manipular o LLM.

---

## Standard Stack

### Core (já no projeto, confirmar versões)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| `httpx` | 0.27.0 | Async HTTP client para Meta Cloud API | Já em uso em `meta_api.py` |
| `redis` | 5.0.8 (sync) + `redis.asyncio` | Deduplicação atômica SET NX | Já em uso em `remarketing.py`, `state_manager.py` |
| `hashlib` | stdlib | SHA-256 para phone_hash e PII masking | Já em uso |
| `hmac` | stdlib | HMAC-SHA256 para signature verification | Já em uso em `meta_api.py` |
| `anthropic` | >= 0.50.0 | LLM calls (Claude Haiku) | Já em uso |

### Para META-03 (envio de mídia)

| Approach | Método | Quando usar |
|----------|--------|-------------|
| Upload + media_id | `POST /{phone_number_id}/media` multipart + `send_document(id=media_id)` | Para arquivos servidos localmente (PDFs e imagens em `docs/`) |
| Link direto | `send_document(link="https://...")` | Só se arquivos estiverem em URL pública acessível pela Meta |

**Recomendação:** Upload (media_id) — os arquivos estão em `docs/` no servidor, não em URL pública. Cache de 10 minutos da Meta para links é problemático para arquivos frequentemente servidos.

**Installation:** Nenhuma dependência nova necessária.

---

## Architecture Patterns

### Padrão 1: Redis SET NX para deduplicação atômica

**O que é:** Usar `SET key value NX EX ttl_segundos` como operação atômica para verificar-e-registrar. Se retorna `True` = primeira vez (processar). Se retorna `None` = duplicata (ignorar).

**Quando usar:** Toda mensagem recebida no webhook, antes de qualquer processamento de negócio.

**Exemplo:**
```python
# Source: redis.io/tutorials/data-deduplication-with-redis (VERIFIED)
async def is_duplicate(redis_client, meta_message_id: str, ttl_seconds: int = 14400) -> bool:
    """Retorna True se mensagem já foi vista (duplicata). False = primeira vez."""
    key = f"dedup:msg:{meta_message_id}"
    # SET NX EX é atômico — sem race condition
    result = await redis_client.set(key, "1", nx=True, ex=ttl_seconds)
    return result is None  # None = key já existia = duplicata
```

**Key prefix:** `dedup:msg:{meta_message_id}` — 4h TTL (14400s)

**Por que 4h:** Meta pode retentar entrega por até 72h, mas na prática reentregas tardias (> 4h) indicam problema diferente. 4h é window suficiente para absorver duplicatas de retry sem acumular keys eternamente.

**Graceful degradation:** Se Redis estiver indisponível, cair para a dedup por banco existente (não quebrar o fluxo principal).

### Padrão 2: Upload de mídia + send_document/send_image

**O que é:** Two-step — primeiro faz upload do arquivo para obter `media_id`, depois usa o `media_id` no payload de mensagem.

**Endpoint de upload:**
```
POST https://graph.facebook.com/v19.0/{phone_number_id}/media
Content-Type: multipart/form-data

Fields:
  messaging_product: "whatsapp"
  file: <binary content>
  type: "application/pdf" | "image/jpeg" | etc.
```

**Response:**
```json
{"id": "4490709327384033"}
```

**Payload send_document (media_id):**
```json
{
  "messaging_product": "whatsapp",
  "to": "5531999999999",
  "type": "document",
  "document": {
    "id": "4490709327384033",
    "filename": "Thaynara - Nutricionista.pdf",
    "caption": "Nosso mídia kit completo 💚"
  }
}
```
[CITED: developers.facebook.com/docs/whatsapp/cloud-api/messages/document-messages/]

**Payload send_image (media_id):**
```json
{
  "messaging_product": "whatsapp",
  "to": "5531999999999",
  "type": "image",
  "image": {
    "id": "4490709327384033",
    "caption": "Como se preparar para a consulta presencial"
  }
}
```
[CITED: developers.facebook.com/docs/whatsapp/cloud-api/messages/image-messages/]

**Implementação Python (httpx multipart):**
```python
# Source: padrão httpx multipart — [ASSUMED] sem exemplo oficial em Python
async def upload_media(self, file_bytes: bytes, mime_type: str, filename: str) -> str:
    """Faz upload de mídia e retorna media_id. Raises httpx.HTTPStatusError em falha."""
    url = f"{META_API_BASE}/{self._phone_id}/media"
    files = {"file": (filename, file_bytes, mime_type)}
    data = {"messaging_product": "whatsapp", "type": mime_type}
    async with httpx.AsyncClient(headers={"Authorization": self._headers["Authorization"]},
                                  timeout=30) as client:
        resp = await client.post(url, files=files, data=data)
        resp.raise_for_status()
        return resp.json()["id"]
```

**Cache do media_id:** Após upload, armazenar `media_id` em Redis com TTL de 23h (Meta armazena mídia por 30 dias, mas refresh conservador). Evita upload repetido do mesmo arquivo.

```python
# Redis cache para media_id dos arquivos estáticos
MEDIA_CACHE_KEY = "media_id:{filename_hash}"
MEDIA_CACHE_TTL = 82800  # 23h em segundos
```

### Padrão 3: PII Sanitizer para historico antes do LLM

**O que é:** Função que recebe o historico (lista de dicts role/content) e aplica mascaramento de PII antes de enviar para a Anthropic.

**Campos sensíveis a mascarar no texto das mensagens:**
- CPF: padrão `\d{3}\.?\d{3}\.?\d{3}-?\d{2}` → `[CPF]`
- Telefone brasileiro: padrão `\(?\d{2}\)?\s?\d{4,5}-?\d{4}` → `[TELEFONE]`
- E-mail: padrão `[\w.+-]+@[\w-]+\.[\w.]+` → `[EMAIL]`

**O que NÃO mascarar:**
- Nome do paciente: nome está no system prompt e é fundamental para personalização. Ana precisa do nome para falar "Eiii Maria". Mascarar quebraria o fluxo.
- Valor de plano: não é PII.
- Data/hora de consulta: não é PII.

**phone_hash vs phone_e164:** O `self.telefone` (E164 real) não deve aparecer no `historico` — mas atualmente `processar()` recebe `mensagem_usuario` que é texto do paciente, não o telefone. O telefone só entra se o paciente *digitar* o próprio número — aí o sanitizer captura. O `self.phone_hash` (já hasheado) pode estar em contexto_extra sem risco.

**Prompt injection:** Mascarar padrões conhecidos no conteúdo `user` antes de adicionar ao historico:
- `\n\n(Human|Assistant|System|User):\s*` → substituir por `[FILTRADO]`
- Strings longas de instrução ("Ignore all previous", "Forget your instructions") → flag + truncar

```python
# Source: padrão de sanitização de prompt — [ASSUMED]
import re

_CPF_RE = re.compile(r'\d{3}\.?\d{3}\.?\d{3}-?\d{2}')
_PHONE_RE = re.compile(r'\(?\d{2}\)?\s?\d{4,5}-?\d{4}')
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
_INJECTION_RE = re.compile(
    r'(ignore\s+(all\s+)?previous|forget\s+your|new\s+instruction|system\s*:)',
    flags=re.IGNORECASE
)

def sanitize_for_llm(text: str) -> str:
    text = _CPF_RE.sub('[CPF]', text)
    text = _PHONE_RE.sub('[TELEFONE]', text)
    text = _EMAIL_RE.sub('[EMAIL]', text)
    if _INJECTION_RE.search(text):
        text = text[:200] + ' [CONTEÚDO FILTRADO]'
    return text
```

### Recomendação de projeto para mídia estática

Criar `app/media_store.py` com um `dict` de arquivos estáticos conhecidos:

```python
# app/media_store.py
MEDIA_STATIC = {
    "pdf_thaynara": {
        "path": "docs/Thaynara - Nutricionista.pdf",
        "mime": "application/pdf",
        "filename": "Thaynara - Nutricionista.pdf",
    },
    "img_preparo_online": {
        "path": "docs/COMO-SE-PREPARAR---ONLINE.jpg",
        "mime": "image/jpeg",
        "filename": "preparo-online.jpg",
    },
    "img_preparo_presencial": {
        "path": "docs/COMO-SE-PREPARAR---presencial.jpg",
        "mime": "image/jpeg",
        "filename": "preparo-presencial.jpg",
    },
    "pdf_guia_circunf_mulher": {
        "path": "docs/Guia - Circunferências Corporais - Mulheres.pdf",
        "mime": "application/pdf",
        "filename": "Guia-Circunferencias-Mulheres.pdf",
    },
    "pdf_guia_circunf_homem": {
        "path": "docs/Guia - Circunferências Corporais - Homens.pdf",
        "mime": "application/pdf",
        "filename": "Guia-Circunferencias-Homens.pdf",
    },
}
```

### Anti-Patterns a Evitar

- **Dedup por DB sem Redis:** Race condition entre select e insert — a IntegrityError evita dados duplicados no banco, mas não evita duas chamadas ao LLM/Dietbox ocorrendo em paralelo.
- **Link para arquivo local:** Meta precisa acessar a URL publicamente. Arquivo em `docs/` no VPS não é acessível externamente sem CDN ou nginx serve-static explícito.
- **Reupload de arquivo a cada mensagem:** PDF de preparação é enviado a todo paciente — cache do media_id no Redis evita upload repetido.
- **Mascarar nome do paciente:** Ana usa o nome em todas as mensagens. Mascarar quebraria a personalização.
- **Regex de CPF muito ampla:** Capturaria datas (01/01/1990) como "CPF". Usar padrão específico com `-` ou `.` delimitadores.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dedup atômica | Check-then-insert em SQL | Redis SET NX EX | SQL tem race condition entre threads; Redis é single-threaded, atômico por design |
| Signature verification | Implementação própria de HMAC | `hmac.compare_digest()` (já existe) | Timing attack se usar `==` comparação direta |
| Regex de CPF | Lógica caseira | Padrão validado com Luhn check | CPF tem dígitos verificadores; regex simples não valida |
| Upload de mídia | Servidor de arquivos próprio | Meta Cloud API upload + Redis cache de media_id | Meta já serve como CDN; mídia fica disponível 30 dias |

---

## Common Pitfalls

### Pitfall 1: MetaAPIClient instanciado sem argumentos em router.py

**O que vai errado:** `router.py:71` chama `MetaAPIClient()` sem `phone_number_id` e `access_token`. Levanta `TypeError` na primeira mensagem real em produção.

**Por que acontece:** Testes de router patcham `MetaAPIClient` com mock; o bug não aparece nos testes.

**Como evitar:** Modificar `MetaAPIClient.__init__` para ler env vars com defaults, ou corrigir a chamada em `router.py` para passar os args. Padrão mais limpo: constructor sem args que lê env vars internamente (como `webhook.py` faz com `APP_SECRET = os.environ.get(...)`).

**Sinal de alerta:** Qualquer route de mensagem real vai falhar com `TypeError: __init__() missing 2 required positional arguments`.

### Pitfall 2: Raw body já consumido pelo FastAPI antes da verificação HMAC

**O que vai errado:** Se o middleware JSON do FastAPI processar o body antes do `await request.body()`, a verificação HMAC falha porque `body` pode estar vazio ou diferente.

**Por que acontece:** FastAPI por padrão não consome o body automaticamente — mas middlewares de log podem. O `webhook.py` atual faz `body = await request.body()` antes de qualquer parse, o que é correto.

**Como evitar:** Nunca adicionar middleware que leia `request.body()` antes do webhook handler. O padrão atual está correto — manter.

**Sinal de alerta:** Todas as requisições da Meta retornando 403 mesmo com APP_SECRET correto.

### Pitfall 3: Race condition na deduplicação por banco

**O que vai errado:** Dois workers background processam a mesma mensagem quase simultaneamente. Ambos passam pelo `filter_by(meta_message_id=meta_id).first()` antes de qualquer um inserir. Resultado: dois agendamentos no Dietbox para o mesmo paciente.

**Por que acontece:** Meta entrega mensagens com at-least-once semantics. BackgroundTasks do FastAPI pode ter dois workers.

**Como evitar:** Redis SET NX antes de qualquer processamento de negócio. O banco `UniqueConstraint` pega a duplicata *depois* — Redis a previne *antes*.

**Sinal de alerta:** Paciente reclama de dois agendamentos. Logs mostram dois `meta_message_id` iguais com timestamps próximos.

### Pitfall 4: Media_id expira após 30 dias

**O que vai errado:** media_id obtido no upload expira após 30 dias. Sistema envia ID expirado e Media API retorna erro.

**Por que acontece:** Meta expira mídia hospedada. Cache de media_id no Redis sem TTL adequado retém ID expirado.

**Como evitar:** TTL do cache de media_id no Redis: 23h (conservador). Re-upload acontece naturalmente no próximo uso. Para produção de longa duração, TTL de 25 dias é seguro, mas 23h simplifica a lógica.

**Sinal de alerta:** Erro 400 da Meta com `"error": {"code": 131053}` (media expired ou não encontrado).

### Pitfall 5: CPF real do paciente enviado ao LLM

**O que vai errado:** Paciente digita seu CPF no chat (ex: "meu CPF é 123.456.789-09"). Esse texto vai para `historico` sem mascaramento, depois para Anthropic API. LGPD violation.

**Por que acontece:** `processar()` adiciona mensagem_usuario direto ao historico sem sanitização.

**Como evitar:** Aplicar `sanitize_for_llm()` ao texto antes de adicionar ao historico, OU aplicar ao construir `msgs` em `_gerar_resposta_llm()`.

**Sinal de alerta:** Logs da Anthropic (se habilitados) mostram CPF em cleartext. Auditoria LGPD.

---

## Code Examples

### Deduplicação Redis atômica (04-01)

```python
# app/webhook.py — modificação no process_message
# Source: redis.io/tutorials/data-deduplication-with-redis [VERIFIED]
import redis.asyncio as aioredis
import os

_DEDUP_TTL = 14400  # 4 horas

async def _is_duplicate_message(meta_message_id: str) -> bool:
    """
    Retorna True se a mensagem já foi processada (duplicata).
    Usa Redis SET NX EX — atômico, sem race condition.
    Graceful degradation: se Redis falhar, retorna False (processa).
    """
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    try:
        redis_client = aioredis.Redis.from_url(redis_url, decode_responses=True)
        key = f"dedup:msg:{meta_message_id}"
        result = await redis_client.set(key, "1", nx=True, ex=_DEDUP_TTL)
        await redis_client.aclose()
        return result is None  # None = chave já existia = duplicata
    except Exception as e:
        logger.warning("Redis dedup indisponível: %s — prosseguindo sem dedup", e)
        return False  # fail open: não bloquear mensagens se Redis cair
```

### MetaAPIClient: send_document e send_image (04-02)

```python
# app/meta_api.py — métodos a adicionar
# Source: developers.facebook.com/docs/whatsapp/cloud-api/messages/document-messages/ [CITED]

async def upload_media(self, file_bytes: bytes, mime_type: str, filename: str) -> str:
    """Faz upload de arquivo para Meta e retorna media_id. [ASSUMED: httpx multipart syntax]"""
    url = f"{META_API_BASE}/{self._phone_id}/media"
    files = {"file": (filename, file_bytes, mime_type)}
    data = {"messaging_product": "whatsapp", "type": mime_type}
    auth_header = {"Authorization": self._headers["Authorization"]}
    async with httpx.AsyncClient(headers=auth_header, timeout=30) as client:
        resp = await client.post(url, files=files, data=data)
        resp.raise_for_status()
        return resp.json()["id"]

async def send_document(self, to: str, media_id: str, filename: str,
                         caption: str = "") -> dict:
    """Envia documento (PDF) usando media_id."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
            **({"caption": caption} if caption else {}),
        },
    }
    return await self._post(payload)

async def send_image(self, to: str, media_id: str, caption: str = "") -> dict:
    """Envia imagem usando media_id."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "id": media_id,
            **({"caption": caption} if caption else {}),
        },
    }
    return await self._post(payload)
```

### Fix: MetaAPIClient sem args obrigatórios (04-02)

```python
# app/meta_api.py — __init__ lê env vars com fallback
import os

class MetaAPIClient:
    def __init__(
        self,
        phone_number_id: str | None = None,
        access_token: str | None = None,
    ):
        self._phone_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        token = access_token or os.environ.get("WHATSAPP_TOKEN", "")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
```

### PII Sanitizer (04-03)

```python
# app/pii_sanitizer.py — novo módulo
# Source: padrão de sanitização [ASSUMED - padrões de regex verificados por conhecimento de treinamento]
import re
import logging

logger = logging.getLogger(__name__)

_CPF_RE = re.compile(r'\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b')
_PHONE_BR_RE = re.compile(r'\(?\b\d{2}\)?\s?\d{4,5}-?\d{4}\b')
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
_INJECTION_RE = re.compile(
    r'ignore\s+(all\s+)?previous|forget\s+(your\s+)?instructions?|'
    r'\n\n(human|assistant|system|user)\s*:',
    flags=re.IGNORECASE,
)

def sanitize_message(text: str) -> str:
    """
    Mascara PII e padrões de prompt injection em mensagem do paciente.
    Chamado ANTES de adicionar mensagem ao historico para LLM.
    """
    text = _CPF_RE.sub('[CPF]', text)
    text = _PHONE_BR_RE.sub('[TELEFONE]', text)
    text = _EMAIL_RE.sub('[EMAIL]', text)
    if _INJECTION_RE.search(text):
        logger.warning("Possível prompt injection detectado, texto truncado.")
        text = text[:200] + ' [CONTEÚDO FILTRADO]'
    return text


def sanitize_historico(historico: list[dict]) -> list[dict]:
    """
    Retorna cópia do historico com PII mascarado em mensagens do usuário.
    Mensagens do assistente (role=assistant) não são alteradas.
    """
    result = []
    for msg in historico:
        if msg.get("role") == "user":
            result.append({"role": "user", "content": sanitize_message(msg["content"])})
        else:
            result.append(msg)
    return result
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Evolution API (v1 proto) | Meta Cloud API direto | Menos intermediário, latência menor, confiabilidade maior |
| Dedup por DB UniqueConstraint | Dedup Redis SET NX + DB fallback | Race condition eliminada |
| `[PDF: ...]` placeholder | `send_document(media_id=...)` | Arquivo real chega ao paciente |
| Sem PII sanitization | `sanitize_historico()` antes de Anthropic | LGPD compliance |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `httpx.AsyncClient` aceita `files=` kwarg para multipart upload | Code Examples (upload_media) | Pode precisar de `httpx.encode_multipart_data` alternativo; testar com mock |
| A2 | Meta Cloud API v19.0 é a versão estável correta (mesma que o projeto usa) | Standard Stack | Se Meta deprecar v19.0, mudar para v20.0+ — mas mudança é de URL apenas |
| A3 | Regex de CPF `\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b` cobre formatos comuns sem falso-positivo em datas | Code Examples (PII Sanitizer) | Validar com casos reais; CPF sem pontuação (11 dígitos seguidos) pode não ser capturado |
| A4 | Meta armazena mídia por 30 dias após upload; TTL de 23h no cache Redis é conservador suficiente | Architecture Patterns (media cache) | Se Meta mudar política de retenção, TTL do Redis precisa de ajuste |
| A5 | Mascarar nome do paciente quebraria o fluxo — nome deve ir ao LLM | Architecture Patterns (PII) | Se LGPD exigir mascaramento de nome, toda personalização da Ana precisa ser repensada |

---

## Open Questions

1. **Multipart upload com httpx.AsyncClient**
   - O que sabemos: `httpx.AsyncClient.post(files=...)` funciona para sync; async tem mesma interface
   - O que não está claro: Comportamento com arquivos grandes (PDFs de múltiplas páginas) em async — possível timeout
   - Recomendação: Testar com `tests/test_meta_api.py` usando `respx.mock` para multipart. Timeout default de 30s deve cobrir arquivos < 5MB

2. **CPF sem pontuação no chat**
   - O que sabemos: Paciente pode digitar "cpf 12345678909" sem pontos ou traços
   - O que não está claro: Regex atual não captura 11 dígitos seguidos sem separadores (pode ser data, ZIP, etc.)
   - Recomendação: Adicionar padrão `\b\d{11}\b` com validação de dígito verificador, ou aceitar falso negativo (CPF sem pontuação) como trade-off aceitável

3. **Escopo jurídico LGPD: quais campos requerem consentimento explícito**
   - O que sabemos: Nome + telefone são dados pessoais. CPF é dado sensível. Pseudonimização reduz risco mas não elimina obrigação
   - O que não está claro: Linguagem de consentimento adequada, DPO (Data Protection Officer) necessário no volume atual
   - Recomendação: Implementar pseudonimização técnica (04-03) como camada de proteção; questão jurídica completa é work in progress conforme volume cresce (já registrado em STATE.md como concern)

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Redis | 04-01 dedup, 04-02 media cache | Sim (docker-compose) | 7.x | Cair para dedup por DB (race condition existe mas não é crítico em vol. baixo) |
| `httpx` async | 04-02 upload_media | Sim | 0.27.0 | — |
| `redis.asyncio` | 04-01 SET NX | Sim | 5.0.8 | — |
| Arquivos em `docs/` | 04-02 envio de mídia | Sim (verificados) | — | — |
| Meta Cloud API token | 04-02 upload | Depende de `.env` | — | Sem fallback — WHATSAPP_TOKEN obrigatório |

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.2 + pytest-asyncio 0.24.0 |
| Config file | `conftest.py` em `tests/` |
| Quick run command | `python -m pytest tests/test_webhook.py tests/test_meta_api.py -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| META-01 | Webhook rejeita assinatura HMAC inválida | unit | `python -m pytest tests/test_webhook.py -q` | Sim |
| META-01 | Webhook aceita assinatura HMAC válida | unit | `python -m pytest tests/test_webhook.py -q` | Sim |
| META-02 | send_text envia payload correto | unit | `python -m pytest tests/test_meta_api.py -q` | Sim |
| META-02 | MetaAPIClient sem args lê env vars | unit | `python -m pytest tests/test_meta_api.py -q` | Parcial (novo teste necessário) |
| META-03 | send_document envia payload com media_id | unit | `python -m pytest tests/test_meta_api.py -q` | Não — Wave 0 |
| META-03 | send_image envia payload com media_id | unit | `python -m pytest tests/test_meta_api.py -q` | Não — Wave 0 |
| META-03 | upload_media retorna media_id | unit | `python -m pytest tests/test_meta_api.py -q` | Não — Wave 0 |
| META-04 | Mensagem duplicada não é processada duas vezes | unit | `python -m pytest tests/test_webhook.py -q` | Parcial (novo teste necessário) |
| META-04 | Redis SET NX atômico previne race condition | unit | `python -m pytest tests/test_webhook.py -q` | Não — Wave 0 |
| META-04 (LGPD) | CPF mascarado antes de chamar Anthropic | unit | `python -m pytest tests/test_pii_sanitizer.py -q` | Não — Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_webhook.py tests/test_meta_api.py -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green antes de `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_pii_sanitizer.py` — cobre sanitize_message() e sanitize_historico() (META-04/LGPD)
- [ ] Novos testes em `tests/test_meta_api.py`: send_document, send_image, upload_media (META-03)
- [ ] Novos testes em `tests/test_webhook.py`: dedup Redis SET NX, MetaAPIClient sem args (META-04, META-02)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Não (webhook, não login) | — |
| V3 Session Management | Não | — |
| V4 Access Control | Parcial | `verify_signature()` autentica o chamador |
| V5 Input Validation | Sim | `sanitize_message()` — regex PII + injection |
| V6 Cryptography | Sim | `hmac.compare_digest()` (timing-safe) — não usar `==` |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Webhook forjado (sem HMAC) | Spoofing | `verify_signature()` + retorno 403 (já implementado) |
| Mensagem duplicada cria 2 agendamentos | Tampering | Redis SET NX antes do processamento |
| CPF/telefone em prompt LLM | Information Disclosure | `sanitize_historico()` antes de Anthropic API |
| Prompt injection via mensagem do paciente | Tampering | `_INJECTION_RE` sanitização no input |
| Timing attack na verificação HMAC | Information Disclosure | `hmac.compare_digest()` (já correto) |
| media_id expirado causa 400 da Meta | Denial of Service | Redis cache com TTL < 30 dias |

---

## Sources

### Primary (HIGH confidence)
- `app/webhook.py`, `app/meta_api.py`, `app/media_handler.py`, `app/models.py`, `app/state_manager.py` — análise direta do código existente [VERIFIED: leitura direta]
- `app/agents/atendimento.py` — identificação dos placeholders `[PDF: ...]` e `[IMG: ...]` [VERIFIED: leitura direta]
- [redis.io/tutorials/data-deduplication-with-redis](https://redis.io/tutorials/data-deduplication-with-redis) — SET NX pattern [VERIFIED: fonte oficial Redis]

### Secondary (MEDIUM confidence)
- [developers.facebook.com/docs/whatsapp/cloud-api/messages/document-messages/](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/document-messages/) — payload de documento [CITED: Meta oficial, página não renderizou conteúdo via WebFetch mas URL confirmada via WebSearch]
- [docs.kapso.ai/api/meta/whatsapp/media/upload-media](https://docs.kapso.ai/api/meta/whatsapp/media/upload-media) — endpoint upload de mídia e response format [MEDIUM: terceiro que wrappa Meta API, confirma estrutura multipart]
- WebSearch: múltiplos resultados confirmando payload `{"messaging_product": "whatsapp", "type": "document", "document": {"id": ...}}` [MEDIUM: convergência de múltiplas fontes]

### Tertiary (LOW confidence)
- Regex de CPF/telefone brasileiro — baseado em conhecimento de treinamento, não verificado contra edge cases reais [ASSUMED — marcar A3]

---

## Metadata

**Confidence breakdown:**
- Current state analysis: HIGH — código lido diretamente
- Standard stack: HIGH — bibliotecas já em uso no projeto
- HMAC pattern: HIGH — já implementado e correto no código
- Redis dedup pattern: HIGH — fonte oficial Redis
- Media sending payload: MEDIUM — URL oficial confirmada mas conteúdo HTML não renderizou; payload estrutural confirmado por múltiplas fontes terceiras
- PII sanitizer: MEDIUM — padrões de regex são padrão conhecidos, mas edge cases de CPF sem pontuação são LOW

**Research date:** 2026-04-15
**Valid until:** 2026-05-15 (Meta Cloud API é estável; Redis patterns estáveis)
