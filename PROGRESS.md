# PROGRESS — Agente Ana (atualizado automaticamente)

## Estado atual

**Fase 1 — COMPLETA** ✅
**Fase 2 — Infraestrutura COMPLETA** ✅ (59/59 testes, Docker rodando)
**Fase 3 — Multi-agentes COMPLETA** ✅ (104/104 testes)

## Próxima tarefa a executar

**Configurar credenciais reais no `.env` e testar com sandbox Meta**

---

## Plano de implementação — Agentes 3, 4, 0, 1, 2

### Agente 3 — Worker Dietbox (`app/agents/dietbox_worker.py`)
Porta e adapta o código existente de `C:\Users\Breno\Desktop\thay\`.

**Funções necessárias:**
- `consultar_horarios_disponiveis(data_inicio, data_fim)` → lista de slots livres
- `cadastrar_paciente(dados)` → retorna id_paciente
- `agendar_consulta(id_paciente, datetime, modalidade, plano)` → retorna id_agendamento
- `lancar_financeiro(id_paciente, id_agendamento, valor, forma_pagamento)` → confirma
- `buscar_paciente_por_telefone(telefone)` → retorna dados ou None
- `buscar_dados_paciente(id_paciente)` → retorna dict com dados completos

**Arquivos a criar:**
- `app/agents/__init__.py`
- `app/agents/dietbox_worker.py` (porta de `C:\Users\Breno\Desktop\thay\dietbox.py` + `dietbox_auth.py`)
- `tests/test_dietbox_worker.py`

**Notas técnicas:**
- Auth via Playwright (Azure AD B2C) — já funcional em `thay/`
- Token cache em arquivo JSON (já implementado)
- API base: `https://api.dietbox.me/v2`
- Adicionar `playwright` ao `requirements.txt`

---

### Agente 4 — Gateway Rede (`app/agents/rede_worker.py`)
Integração com userede.com.br para geração de links de pagamento por cartão.

**Funções necessárias:**
- `gerar_link_pagamento(valor_centavos, parcelas, descricao)` → retorna URL do link
- `consultar_status_pagamento(id_transacao)` → retorna status

**Pesquisar:** API REST da Rede (userede.com.br) — credenciais necessárias: PV (número de afiliação) + token de integração.

**Arquivos a criar:**
- `app/agents/rede_worker.py`
- `tests/test_rede_worker.py`

---

### Agente 0 — Orquestrador (`app/agents/orchestrator.py`)
Substitui o `app/router.py` atual. Classifica intenção via Claude Haiku e roteia.

**Intenções a classificar:**
- `novo_lead` → Agente 1
- `tirar_duvida` → Agente 1
- `agendar` → Agente 1
- `pagar` → Agente 1
- `remarcar` → Agente 2
- `cancelar` → Agente 2
- `lembrete` → Agente 2 (disparado por scheduler, não por mensagem)
- `fora_de_contexto` → resposta padrão
- `duvida_clinica` → escalação para nutricionista

---

### Agente 1 — Atendimento Geral (`app/agents/atendimento.py`)
Fluxo completo das 10 etapas com base de conhecimento embutida.

**Etapas:**
1. Boas-vindas + coleta nome/status
2. Qualificação do objetivo
3. Apresentação dos planos (envia PDF)
4. Qualificação da escolha + upsell
5. Agendamento (consulta Dietbox, oferece 3 opções)
6. Forma de pagamento (PIX ou cartão)
7. Pagamento (PIX: chave CPF | Cartão: link Rede)
8. Cadastro no Dietbox
9. Confirmação (presencial ou online, com arquivos)
10. Finalização (altera etiqueta para "OK")

**Base de conhecimento embutida:**
- Planos e valores (Premium, Ouro, Com Retorno, Única, Formulário)
- Horários de atendimento
- Políticas (pagamento, cancelamento, tolerância)
- FAQ completo
- Regras de upsell
- Chave PIX: 14994735670
- Número da nutri (enviar ao paciente): 5531991394759
- Número interno (NUNCA enviar): 31 99205-9211

---

### Agente 2 — Retenção (`app/agents/retencao.py`)
Remarketing + lembretes de consulta + remarcação/cancelamento.

**Funções:**
- Sequência de remarketing: 3 mensagens (24h, 7d, 30d)
- Lembrete 24h antes da consulta (via scheduler APScheduler)
- Fluxo de remarcação (consulta Dietbox, prazo 7 dias)
- Fluxo de cancelamento

---

### Outros módulos necessários

**`app/media_handler.py`** — Leitura de mídia recebida:
- PDFs (comprovantes de pagamento)
- Imagens (comprovantes)
- Áudios (transcrição via Whisper ou similar)

**`app/knowledge_base.py`** — Carrega e serve a base de conhecimento:
- Lê `knowledge_base/` gerado na Fase 1
- Serve para os agentes 1 e 2
- Inclui dados estáticos (planos, FAQ, políticas) do doc V2.0

**`app/tags.py`** — Gerenciamento de etiquetas:
- novo_lead | aguardando_pagamento | agendado | remarketing | lead_perdido | OK

**`app/escalation.py`** — Escalação para humano:
- Envia contexto para 31 99205-9211 (interno)
- Timeout de 15 min em horário comercial
- NUNCA revela este número ao paciente

---

## Arquivos de mídia necessários (obter com Thaynara)
- `assets/Thaynara - Nutricionista.pdf`
- `assets/COMO-SE-PREPARAR---presencial.jpg`
- `assets/COMO-SE-PREPARAR---ONLINE.jpg`
- `assets/Guia - Circunferências Corporais - Mulheres.pdf`
- `assets/Guia - Circunferências Corporais - Homens.pdf`

---

## Ordem de execução das próximas tarefas

- [x] Agente 3: `app/agents/dietbox_worker.py` + testes (11/11 passando)
- [x] Agente 4: `app/agents/rede_worker.py` + testes — modo portal apenas, sem transação transparente (18/18)
- [x] `app/knowledge_base.py` + base de conhecimento completa
- [x] `app/tags.py`
- [x] `app/escalation.py`
- [x] `app/media_handler.py`
- [x] Agente 0: `app/agents/orchestrator.py`
- [x] Agente 1: `app/agents/atendimento.py`
- [x] Agente 2: `app/agents/retencao.py`
- [x] Refatorar `app/router.py` para usar nova arquitetura
- [x] Testes de integração end-to-end (`tests/test_integration.py` — 12 testes)
- [x] 104/104 testes passando
