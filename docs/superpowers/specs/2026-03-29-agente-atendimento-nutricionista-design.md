# Design: Agente de Atendimento Híbrido — Nutricionista Thaynara Teixeira

**Data:** 2026-03-29
**Status:** Aprovado
**Contexto:** Clínica de nutrição individual. WhatsApp já em produção via Evolution API com bot "Ana" (nome fictício do agente, não da nutricionista). Migração para Meta Cloud API oficial com IA conversacional e remarketing automatizado.

---

## 1. Objetivo

Substituir o bot de fluxo fixo atual por um agente híbrido que:
- Usa IA (Gemini 2.0 Flash) para conversas abertas, objeções e dúvidas
- Mantém fluxos fixos para etapas críticas (pagamento, confirmação, boas-vindas)
- Dispara remarketing automatizado por tempo e comportamento
- Opera sobre a Meta Cloud API oficial (sem risco de ban)

> **Nota LGPD:** Dados de nome e telefone são pseudonimizados antes de serem enviados aos LLMs externos (Gemini e Claude). O conteúdo das mensagens é enviado sem o número real — apenas um ID interno. Ambos os providers (Google e Anthropic) possuem DPA disponível para assinar mediante plano pago.

---

## 2. Fases do Projeto

### Fase 1 — Mineração de Dados (execução única)

Extrai e analisa as últimas 800 conversas da Evolution API para gerar a knowledge base do agente.

**Pipeline:**
1. Buscar os 1.018 chats via Evolution API REST
2. Ordenar por `updatedAt` desc, pegar os 800 mais recentes
3. Para cada chat: buscar todas as mensagens via `/chat/findMessages`
4. Filtrar: remover grupos, broadcasts, conversas < 3 mensagens
5. Pseudonimizar: substituir nome/telefone por ID interno antes de enviar ao Gemini
6. Enviar cada conversa ao Gemini com prompt de análise estruturada (resposta JSON forçada)
7. Consolidar resultados e gerar knowledge base

**Saída — `knowledge_base/`:**
```
knowledge_base/
├── faq.json           # Top perguntas + melhores respostas encontradas
├── objections.json    # Objeções reais + como o agente respondeu ao converter
├── remarketing.json   # Perfis de leads frios + gatilhos sugeridos
├── tone_guide.md      # Vocabulário real, expressões, tom ideal
└── system_prompt.md   # Prompt completo para o novo agente Ana
```

**Estrutura de extração por conversa (Gemini, JSON forçado via `response_mime_type`):**
```json
{
  "intent": "agendar | tirar_duvida | preco | desistir | remarcar",
  "questions": ["string"],
  "objections": ["string"],
  "outcome": "fechou | nao_fechou | em_aberto",
  "interest_score": 1,
  "language_notes": "string",
  "behavioral_signals": ["pediu_preco", "mencionou_concorrente", "pediu_parcelamento", "disse_vou_pensar"]
}
```

**Checkpoint/resume da Fase 1:** O script salva o progresso em `scripts/mining_progress.json` após cada conversa processada com sucesso. Em caso de falha, o script retoma a partir do último checkpoint, evitando reprocessamento e desperdício de tokens.

### Fase 2 — Novo Agente em Produção

Backend Python operando sobre Meta Cloud API com roteamento híbrido.

**Migração de dados históricos:** Os contatos existentes (1.018) são importados do PostgreSQL da Evolution API para o novo banco, preservando histórico de conversas. Isso evita que leads quentes apareçam como `new` após o go-live.

---

## 3. Arquitetura

```
Paciente (WhatsApp)
        ↓
  Meta Cloud API — webhook POST
        ↓
  FastAPI Backend (Docker)
  ├── Webhook Handler (verifica X-Hub-Signature-256 + deduplica por message_id)
  ├── Router (fluxo fixo ou IA?)
  ├── Flows Engine
  ├── AI Engine (Gemini + Claude fallback)
  └── Remarketing Scheduler (APScheduler + SQLAlchemyJobStore)
        ↓
  PostgreSQL — histórico, estados, fila remarketing, jobs APScheduler
```

### Stack

| Componente | Tecnologia |
|---|---|
| Backend | Python 3.12 + FastAPI |
| LLM principal | Gemini 2.0 Flash (`gemini-2.0-flash`) — tier pago (~R$4-12/mês) |
| LLM fallback | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) |
| WhatsApp | Meta Cloud API oficial |
| Banco | PostgreSQL 15 (já em uso) |
| Scheduler | APScheduler 3.x com `SQLAlchemyJobStore` (persistência no PostgreSQL) |
| Cache | Redis 7 (já em uso) |
| Container | Docker Compose |

> **Nota:** Gemini operará no **tier pago** (não free tier) para evitar limite de 1.000 req/dia em dias de campanha de remarketing. O custo estimado é ~R$4-12/mês com 1.018 contatos ativos.

---

## 4. Schema do Banco de Dados

### Tabelas principais

**`contacts`**
```
id UUID PK
phone_hash VARCHAR(64)   -- hash do número, não o número real
push_name VARCHAR(255)
stage VARCHAR(50)        -- valores: new | collecting_info | presenting | scheduling |
                         --          awaiting_payment | confirmed | cold_lead |
                         --          remarketing_sequence | archived
collected_name VARCHAR(255)
patient_type VARCHAR(50)  -- primeira_consulta | paciente_existente
interest_score INT
remarketing_count INT DEFAULT 0
last_message_at TIMESTAMP
created_at TIMESTAMP
```

**`conversations`**
```
id UUID PK
contact_id UUID FK → contacts
stage VARCHAR(50)
opened_at TIMESTAMP
closed_at TIMESTAMP
outcome VARCHAR(50)  -- converteu | abandonou | agendou | arquivou | em_aberto
```

**`messages`**
```
id UUID PK
meta_message_id VARCHAR(255) UNIQUE  -- para deduplicação
conversation_id UUID FK → conversations
direction VARCHAR(10)   -- inbound | outbound
content TEXT
message_type VARCHAR(20)
processing_status VARCHAR(20) DEFAULT 'pending'  -- pending | processed | failed | retrying
sent_at TIMESTAMP
processed_at TIMESTAMP NULL
```

**`remarketing_queue`**
```
id UUID PK
contact_id UUID FK → contacts
template_name VARCHAR(100)
scheduled_for TIMESTAMP
sent_at TIMESTAMP NULL
status VARCHAR(20)  -- pending | sent | cancelled | failed
sequence_position INT  -- 1 a 5
trigger_type VARCHAR(20)  -- time | behavior
counts_toward_limit BOOLEAN DEFAULT true  -- false para templates informativos
```

---

## 5. Lógica do Agente Híbrido

### Estados da Conversa (`stage`)

| Stage | Descrição |
|---|---|
| `new` | Primeiro contato |
| `collecting_info` | Coletando nome + tipo de paciente |
| `presenting` | IA apresentando método/planos |
| `scheduling` | Selecionando horário |
| `awaiting_payment` | Aguardando comprovante PIX ou cartão |
| `confirmed` | Agendamento confirmado |
| `cold_lead` | Demonstrou interesse, não fechou — aguardando remarketing |
| `remarketing_sequence` | Em sequência ativa de reativação |
| `archived` | Esgotou sequência de remarketing sem resposta |

### Transições de Stage

```
new → collecting_info → presenting → scheduling → awaiting_payment → confirmed
         ↓                  ↓              ↓
       cold_lead ←←←←←←←←←←←←←←←←←←←←←←←
           ↓
    remarketing_sequence
           ↓ (resposta recebida)
       presenting   ← retorna ao fluxo de IA
           ↓ (5 sem resposta)
        archived
```

**Quando `cold_lead` recebe uma resposta:** stage transita para `presenting` e o agente de IA retoma a conversa. O job de remarketing pendente é cancelado.

### Roteamento

**Fluxo fixo ativa quando:**
- Stage é `new` → mensagem de boas-vindas + coleta de dados
- Stage é `awaiting_payment` → instruções PIX ou cartão
- Stage é `scheduling` → apresentação de horários disponíveis
- Stage é `confirmed` → confirmação + orientações pré-consulta

**IA (Gemini) ativa quando:**
- Qualquer mensagem com stage `collecting_info`, `presenting`, `cold_lead` (resposta recebida), `remarketing_sequence` (resposta recebida)
- Objeção ou resistência detectada em qualquer stage

**Fallback Claude Haiku ativa quando:**
- O campo `fallback_to_claude: true` é retornado no JSON do Gemini
- Gemini é acionado via prompt estruturado que retorna JSON com campo `confidence` (0.0-1.0); se `confidence < 0.6` → fallback

### Contexto enviado ao Gemini por chamada

Resposta **forçada em JSON** via `response_mime_type: application/json`:

```json
{
  "message": "texto da resposta para a paciente",
  "confidence": 0.85,
  "fallback_to_claude": false,
  "suggested_stage": "scheduling",
  "behavioral_signals": ["pediu_preco"]
}
```

**Valores válidos de `behavioral_signals`:** `pediu_preco` | `mencionou_concorrente` | `pediu_parcelamento` | `disse_vou_pensar`

Prompt inclui:
- `system_prompt.md` gerado na Fase 1
- Últimas 10 mensagens da conversa (com IDs internos, sem número real)
- Stage atual + dados coletados (nome, tipo de paciente)
- Objetivo do stage atual

---

## 6. Motor de Remarketing

### Disparos por Tempo (APScheduler + SQLAlchemyJobStore)

Contador global de 5 mensagens por contato. Disparos por tempo e comportamento compartilham o mesmo contador.

| Seq | Gatilho | Delay | Template |
|---|---|---|---|
| 1 | Não respondeu após boas-vindas | 2h | `follow_up_geral` |
| 2 | Pediu preço, sumiu | 24h | `objecao_preco` |
| 3 | Iniciou agendamento, não pagou | 48h | `urgencia_vagas` |
| 4 | Sem resposta ao follow-up anterior | 3 dias | `depoimento` |
| 5 | Sem resposta ao follow-up anterior | 7 dias | `oferta_especial` |

### Disparos por Comportamento (sinais extraídos do JSON do Gemini)

| Sinal (`behavioral_signals`) | Ação |
|---|---|
| `pediu_preco` | Avança para sequência `objecao_preco` (posição atual + 1) |
| `disse_vou_pensar` | Agenda `follow_up_geral` em 24h |
| `pediu_parcelamento` | Envia template `opcoes_pagamento` (não conta no contador de 5) |
| `mencionou_concorrente` | Aciona template `diferenciacao` (não conta no contador de 5) |

### Proteções Anti-Spam
- Máximo **1 mensagem por dia** por contato (verificado em `remarketing_queue`)
- Máximo **5 mensagens no contador global** (sequências de tempo + comportamento combinadas)
- Templates `opcoes_pagamento` e `diferenciacao` são informativos e **não contam** no contador de 5
- Resposta do contato → cancela jobs pendentes na fila, stage → `presenting`
- Contador atingir 5 sem resposta → status `archived`, campo `remarketing_count = 5`, nunca mais agendar

### Templates HSM — Plano de Contingência

Templates de saúde/nutrição podem ser rejeitados pela Meta por linguagem de urgência ou promessa terapêutica. Estratégia:

1. Submeter versão **primária** + versão **alternativa** (linguagem mais neutra) para cada template
2. `urgencia_vagas` e `oferta_especial` têm versões alternativas sem palavras como "últimas vagas" ou "oferta"
3. Se o template primário for rejeitado, a versão alternativa é usada sem atrasar o cronograma

```
templates/
├── follow_up_geral.txt / follow_up_geral_alt.txt
├── objecao_preco.txt / objecao_preco_alt.txt
├── urgencia_vagas.txt / urgencia_vagas_alt.txt
├── depoimento.txt
├── oferta_especial.txt / oferta_especial_alt.txt
├── opcoes_pagamento.txt
└── diferenciacao.txt
```

---

## 7. Resiliência e Rate Limiting

### Retry Policy para APIs Externas

O processamento de cada mensagem recebida ocorre em background task. Em caso de falha (timeout, erro 5xx do Gemini ou da Meta API):

- **3 tentativas** com backoff exponencial: 1s → 4s → 16s
- Campo `processing_status` na tabela `messages` rastreia o estado: `pending | processed | failed | retrying`
- Após 3 falhas: `processing_status = failed`, alerta logado. Mensagem não é perdida — fica na tabela para investigação manual.
- Um job APScheduler periódico (a cada 5 min) reprocessa mensagens com `processing_status = retrying` há mais de 30s

**Transições válidas de `processing_status`:**
```
pending → retrying   (1ª falha)
retrying → retrying  (2ª falha)
retrying → failed    (3ª falha — esgotou tentativas)
pending/retrying → processed  (sucesso em qualquer tentativa)
```

### Rate Limiting da Meta Cloud API

A Meta impõe limites por número de negócio. Para o remarketing em lote (especialmente na semana de migração dos 1.018 contatos):

- Intervalo mínimo de **2 segundos** entre disparos de template via `remarketing_queue`
- Implementado com contador em Redis: `INCR meta:rate:{minute}` com TTL de 60s
- Limite: máximo **30 disparos por minuto** (conservador — Meta permite até 250/min no tier básico)
- Se limite atingido: job recalcula `scheduled_for` para o próximo minuto disponível

---

## 8. Segurança do Webhook

O handler `webhook.py` implementa obrigatoriamente:

1. **Verificação de assinatura:** Valida `X-Hub-Signature-256` em toda requisição POST usando o `APP_SECRET` do Meta Developers. Requisições sem assinatura válida retornam `403`.

2. **Deduplicação:** Cada mensagem é identificada por `meta_message_id`. Antes de processar, verifica existência na tabela `messages`. Duplicata → retorna `200 OK` sem reprocessar (Meta interpreta não-200 como falha e reenvia).

3. **Resposta imediata:** Retorna `200 OK` imediatamente ao receber o webhook, processa de forma assíncrona via background task do FastAPI.

---

## 9. Migração Evolution → Meta Cloud API

### Pré-requisitos (executados manualmente uma vez)
1. Meta Business Account verificada
2. WhatsApp Business Account vinculada ao número do cliente
3. App no Meta Developers com permissão `whatsapp_business_messaging`
4. Webhook URL pública (ngrok em dev, URL da VPS em produção)
5. Templates HSM primários + alternativos submetidos e aprovados

> **Nota sobre cooldown:** A Meta exige que o número seja desregistrado do provedor atual antes do re-registro. O prazo varia por provedor — verificar na documentação oficial Meta Business Help Center antes de agendar o go-live.

### Cronograma de Transição

| Semana | Atividade |
|---|---|
| 1-2 | Mineração de dados (Evolution ainda ativo) + importação histórico |
| 3 | Build do backend + testes com número de teste Meta |
| 4 | Submissão dos templates HSM (primários + alternativos) |
| 5 | Go-live: desconecta Evolution, ativa Meta no número real |

> **Limitação conhecida:** Templates HSM só podem ser testados com o número real (não com número de teste). A integração completa de remarketing é validada em produção na Semana 5.

---

## 10. Deploy na VPS

Toda a infra roda em Docker Compose. Migração para VPS:

```bash
git clone <repo>
cp .env.example .env   # META_TOKEN, META_APP_SECRET, GEMINI_API_KEY, CLAUDE_API_KEY, DATABASE_URL
docker compose up -d
```

**Serviços no `docker-compose.yml`:**
- `app` — FastAPI backend (porta 8000, interna)
- `postgres` — PostgreSQL 15 (volume persistente `pgdata`)
- `redis` — Redis 7 (volume persistente `redisdata`)
- `nginx` — Reverse proxy (porta 443, HTTPS via Certbot)

Nginx como reverse proxy, HTTPS via Let's Encrypt (Certbot). Volume `pgdata` com backup diário obrigatório na VPS.

---

## 11. Estrutura de Arquivos do Projeto

```
agente-ana/
├── docker-compose.yml
├── .env.example
├── knowledge_base/          # Gerado na Fase 1
│   ├── faq.json
│   ├── objections.json
│   ├── remarketing.json
│   ├── tone_guide.md
│   └── system_prompt.md
├── templates/               # Templates HSM para Meta (primários + alternativos)
├── scripts/
│   └── mine_conversations.py  # Script Fase 1
└── app/
    ├── main.py              # FastAPI app + lifespan (APScheduler start/stop)
    ├── webhook.py           # Handler Meta webhook (assinatura + deduplicação)
    ├── router.py            # Decisão fluxo fixo vs IA
    ├── flows.py             # Fluxos fixos
    ├── ai_engine.py         # Gemini (JSON forçado) + Claude fallback
    ├── remarketing.py       # APScheduler SQLAlchemyJobStore + lógica de disparo
    ├── meta_api.py          # Wrapper Meta Cloud API
    └── models.py            # Modelos PostgreSQL (SQLAlchemy) — tabelas definidas na Seção 4
```

---

## 12. Decisões e Justificativas

| Decisão | Justificativa |
|---|---|
| Gemini 2.0 Flash tier pago | Evita limite de 1.000 req/dia do free tier em dias de campanha |
| Claude Haiku 4.5 como fallback | Melhor empatia para objeções emocionais; acionado via `confidence < 0.6` no JSON do Gemini |
| Resposta Gemini em JSON forçado | Permite extrair `confidence`, `suggested_stage` e `behavioral_signals` de forma estruturada |
| Meta Cloud API oficial | Elimina risco de ban, habilita templates HSM para remarketing |
| APScheduler com SQLAlchemyJobStore | Persistência de jobs no PostgreSQL já existente — sem perda de jobs em reinício do container |
| Templates primários + alternativos | Plano de contingência para rejeição Meta sem impacto no cronograma |
| Pseudonimização para LLMs | LGPD — número real nunca sai do servidor; apenas ID interno é enviado ao Gemini/Claude |
| Migração dos 1.018 contatos | Preserva histórico — leads quentes não aparecem como `new` após go-live |
| Retry com backoff exponencial | Mensagens nunca são perdidas silenciosamente em falha de API |
| Rate limiter Redis (30/min) | Evita bloqueio do número de negócio pela Meta em disparos em lote |
| Checkpoint/resume Fase 1 | Evita reprocessamento de 800 conversas em caso de falha parcial |
| Docker Compose | Portabilidade imediata para VPS sem mudanças |

---

*Spec gerada em 2026-03-29. Aprovada pelo usuário após revisão iterativa das 5 seções de design. Revisada pelo spec-document-reviewer com 12 pontos corrigidos.*
