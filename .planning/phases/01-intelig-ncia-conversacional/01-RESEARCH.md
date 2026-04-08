# Phase 1: Inteligência Conversacional - Research

**Researched:** 2026-04-08
**Domain:** FSM com structured LLM output, Redis state persistence, escalation relay bidirecional
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Interrupt Detection**
- D-01: Toda mensagem passa pelo orquestrador MESMO com agente ativo — classificação sempre acontece
- D-02: Intenções que INTERROMPEM o fluxo (troca de agente): `remarcar`, `cancelar`, `duvida_clinica`
- D-03: Intenções respondidas INLINE sem sair do fluxo: `tirar_duvida`, `fora_de_contexto` — responde e volta para etapa atual
- D-04: Mudança de etapa DENTRO do mesmo agente é permitida (ex: "quero trocar de plano" volta para `escolha_plano`)

**Escalação — 3 caminhos**
- D-05: Dúvida clínica + paciente cadastrado → Ana diz "Aqui é um canal somente para marcação de consultas. Para dúvidas clínicas por favor chame a Thaynara no WhatsApp" → envia contato da Thaynara (5531991394759). Não escala internamente, não aguarda resposta
- D-06: Dúvida clínica + NÃO é paciente (lead) → encaminha para Breno (31 99205-9211) com contexto. Ana: "Só um instante, vou verificar essa informação 💚". Memoriza resposta do Breno para próximas vezes. Repassa ao paciente
- D-07: Ana não sabe responder (qualquer situação) → encaminha para Breno (31 99205-9211). Mesma mecânica: aguarda, memoriza, repassa
- D-08: Número 31 99205-9211 (Breno) NUNCA é exposto ao paciente — é exclusivamente interno
- D-09: Cobrança ao Breno: a cada 15 min na primeira hora (15, 30, 45, 60 min), depois a cada 1h (2h, 3h, ...)
- D-10: Após 1h sem resposta do Breno → Ana avisa paciente: "Ainda estou verificando, te aviso assim que tiver retorno 💚"
- D-11: Respostas aprendidas são salvas na knowledge base como FAQ aprendido — persiste entre deploys, revisável

**Redis State Persistence**
- D-12: Estado de conversa (fluxo ativo) persiste no Redis SEM TTL automático — só limpa quando fluxo termina (`finalizacao`)
- D-13: Perfil do paciente (nome, sobrenome, dados permanentes) salvo no PostgreSQL via tabela `Contact` expandida — NUNCA expira
- D-14: Paciente que retorna é reconhecido pelo perfil: "Ei Marcela, lembro que já nos falamos! Como posso te ajudar?" — sem re-perguntar nome
- D-15: Falha do Redis → loga erro, cria estado novo, Ana pede as informações novamente: "Tive um probleminha técnico e perdi algumas informações da nossa conversa. Poderia me passar seu nome novamente?"

**Alinhamento com Documentação**
- D-16: Fora de contexto: escalar na primeira mensagem que Ana não souber responder (sem contador de 2x)
- D-17: Múltiplas perguntas por mensagem são permitidas DESDE QUE o agente consiga interpretar respostas parciais/fora de ordem
- D-18: Tom e expressões conforme documentação: "Eiii", "Perfeitoooo", "Obrigadaaa" — informal, caloroso, com emojis moderados (💚, 😊, ✅, 📅, 👉)
- D-19: Agendamento: nunca oferecer horário no mesmo dia. Mínimo 1 dia útil. Quando oferecer na mesma semana, usar o termo "tive uma desistência amanhã às X horas"
- D-20: "Vou pensar" / "Vou confirmar depois" → remarketing tradicional (24h, 7d, 30d)

**Waiting Indicator**
- D-21: Ana envia "Um instante, por favor 💚" (ou variação) ANTES de qualquer operação demorada: consulta Dietbox, busca de horários, geração de link de pagamento

### Claude's Discretion

- Formato exato do structured LLM output (`{nova_etapa, slots_atualizados, resposta}`)
- Schema de serialização Redis (`to_dict()/from_dict()`)
- Implementação do mecanismo de cobrança ao Breno (APScheduler job vs loop async)
- Formato de armazenamento do FAQ aprendido na knowledge base
- Colunas exatas a adicionar na tabela `Contact`

### Deferred Ideas (OUT OF SCOPE)

- Detecção de comprovante por análise de imagem (v2 — AUTO-02)
- Desconto família automático (v2 — UX-01)
- Guard contra alucinação / informações inventadas (v2 — INTL-07)
- Interface admin para revisar FAQ aprendido (backlog)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INTL-01 | Agente interpreta contexto da conversa e adapta o fluxo quando paciente muda de assunto ou dá informação fora de ordem | Seções: Interrupt Detection Pattern, Orchestrator Always-On, FSM with inline interrupt |
| INTL-02 | Agente envia "Um instante, por favor 💚" antes de operações demoradas (consulta Dietbox, busca de horários, geração de link) | Seção: Waiting Indicator Pattern |
| INTL-03 | Quando não souber responder, agente envia dúvida com contexto para 31 99205-9211 (interno), aguarda resposta, e repassa ao paciente | Seção: Escalation Relay + Pending Escalations |
| INTL-04 | Agente nunca expõe o número 31 99205-9211 diretamente ao paciente | Seção: Security Domain + Escalation 3 Paths |
| INTL-05 | Comportamento do agente alinhado com documentação oficial — tom, fluxo de etapas, mensagens fixas | Seção: Behavior Alignment, Tone Constants, Existing MSG_* Constants |
</phase_requirements>

---

## Summary

Esta fase refatora 5 arquivos principais do sistema (`router.py`, `orchestrator.py`, `atendimento.py`, `retencao.py`, `escalation.py`) e expande o modelo de dados (`models.py`) para suportar três capacidades novas: (1) detecção de interrupção de fluxo via orquestrador sempre ativo, (2) persistência de estado no Redis substituindo o dict `_AGENT_STATE` em memória, e (3) relay bidirecional de escalação para o Breno com timeout e cobrança.

O sistema já tem a infraestrutura de base correta: Redis 7 está no docker-compose, o pacote `redis==5.0.8` está no requirements.txt, APScheduler está operacional para jobs, e o padrão FSM `etapa + _despachar()` é consistente nos dois agentes. O trabalho é refatoração cirúrgica — não reescrita. Cada um dos 3 planos (01-01, 01-02, 01-03) modifica partes bem delimitadas do codebase sem quebrar contratos existentes.

**Primary recommendation:** Implementar na ordem 01-02 → 01-01 → 01-03. Redis state serialization deve vir primeiro porque o interrupt detection (01-01) depende de conseguir salvar/restaurar estado modificado; a escalação relay (01-03) depende de ambos.

---

## Standard Stack

### Core (já no projeto — sem instalação nova necessária)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| redis | 5.0.8 | State persistence, pending escalation keys | Já no requirements.txt; Redis 7 no docker-compose |
| anthropic | 0.86.0 | Structured output para interrupt detection | Já em uso no orchestrator e atendimento |
| apscheduler | 3.10.4 | Jobs de cobrança ao Breno (15min/1h) | Já operacional no scheduler do main.py |
| alembic | 1.13.3 | Migration para novas colunas em `Contact` | Já configurado no projeto |
| sqlalchemy | 2.0.35 | ORM para Contact expandido | Já em uso |

[VERIFIED: requirements.txt + pip show redis/anthropic/apscheduler]

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | — | Serialização Redis to_dict/from_dict | Padrão Python, sem dependência extra |
| asyncio (stdlib) | — | Coordinator async para operações demoradas com waiting indicator | Já usado no stack FastAPI |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Redis HSET (hash) | Redis SET com JSON string | HSET permite campos individuais; SET é mais simples para dump completo. SET com JSON é suficiente para este escopo |
| APScheduler para cobrança | asyncio.create_task com loop | APScheduler persiste jobs; asyncio task se perde no restart. APScheduler é melhor dado o requisito D-09 |
| Arquivo JSON para FAQ aprendido | Redis ou PostgreSQL JSONB | Arquivo JSON persiste entre deploys sem infra extra, revisável manualmente. Correto para o escopo. |

**Installation:** Nenhuma nova dependência. Todo o stack necessário já está instalado.

---

## Architecture Patterns

### Recommended Project Structure (mudanças desta fase)

```
app/
├── router.py            # MODIFICAR: sempre chama orquestrador + Redis load/save
├── agents/
│   ├── orchestrator.py  # MODIFICAR: retorna interrupt_action além de agente
│   ├── atendimento.py   # MODIFICAR: to_dict/from_dict + inline interrupt handling
│   └── retencao.py      # MODIFICAR: to_dict/from_dict
├── escalation.py        # MODIFICAR: 3 caminhos + relay + pending escalations
├── models.py            # MODIFICAR: Contact com first_name, last_name, dietbox_id
├── state_manager.py     # CRIAR NOVO: RedisStateManager (load/save/delete)
└── knowledge_base.py    # MODIFICAR: add_faq_learned() + persist to file

knowledge_base/
└── faq_learned.json     # CRIAR: FAQ aprendido persistente entre deploys
```

### Pattern 1: Orchestrator Always-On com interrupt_action

**What:** O orquestrador classifica TODA mensagem, inclusive quando há agente ativo. Retorna um campo `interrupt_action` indicando o que o router deve fazer.

**When to use:** Toda mensagem inbound (D-01, D-02, D-03, D-04).

**Lógica de roteamento no router.py:**
```python
# Source: [ASSUMED] — baseado nas decisões D-01 a D-04 do CONTEXT.md

rota = rotear(mensagem=text, stage_atual=stage, primeiro_contato=primeiro_contato)
interrupt_action = rota.get("interrupt_action")  # "switch_agent" | "inline" | "continue"

agente_ativo = await state_manager.load(phone_hash)

if agente_ativo and interrupt_action == "continue":
    # Comportamento atual: processa no agente ativo
    respostas = agente_ativo.processar(text)

elif agente_ativo and interrupt_action == "inline":
    # D-03: tirar_duvida ou fora_de_contexto — responde inline e volta à etapa atual
    respostas = [rota["resposta_inline"]]

elif interrupt_action == "switch_agent":
    # D-02: remarcar/cancelar/duvida_clinica — descarta agente ativo, roteia para novo
    await state_manager.delete(phone_hash)
    agente_ativo = None
    # cai para roteamento normal abaixo

# ... roteamento normal para atendimento / retencao / escalacao
await state_manager.save(phone_hash, agente_ativo)
```

**Orchestrator changes — campos adicionados ao retorno de `rotear()`:**
```python
# orchestrator.py: rotear() passa a retornar também:
{
    "interrupt_action": "switch_agent" | "inline" | "continue" | None,
    "resposta_inline": str | None,  # preenchido quando interrupt_action == "inline"
    # ... campos existentes mantidos
}
```

**Mapeamento intenção → interrupt_action:**
```python
_INTERRUPT_SWITCH = {"remarcar", "cancelar", "duvida_clinica"}   # D-02
_INTERRUPT_INLINE = {"tirar_duvida", "fora_de_contexto"}          # D-03
# D-04: "agendar" / "novo_lead" dentro do mesmo agente = "continue" (agente trata internamente)
```

### Pattern 2: Redis State Serialization (to_dict / from_dict)

**What:** Cada agente implementa `to_dict()` retornando JSON-serializable dict e classmethod `from_dict()` reconstituindo estado. `RedisStateManager` centraliza load/save/delete.

**When to use:** Toda persistência de estado de conversa entre mensagens.

**RedisStateManager — interface pública:**
```python
# Source: [VERIFIED: redis 5.0.8 SET/GET API — pip show redis]

class RedisStateManager:
    KEY_PREFIX = "agent_state:"

    def __init__(self, redis_url: str) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)

    async def load(self, phone_hash: str) -> AgenteAtendimento | AgenteRetencao | None:
        raw = self._client.get(f"{self.KEY_PREFIX}{phone_hash}")
        if not raw:
            return None
        data = json.loads(raw)
        tipo = data.get("_tipo")
        if tipo == "atendimento":
            return AgenteAtendimento.from_dict(data)
        if tipo == "retencao":
            return AgenteRetencao.from_dict(data)
        return None

    async def save(self, phone_hash: str, agent) -> None:
        if agent is None:
            return
        data = agent.to_dict()
        self._client.set(f"{self.KEY_PREFIX}{phone_hash}", json.dumps(data))
        # Sem TTL (D-12) — só limpa na finalizacao via delete()

    async def delete(self, phone_hash: str) -> None:
        self._client.delete(f"{self.KEY_PREFIX}{phone_hash}")
```

**to_dict / from_dict em AgenteAtendimento:**
```python
# Source: [ASSUMED] — segue campos declarados no __init__ existente

def to_dict(self) -> dict:
    return {
        "_tipo": "atendimento",
        "telefone": self.telefone,
        "phone_hash": self.phone_hash,
        "etapa": self.etapa,
        "nome": self.nome,
        "status_paciente": self.status_paciente,
        "objetivo": self.objetivo,
        "plano_escolhido": self.plano_escolhido,
        "modalidade": self.modalidade,
        "upsell_oferecido": self.upsell_oferecido,
        "slot_escolhido": self.slot_escolhido,
        "forma_pagamento": self.forma_pagamento,
        "pagamento_confirmado": self.pagamento_confirmado,
        "id_paciente_dietbox": self.id_paciente_dietbox,
        "id_agenda_dietbox": self.id_agenda_dietbox,
        "historico": self.historico[-20:],  # cap para evitar crescimento ilimitado
    }

@classmethod
def from_dict(cls, data: dict) -> "AgenteAtendimento":
    agent = cls(telefone=data["telefone"], phone_hash=data["phone_hash"])
    agent.etapa = data.get("etapa", "boas_vindas")
    agent.nome = data.get("nome")
    # ... demais campos
    agent.historico = data.get("historico", [])
    return agent
```

**Redis key deletion no finalizacao:**
```python
# Em router.py, após processar o agente:
if isinstance(agent, AgenteAtendimento) and agent.etapa == "finalizacao":
    await state_manager.delete(phone_hash)
else:
    await state_manager.save(phone_hash, agent)
```

### Pattern 3: Escalation Relay Bidirecional com Pending Table

**What:** Quando Ana não sabe responder (D-06, D-07), registra uma `PendingEscalation` no banco, envia contexto para Breno, e "congela" a conversa aguardando resposta. Quando Breno responde (via webhook), o sistema reconhece a mensagem vinda do número interno, recupera o paciente pendente, repassa a resposta, salva no FAQ aprendido, e fecha a escalação.

**Pending escalation — nova tabela no models.py:**
```python
# Source: [ASSUMED] — design baseado nos requisitos D-06 a D-11

class PendingEscalation(Base):
    __tablename__ = "pending_escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False)  # paciente
    pergunta_original: Mapped[str] = mapped_column(Text)
    contexto: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="aguardando")
    # aguardando | respondido | timeout
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resposta_breno: Mapped[str | None] = mapped_column(Text)
    next_reminder_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
```

**Fluxo escalação (router.py):**
```python
# Mensagem vinda do número interno (Breno respondeu)
if phone == _NUMERO_INTERNO_E164:
    await _processar_resposta_breno(phone_hash, text, meta)
    return

# Ana não sabe → cria pending escalation
async def _escalar_para_breno(phone, phone_hash, text, meta, nome, historico):
    await meta.send_text(phone, "Só um instante, vou verificar essa informação 💚")
    escalacao = await criar_pending_escalation(phone_hash, phone, text, historico)
    await meta.send_text(_NUMERO_INTERNO_E164, build_contexto_escalacao(...))
    # APScheduler job agendado para cobranças (D-09)
```

**Cobrança ao Breno — APScheduler:**
```python
# Source: [VERIFIED: APScheduler 3.10.4 já em uso no projeto]
# Implementação: job único por escalação, re-agenda a si mesmo

def _cobrar_breno_job(escalacao_id: str):
    with SessionLocal() as db:
        esc = db.get(PendingEscalation, escalacao_id)
        if not esc or esc.status != "aguardando":
            return  # já foi respondida ou cancelada
        # Envia lembrete para Breno
        # Agenda próximo reminder baseado em reminder_count:
        # reminder_count 0-3 (primeiros 4 = 15min cada) → próximo em 15min
        # reminder_count >= 4 → próximo em 1h
        if esc.reminder_count == 0:
            # Notifica paciente de 1h de espera (D-10)
            asyncio.run(meta.send_text(esc.phone_e164, "Ainda estou verificando..."))
```

### Pattern 4: Waiting Indicator (INTL-02)

**What:** Antes de qualquer chamada bloqueante (Dietbox, Rede link), enviar "Um instante, por favor 💚" como primeira mensagem no `_enviar()` call, antes do `await` da operação.

**Implementação no atendimento.py:**
```python
# Source: [ASSUMED] — baseado em D-21 do CONTEXT.md

async def _etapa_agendamento_com_indicator(self) -> list[str]:
    # A primeira mensagem da lista é o waiting indicator
    # router.py envia imediatamente antes de chamar a operação demorada
    return ["Um instante, por favor 💚"] + await _buscar_slots_e_formatar(...)

# Alternativa (mais simples): router.py injeta o indicator
# antes de chamar agent.processar() para etapas conhecidas como demoradas
```

**Recomendação:** Injetar waiting indicator no `router.py` antes das etapas `agendamento` e `forma_pagamento` (cartão), não dentro do agente — mantém o agente síncrono e testável.

### Pattern 5: Contact Profile Expansion + Return Patient Recognition

**What:** Adicionar `first_name`, `last_name`, `dietbox_patient_id` na tabela `Contact`. No `router.py`, carregar o perfil antes do agente e pré-popular o agente com o nome já conhecido.

**Novas colunas (Alembic migration):**
```python
# app/models.py — Contact
first_name: Mapped[str | None] = mapped_column(String(100))
last_name: Mapped[str | None] = mapped_column(String(100))
dietbox_patient_id: Mapped[int | None] = mapped_column(Integer)
# collected_name já existe — pode coexistir como "nome completo como digitado"
```

**Reconhecimento de retorno em router.py:**
```python
nome_conhecido = contact.first_name or contact.collected_name
if nome_conhecido and not primeiro_contato:
    # Cria agente pré-populado com nome (pula pergunta de nome)
    agent = AgenteAtendimento(telefone=phone, phone_hash=phone_hash)
    agent.nome = nome_conhecido
    agent.etapa = "qualificacao"  # pula boas_vindas que pede nome
    # router envia saudação de retorno antes
    await _enviar(meta, phone, [f"Ei {nome_conhecido}! Lembro que já nos falamos 💚 Como posso te ajudar?"])
```

### Pattern 6: FAQ Aprendido — Persistência em Arquivo JSON

**What:** Quando Breno responde uma escalação, a resposta é salva em `knowledge_base/faq_learned.json`. O `KnowledgeBase.faq_combinado()` já lê este arquivo (`faq_minerado`). Adicionar `add_faq_learned()` ao KnowledgeBase para salvar novas entradas.

```python
# Source: [VERIFIED: knowledge_base.py já tem _load_json("faq.json") e faq_combinado()]

# app/knowledge_base.py
def add_faq_learned(self, pergunta: str, resposta: str) -> None:
    """Persiste uma resposta aprendida no faq_learned.json."""
    path = _KB_DIR / "faq_learned.json"
    items: list[dict] = []
    if path.exists():
        items = json.loads(path.read_text(encoding="utf-8"))
    items.append({
        "question": pergunta,
        "suggested_answer": resposta,
        "frequency": 2,  # >1 para aparecer em faq_combinado()
        "source": "breno",
        "learned_at": datetime.now(UTC).isoformat(),
    })
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    self.faq_minerado = items  # atualiza em memória também
```

### Anti-Patterns to Avoid

- **Não chamar o orquestrador apenas quando não há agente ativo:** O padrão atual do `router.py` skippa o orquestrador quando `agente_ativo is not None`. D-01 proíbe isso. Reescrever para chamar sempre.
- **Não usar TTL no Redis para estado de fluxo:** D-12 exige sem TTL automático. Não adicionar `ex=` no `redis.set()`.
- **Não expor o número do Breno em nenhuma mensagem ao paciente:** INTL-04 / D-08. Verificar em tests.
- **Não criar jobs APScheduler duplicados:** Usar `replace_existing=True` e `id` único baseado em `escalacao_id`.
- **Não bloquear o event loop asyncio com redis.Redis síncrono:** O cliente `redis` padrão é síncrono. Chamar em `run_in_executor` ou usar `redis.asyncio.Redis` (disponível no redis-py 4+). [VERIFIED: redis 5.0.8 inclui `redis.asyncio`]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Redis connection pooling | Pool manual de connections | `redis.Redis.from_url()` | Connection pooling built-in, thread-safe |
| Agendamento de lembretes de cobrança | Loop asyncio com sleep | APScheduler job com `id` único | APScheduler persiste no SQLAlchemy job store — sobrevive a restarts |
| Serialização de estado | Pickle | `json.dumps(to_dict())` | Pickle é inseguro; JSON é legível/debugável e já é o padrão do projeto |
| Detecção de interrupção por keywords | Lista enorme de palavras-chave | Classificação LLM já existente no orchestrator | A classificação LLM já distingue `remarcar`/`cancelar`/`duvida_clinica` com alta acurácia |
| Relay de mensagens Breno→paciente | Armazenar número do Breno no estado do agente | Tabela `PendingEscalation` indexada por `phone_hash` | O número do Breno é o mesmo para todas escalações; índice por `phone_hash` do paciente |

**Key insight:** O projeto já tem APScheduler, Redis e SQLAlchemy operacionais. Todos os problemas desta fase têm solução nativa nessa stack.

---

## Common Pitfalls

### Pitfall 1: Redis sync em FastAPI async — bloqueio do event loop
**What goes wrong:** `redis.Redis` (síncrono) chamado diretamente em função `async def` bloqueia o event loop do uvicorn, causando latência para todos os usuários simultâneos.
**Why it happens:** `redis.Redis` usa socket síncrono; FastAPI é async.
**How to avoid:** Usar `redis.asyncio.Redis` (disponível em redis-py 4+, incluso no 5.0.8) para operações em contexto async. Ou envolver em `asyncio.get_event_loop().run_in_executor(None, ...)`.
**Warning signs:** Requests ficam lentos quando há múltiplos usuários simultâneos.
[VERIFIED: redis 5.0.8 — `redis.asyncio` module exists]

### Pitfall 2: APScheduler com múltiplos processos gera jobs duplicados
**What goes wrong:** Se uvicorn roda com `--workers 2+` ou gunicorn multi-process, cada processo cria seu próprio scheduler → jobs de cobrança rodam N vezes por escalação.
**Why it happens:** APScheduler é iniciado no lifespan de cada worker.
**How to avoid:** Garantir `workers=1` no uvicorn de produção (já é o padrão no docker-compose atual) ou usar `SQLAlchemyJobStore` com `replace_existing=True` e `id` único — jobs com o mesmo ID não duplicam mesmo com múltiplos schedulers.
**Warning signs:** Breno recebe N mensagens de cobrança em vez de 1.
[VERIFIED: APScheduler 3.10.4 docs — `replace_existing=True` comportamento]

### Pitfall 3: Orquestrador sempre ativo aumenta latência e custo
**What goes wrong:** Chamar o LLM de classificação em TODA mensagem (D-01) aumenta o tempo de resposta em ~300-600ms e custo por mensagem.
**Why it happens:** Antes, o orquestrador só era chamado quando não havia agente ativo.
**How to avoid:** Aceitar o tradeoff (é um requisito locked). Mitigar mantendo `max_tokens=100` no classificador (já está assim). Para etapas onde a resposta nunca pode interromper (ex: `pagamento` após já ter clicado PIX), o router pode optar por não chamar o orquestrador — mas isso é otimização de v2.
**Warning signs:** Latência aumenta. Monitorar tempo médio de resposta após implementação.

### Pitfall 4: Estado Redis inconsistente se save falha após processar
**What goes wrong:** `agent.processar(msg)` modifica o estado do agente em memória, mas se `state_manager.save()` falha (Redis down), próxima mensagem carrega estado antigo.
**Why it happens:** Operações de save não são transacionais com a lógica do agente.
**How to avoid:** Try/except em torno do save, com log de erro. D-15 cobre este caso: se load falha, criar estado novo e pedir dados novamente. Se save falha, logar e continuar (perda de estado aceitável conforme D-15).
**Warning signs:** Paciente repetindo informações que já tinha fornecido.

### Pitfall 5: Breno responde mas webhook não identifica a mensagem como resposta de escalação
**What goes wrong:** Quando Breno envia mensagem de volta para o número do WhatsApp Business, o webhook recebe normalmente — mas o sistema não sabe que é uma resposta para um paciente específico, e trata como nova conversa.
**Why it happens:** O webhook não diferencia mensagens por remetente de forma especial.
**How to avoid:** Em `router.py`, verificar se `phone_e164 == _NUMERO_INTERNO_E164` ANTES de qualquer outra lógica. Se sim, buscar `PendingEscalation` com status `aguardando` ordenado por `created_at`. Repassar a resposta ao paciente correspondente.
**Warning signs:** Mensagens do Breno sendo tratadas como novo atendimento.

### Pitfall 6: `collected_name` vs `first_name`/`last_name` — duplicidade de campo
**What goes wrong:** Adicionar `first_name` sem deprecar `collected_name` cria dois campos com a mesma semântica, causando confusão em qual usar.
**Why it happens:** `collected_name` já existe e é usado em vários lugares.
**How to avoid:** Manter `collected_name` como campo legado (compatibilidade); `first_name`/`last_name` como campos novos. `router.py` usa `first_name or collected_name` para reconhecimento de retorno. Na etapa de coleta de nome do agente, salvar tanto `agent.nome` quanto `contact.first_name`.

---

## Code Examples

### Redis Async Connection (padrão recomendado)
```python
# Source: [VERIFIED: redis 5.0.8 — redis.asyncio module]
import redis.asyncio as aioredis

async def get_redis_client() -> aioredis.Redis:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    return aioredis.Redis.from_url(url, decode_responses=True)
```

### APScheduler job para cobrança — evitar duplicatas
```python
# Source: [VERIFIED: APScheduler 3.10.4 em uso no app/remarketing.py]
from datetime import datetime, timedelta, UTC

def agendar_cobranca_breno(scheduler, escalacao_id: str, delay_minutos: int):
    run_at = datetime.now(UTC) + timedelta(minutes=delay_minutos)
    scheduler.add_job(
        _cobrar_breno_job,
        "date",
        run_date=run_at,
        id=f"breno_reminder_{escalacao_id}_{delay_minutos}",
        args=[escalacao_id],
        replace_existing=True,
    )
```

### Alembic migration para novas colunas
```python
# Source: [VERIFIED: Alembic 1.13.3 em uso no projeto]
# alembic/versions/xxx_add_contact_profile_columns.py
def upgrade():
    op.add_column("contacts", sa.Column("first_name", sa.String(100), nullable=True))
    op.add_column("contacts", sa.Column("last_name", sa.String(100), nullable=True))
    op.add_column("contacts", sa.Column("dietbox_patient_id", sa.Integer, nullable=True))

def downgrade():
    op.drop_column("contacts", "first_name")
    op.drop_column("contacts", "last_name")
    op.drop_column("contacts", "dietbox_patient_id")
```

### Identificação do remetente interno no router
```python
# Source: [ASSUMED] — baseado em escalation.py:_NUMERO_INTERNO existente
_NUMERO_INTERNO_E164 = "5531992059211"  # já definido em escalation.py

async def route_message(phone: str, phone_hash: str, text: str, meta_message_id: str):
    # PRIMEIRO: verificar se é resposta do Breno
    if phone == _NUMERO_INTERNO_E164:
        await _processar_resposta_breno(text, meta)
        return
    # ... resto do fluxo normal
```

---

## Runtime State Inventory

Esta fase não é renaming/refactoring de strings, mas envolve mudança de onde o estado de conversa é guardado (in-memory → Redis). Inventário das implicações de runtime:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (in-memory) | `_AGENT_STATE` dict em `router.py` — perdido a cada restart | Substituir por Redis; sem dados a migrar (estado é efêmero) |
| Stored data (Redis) | Redis 7 vazio inicialmente — sem dados pré-existentes a migrar | Nenhuma migração; novos estados escritos após deploy |
| Live service config | Docker Compose: Redis porta 6379 já configurado e com healthcheck | Nenhuma mudança de config necessária |
| OS-registered state | APScheduler jobs em SQLAlchemy job store — novos jobs de cobrança | Tabela `apscheduler_jobs` gerada automaticamente pelo APScheduler |
| Secrets/env vars | `REDIS_URL` já deve estar no `.env` (referenciado no código); verificar `.env.example` | Confirmar que `REDIS_URL=redis://redis:6379` está no `.env.example` |
| Build artifacts | Nenhum — projeto não é pacote instalável | None |
| Database migrations | `contacts` precisa de 3 novas colunas; nova tabela `pending_escalations` | 2 arquivos de migration Alembic necessários |

**Nothing found in category:** Build artifacts — None, verificado pela ausência de `setup.py`/`pyproject.toml` no projeto.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Redis (server) | 01-02 Redis state | ✓ (docker-compose) | 7-alpine | — (sem fallback; D-15 cobre Redis down em runtime) |
| redis-py | 01-02 serialization | ✓ | 5.0.8 | — |
| APScheduler | 01-03 cobrança Breno | ✓ | 3.10.4 | — |
| Alembic | 01-01/01-03 migrations | ✓ | 1.13.3 | create_all fallback já em main.py |
| anthropic SDK | 01-01 orchestrator | ✓ | 0.86.0 | fallback "novo_lead" já implementado |
| PostgreSQL | 01-03 PendingEscalation | ✓ (docker-compose) | 15-alpine | SQLite em dev (DATABASE_URL auto-detecta) |

**Missing dependencies with no fallback:** Nenhuma — todo o stack está disponível.

**Note:** Redis não está acessível localmente fora do Docker (`redis-cli ping` retornou "not accessible"), mas está corretamente configurado no docker-compose. Testes devem mockar Redis; integração funciona dentro do container.
[VERIFIED: docker-compose.yml redis service + redis-cli check]

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.2 + pytest-asyncio 0.24.0 |
| Config file | `pytest.ini` (pythonpath=., testpaths=tests) |
| Quick run command | `python -m pytest tests/test_router.py tests/test_integration.py -q` |
| Full suite command | `python -m pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTL-01 | Paciente muda de assunto no meio do fluxo; Ana retoma contexto sem resetar | integration | `pytest tests/test_integration.py::test_interrupt_detection -x` | ❌ Wave 0 |
| INTL-01 | Intenção inline (tirar_duvida) respondida sem sair da etapa | unit | `pytest tests/test_router.py::test_inline_interrupt_stays_in_flow -x` | ❌ Wave 0 |
| INTL-02 | Waiting indicator enviado antes de consulta Dietbox | unit | `pytest tests/test_integration.py::test_waiting_indicator_antes_slots -x` | ❌ Wave 0 |
| INTL-03 | Escalação para Breno cria PendingEscalation e envia contexto | unit | `pytest tests/test_escalation.py::test_pending_escalation_criada -x` | ❌ Wave 0 |
| INTL-03 | Resposta do Breno chega e é repassada ao paciente | integration | `pytest tests/test_escalation.py::test_relay_breno_para_paciente -x` | ❌ Wave 0 |
| INTL-04 | Número 31 99205-9211 nunca aparece em mensagem ao paciente | unit | `pytest tests/test_escalation.py::test_numero_interno_nao_exposto -x` | ❌ Wave 0 |
| INTL-05 | MSG_BOAS_VINDAS usa "Eiii" / tom informal conforme docs | unit | `pytest tests/test_behavior_alignment.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_router.py tests/test_integration.py -q`
- **Per wave merge:** `python -m pytest tests/ -q`
- **Phase gate:** Full suite green antes do `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/test_escalation.py` — cobre INTL-03, INTL-04 (relay Breno ↔ paciente, número não exposto)
- [ ] `tests/test_behavior_alignment.py` — cobre INTL-05 (tom, mensagens fixas vs docs)
- [ ] `tests/test_state_manager.py` — cobre RedisStateManager com mock de redis
- [ ] Tests de interrupt detection em `test_integration.py` e `test_router.py`

**Nota:** `tests/test_router.py` (existente, 44 linhas) já testa roteamento básico. Será expandido — não recriado.

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Sistema usa phone_hash; sem login |
| V3 Session Management | yes | Estado Redis por phone_hash; sem TTL = sessão permanente por design (D-12) |
| V4 Access Control | yes | Número interno (Breno) deve ter path separado no router; nunca exposto ao paciente |
| V5 Input Validation | yes | `pergunta_original` truncada antes de salvar; histórico capped a 20 entradas |
| V6 Cryptography | no | Dados sensíveis não criptografados no Redis (apenas estado de fluxo, não PII clínico) |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Paciente enviando número de telefone do Breno para tentar ser tratado como escalação | Spoofing | Router verifica `phone == _NUMERO_INTERNO_E164` usando o número E164 real; paciente não conhece o número |
| Redis dump expõe histórico de conversa | Information Disclosure | Histórico capped a 20 mensagens; não incluir dados de pagamento (link, CPF) no estado Redis — apenas referências |
| APScheduler job de cobrança disparando para escalação já respondida | Denial of Service (leve) | Job verifica `esc.status != "aguardando"` antes de enviar; `replace_existing=True` evita acúmulo |
| FAQ aprendido sendo populado com resposta incorreta do Breno | Tampering | faq_learned.json é revisável manualmente (D-11); não substituir FAQ estático, apenas enriquecer |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `redis.asyncio` está disponível em redis-py 5.0.8 | Standard Stack / Code Examples | Sem async Redis — usar run_in_executor como fallback (não bloqueia) |
| A2 | Usar `to_dict()/from_dict()` como interface pública nos agentes (campos exatos) | Pattern 2 | Campos faltando podem causar KeyError no from_dict — coberto por testes |
| A3 | Mensagem do Breno chega pelo mesmo webhook WhatsApp que as mensagens dos pacientes | Pattern 3 / Pitfall 5 | Se Breno usa número diferente do Meta API — toda a lógica de relay muda |
| A4 | APScheduler pode agendar job por `date` com `id` único sem conflito com jobs existentes de remarketing | Pattern 3 / Pitfall 2 | IDs de jobs de cobrança colidirem com remarketing — usar prefixo `breno_reminder_` |
| A5 | Formato do FAQ aprendido compatível com `faq_combinado()` existente (campo `frequency > 1`) | Pattern 6 | FAQ aprendido não aparece nas respostas — verificável em tests |

---

## Open Questions

1. **Número interno do Breno no webhook — mesmo número Meta Business?**
   - What we know: `_NUMERO_INTERNO = "5531992059211"` definido em `escalation.py`. O webhook já recebe mensagens deste número se ele estiver na mesma conta Meta.
   - What's unclear: Breno usa o mesmo número WhatsApp que está cadastrado no Meta Business? Ou é um número pessoal separado?
   - Recommendation: Confirmar com Breno antes de implementar o relay. Se for número diferente do Meta Business, o webhook não receberá as respostas automaticamente — seria necessário outro mecanismo (ex: Breno responde via interface admin).

2. **Persistência do FAQ aprendido entre deploys de Docker**
   - What we know: `knowledge_base/` é montado como volume read-only: `./knowledge_base:/app/knowledge_base:ro` no docker-compose.
   - What's unclear: Com volume `:ro`, não é possível escrever `faq_learned.json` de dentro do container.
   - Recommendation: Mudar volume para read-write ou salvar o FAQ no PostgreSQL (tabela `learned_faq`). Planner deve decidir baseado em D-11 ("persiste entre deploys, revisável").

3. **Tom de voz — "Eiii" vs "Olá" nas mensagens fixas existentes**
   - What we know: `MSG_BOAS_VINDAS` atual usa "Olá! Que bom ter você por aqui 💚". CONTEXT.md D-18 exige "Eiii", "Perfeitoooo", "Obrigadaaa".
   - What's unclear: Quão extenso é o realinhamento de mensagens (INTL-05)?
   - Recommendation: Planner deve incluir task dedicada para revisar TODOS os `MSG_*` constants em `atendimento.py` e `retencao.py` contra a documentação oficial.

---

## Sources

### Primary (HIGH confidence)
- Codebase `app/router.py` — padrão atual de roteamento e `_AGENT_STATE` in-memory
- Codebase `app/agents/orchestrator.py` — classificador LLM existente, IntencaoType
- Codebase `app/agents/atendimento.py` — FSM com 10 etapas, campos de estado, `historico`
- Codebase `app/escalation.py` — função de escalação existente, `_NUMERO_INTERNO`
- Codebase `app/models.py` — Contact, tabelas existentes
- Codebase `app/knowledge_base.py` — `faq_minerado`, `faq_combinado()`, `add_faq_learned` ponto de extensão
- Codebase `docker-compose.yml` — Redis 7, PostgreSQL 15 configurados
- Codebase `requirements.txt` — versões exatas de todas as dependências
- [VERIFIED: pip show redis] — redis-py 5.0.8 instalado localmente
- [VERIFIED: pip show anthropic] — anthropic 0.86.0 instalado
- [VERIFIED: pip show apscheduler] — APScheduler 3.10.4 instalado

### Secondary (MEDIUM confidence)
- docker-compose.yml volume `:ro` para knowledge_base — [VERIFIED: linha 16 do arquivo]
- APScheduler `replace_existing=True` comportamento — [VERIFIED: já em uso em `app/remarketing.py`]

### Tertiary (LOW confidence)
- Comportamento do webhook Meta recebendo mensagens do número do Breno — não testado/verificado
- redis.asyncio availability confirmada via redis-py 5.0.8 docs — [ASSUMED: baseado em versão]

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — todas as dependências verificadas via pip show e requirements.txt
- Architecture patterns: MEDIUM-HIGH — padrões baseados em codebase existente + requisitos locked
- Pitfalls: HIGH — identificados diretamente do código existente e dos requisitos
- Open questions: precisam de resposta humana antes de implementação (especialmente Q1 e Q2)

**Research date:** 2026-04-08
**Valid until:** 2026-05-08 (stack estável; Anthropic SDK pode ter updates menores)
