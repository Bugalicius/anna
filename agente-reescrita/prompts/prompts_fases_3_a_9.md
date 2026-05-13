# FASE 5 — Fluxos 4 e 5 (Confirmação presença + Recebimento de imagem)
# ═════════════════════════════════════════════════════════════════════════

## OBJETIVO

Implementar jobs automáticos de confirmação de presença + interceptador de imagens.

## TAREFAS

### 5.1 — Scheduler com APScheduler

Cria `app/conversation_v2/scheduler.py`:

```python
"""
Scheduler — jobs automáticos do agente.

Jobs:
- confirmacao_semanal: toda sexta às 13h
- lembrete_vespera: todo dia às 18h
- followup_24h: agendado dinamicamente após confirmação
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

@scheduler.scheduled_job('cron', day_of_week='fri', hour=13)
async def job_confirmacao_semanal():
    """Busca consultas da semana seguinte e envia confirmação."""

@scheduler.scheduled_job('cron', hour=18)
async def job_lembrete_vespera():
    """Busca consultas do dia seguinte e envia lembrete."""
```

### 5.2 — Templates de confirmação (4.9.1 e 4.9.2)

Carrega os templates do YAML `fluxo_4_confirmacao_presenca.yaml`:
- Template presencial com lembrete de short/top
- Template online com contato da Thaynara + texto pós

### 5.3 — Handlers dos botões

No orchestrator, adiciona handlers para `button_id`:
- `confirmar_presenca` → marca confirmada no Dietbox + responde "Confirmado então! Obrigadaaa 💚😉"
- `remarcar_consulta` → ativa Fluxo 2

### 5.4 — Follow-ups

- 24h após confirmação enviada sem resposta: manda "{nome}?"
- Sem resposta após véspera: notifica Breno (humano decide se desmarca)
- **Nunca desmarca automaticamente sem aprovação humana**

### 5.5 — Implementar Fluxo 5 (Recebimento de Imagem) como interceptador

Cria `app/conversation_v2/interceptors/image_interceptor.py`:

```python
"""
Interceptor — quando chega imagem, classifica ANTES de qualquer ação do fluxo principal.
"""

async def interceptar_imagem(payload, state) -> InterceptResult:
    """
    1. Classifica via Gemini Vision
    2. Se comprovante: roteia para validação
    3. Se figurinha: responde "Hihi 💚 Como posso te ajudar?"
    4. Se foto qualquer: responde adequado ao contexto
    """
```

### 5.6 — Validação completa de comprovante

Implementa todos os 4 cenários de valor:
- Exato sinal → aprova + saldo
- Acima sinal abaixo total → aprova + saldo restante
- Total → aprova quitado
- Abaixo sinal → pede complemento

**Sempre encaminha comprovante aprovado pra Thaynara.**

### 5.7 — Testes

Mínimo 10 cenários cada fluxo:
- Confirmação semanal: envio, resposta confirmar, resposta remarcar, sem resposta, follow-up
- Imagens: comprovante OK, sticker, foto aleatória, imagem ilegível, PDF

## TESTE DE ACEITAÇÃO

✓ Jobs rodando (testar manualmente disparando scheduler)  
✓ Templates 4.9.1 e 4.9.2 corretos  
✓ Interceptor de imagem funcionando  
✓ Encaminhamento pra Thaynara testado  

## AO TERMINAR

```
✅ FASE 5 CONCLUÍDA
Aguardando prompt da Fase 6.
```


# ═════════════════════════════════════════════════════════════════════════
# FASE 6 — Fluxos 6 e 7 (Dúvidas + Casos especiais)
# ═════════════════════════════════════════════════════════════════════════

## OBJETIVO

Implementar Fluxo 6 (Dúvidas) e Fluxo 7 (Casos especiais).

## TAREFAS

### 6.1 — Classificador de dúvida

No interpreter, adiciona classificação de subcategorias:
- duvida_operacional
- duvida_clinica
- duvida_sobre_thaynara
- duvida_sobre_clinica
- duvida_processo
- pergunta_indicacao
- pergunta_dupla_familia

### 6.2 — Knowledge base de FAQ

Carrega `faq.json` e implementa busca por similaridade textual. Se match acima de threshold, usa resposta direta. Senão, modo improviso com instrução restritiva.

### 6.3 — Knowledge base de objeções

Carrega `objections.json` e implementa matching por triggers.

### 6.4 — Escalação de dúvida clínica

Implementa diferenciação:
- Paciente existente: envia contato da Thaynara
- Lead novo: escala silenciosamente pro Breno + aguarda resposta + adapta tom Ana

### 6.5 — Detectores de casos especiais

Cria detectores no interpreter:
- Gestante (texto contém "grávida", "gestante", etc)
- Menor 16 (calcula idade pela data nascimento)
- Terceiro (texto sugere marcação pra outra pessoa)
- B2B (tom corporativo, CNPJ, oferta comercial)

### 6.6 — Fluxo de marcação pra terceiro

Implementa estados específicos:
- Coleta dados do paciente real (não quem conversa)
- Distingue quem_marca vs paciente
- Suporta "fala com ela" (repassa contato pra outro número)

### 6.7 — Consulta em dupla

Implementa modo dupla:
- Coleta dados de ambos
- Aplica 10% desconto
- Busca 2 horários sequenciais no Dietbox
- Cria 2 agendamentos + 2 lançamentos financeiros

### 6.8 — B2B

Resposta única + flag ignorar 24h + notifica Breno

### 6.9 — Programa de Indicação

Resposta padrão sobre recompensas

## TESTE DE ACEITAÇÃO

✓ FAQ funcionando com matching  
✓ Objeções respondidas corretamente  
✓ Casos especiais detectados e tratados  
✓ Modo dupla funciona ponta a ponta  

## AO TERMINAR

```
✅ FASE 6 CONCLUÍDA
Aguardando prompt da Fase 7.
```


# ═════════════════════════════════════════════════════════════════════════
# FASE 7 — Fluxos 8, 9 e 10 (Comandos + Mídias + Fora de contexto)
# ═════════════════════════════════════════════════════════════════════════

## TAREFAS

### 7.1 — Comandos internos (Fluxo 8)

Implementa em `app/conversation_v2/command_processor.py`:

- Detecta números autorizados (Thaynara, Breno)
- Interpreta comando via Gemini (linguagem livre)
- Executa: status, perguntar troca, cancelar, remarcar, responder escalação, enviar mensagem
- Confirma de volta pra quem pediu

### 7.2 — Mídias não textuais (Fluxo 9)

Áudio via Gemini, sticker, localização, vídeo, documento.

### 7.3 — Fora de contexto (Fluxo 10)

Contador que zera quando paciente volta ao fluxo. Escala após 2 consecutivas.

## TESTE DE ACEITAÇÃO

✓ Comandos da Thaynara/Breno funcionando  
✓ Áudio sendo transcrito  
✓ Fora de contexto escalando corretamente  

## AO TERMINAR

```
✅ FASE 7 CONCLUÍDA
Aguardando prompt da Fase 8.
```


# ═════════════════════════════════════════════════════════════════════════
# FASE 8 — Testes E2E e validação
# ═════════════════════════════════════════════════════════════════════════

## OBJETIVO

Rodar bateria completa de testes E2E baseados em conversas reais.

## TAREFAS

### 8.1 — Carregar conversas reais como casos de teste

Usa `conversas_export.json` (1.283 conversas). Seleciona 50 conversas representativas:
- 20 agendamentos completos
- 10 remarcações
- 5 cancelamentos
- 5 confirmações
- 10 casos diversos (dúvidas, fora contexto, gestante, etc)

### 8.2 — Test runner E2E

Cria `tests/conversation_v2/e2e/runner.py`:

```python
"""
Runner — simula conversa replay e compara saída esperada.
"""

async def replay_conversa(conversa_real: dict) -> ReplayResult:
    """
    Para cada mensagem do paciente, alimenta o orchestrator
    e compara saída com a mensagem real da Ana.
    
    Não exige match exato — usa similaridade semântica (Gemini).
    Métrica: % de turnos com resposta semanticamente aceitável.
    """
```

### 8.3 — Bateria de testes de regra

Roda todas as regras (R1 a R16) com inputs adversariais:
- "Quem é Breno?" → bloqueia R1
- "Quanto custa? R$50?" → bloqueia R3 (valor inventado)
- "Me dá um horário no sábado" → bloqueia R4
- etc

### 8.4 — Stress test

Simula 50 conversas simultâneas com Gemini real. Mede:
- Taxa de sucesso
- Latência média por turno
- Erros 429 (rate limit)
- Uso de tokens

### 8.5 — Relatório de qualidade

Gera `RELATORIO_FASE_8.md` com:
- Taxa de sucesso por fluxo
- Latência média
- Bugs encontrados
- Regressões em relação ao agente antigo

## TESTE DE ACEITAÇÃO

✓ Bateria E2E com 50+ cenários reais  
✓ Taxa de sucesso ≥ 85%  
✓ Todas as 16 regras invioláveis passando  
✓ Stress test sem erros críticos  

## AO TERMINAR

```
✅ FASE 8 CONCLUÍDA

Relatório de qualidade: RELATORIO_FASE_8.md
Taxa de sucesso: X%
Latência média: Y ms

Aguardando prompt da Fase 9 (cutover).
```


# ═════════════════════════════════════════════════════════════════════════
# FASE 9 — Cutover (substituir agente antigo)
# ═════════════════════════════════════════════════════════════════════════

## OBJETIVO

Substituir definitivamente o agente antigo pelo novo. Limpeza final.

## ATENÇÃO

**Esta fase é IRREVERSÍVEL via git checkout.** Antes de começar, garantir que Fase 8 passou em 100% dos testes críticos.

## TAREFAS

### 9.1 — Backup definitivo do código antigo

```bash
git tag v1-antigo-backup
git push --tags
```

### 9.2 — Renomear pastas

```bash
# Move antigo para legacy
mv app/conversation app/conversation_legacy

# Promove novo
mv app/conversation_v2 app/conversation
```

### 9.3 — Atualizar imports

Roda find/replace global:
```bash
grep -rl "app.conversation_v2" app/ | xargs sed -i 's/app.conversation_v2/app.conversation/g'
grep -rl "app.conversation_legacy" app/ | xargs sed -i 's/app.conversation_legacy/_legacy_app.conversation/g'
```

### 9.4 — Atualizar webhook.py e router.py

Remove feature flag `USE_AGENT_V2`. O sistema usa orchestrator novo direto.

### 9.5 — Deletar código legacy (opcional, mas recomendado)

Após validação de 1 semana em produção, deleta:

```bash
rm -rf app/conversation_legacy
```

### 9.6 — Restart no VPS

```bash
cd /root/agente
git pull
docker compose up --build -d app
docker compose logs app --tail=50
```

### 9.7 — Smoke test em produção

Manda 5 mensagens reais via WhatsApp:
- "oi" → começa fluxo
- "quero agendar" → segue normalmente
- "1234" → mensagem confusa → trata como fora de contexto
- "qual o valor?" → responde
- "obrigada" → encerra educadamente

Cada uma deve responder corretamente. Se algum erro, reverte:

```bash
git checkout v1-antigo-backup
docker compose up --build -d app
```

### 9.8 — Atualizar documentação

Atualiza `README.md`, `ARCHITECTURE.md`, `CLAUDE.md` refletindo a nova arquitetura.

Tag de release:
```bash
git tag v2.0-reescrita
git push --tags
```

## TESTE DE ACEITAÇÃO

✓ Agente novo rodando em produção  
✓ 5 smoke tests bem-sucedidos  
✓ Logs sem erros críticos  
✓ Documentação atualizada  
✓ Tag de backup `v1-antigo-backup` no git  
✓ Tag de release `v2.0-reescrita` no git  

## AO TERMINAR

```
✅ FASE 9 CONCLUÍDA — REESCRITA FINALIZADA

Agente Ana v2.0 em produção.
Backup tag: v1-antigo-backup
Release tag: v2.0-reescrita

Acompanhar logs nas primeiras 48h:
docker compose logs app --tail=100 --follow
```
