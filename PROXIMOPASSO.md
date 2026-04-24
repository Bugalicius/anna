# PROXIMOPASSO

## 1. 📍 Status atual do sistema

### O que já foi implementado
- Orquestração principal entre `orchestrator`, `router`, `AgenteAtendimento` e `AgenteRetencao`.
- Persistência de estado dos agentes em Redis via `to_dict()` / `from_dict()`.
- Fluxo de atendimento com:
  - boas-vindas
  - qualificação
  - apresentação de planos
  - upsell
  - consulta de horários no Dietbox
  - pagamento por PIX ou cartão
  - cadastro/agendamento no Dietbox
- Fluxo de retenção com:
  - remarcação
  - cancelamento
  - lembrete
  - remarketing
- Worker Dietbox com:
  - consulta de slots
  - busca/cadastro de paciente
  - agendamento
  - alteração de agendamento
  - verificação financeira
  - cancelamento de agendamento
- Worker Rede com geração de link de pagamento.
- `/test/chat` ativo para teste conversacional sem WhatsApp real.

### O que foi corrigido
- Persistência de `_slots_oferecidos` no `AgenteAtendimento`.
- Persistência de `_slots_oferecidos` e `_preferencia_horario` no `AgenteRetencao`.
- Remarcação agora executa no mesmo turno da escolha do slot.
- `apresentacao_planos` agora lida com:
  - modalidade sem plano
  - plano sem modalidade
  - mensagens ambíguas com mais contexto
- `escolha_plano` agora trata melhor dúvidas de parcelamento, comparação e upsell.
- `forma_pagamento` agora interpreta melhor dúvidas sobre PIX x cartão.
- O `router` parou de responder com o inline genérico em etapas sensíveis de conversa.
- O atendimento não confirma mais consulta quando o Dietbox falha.
- O cancelamento agora tenta cancelar de verdade no Dietbox.

### O que ainda está quebrado ou incompleto
- O fluxo ainda é híbrido, mas continua mais FSM-first do que agentic.
- A interpretação contextual foi fortalecida no atendimento, mas ainda não foi expandida com a mesma profundidade para retenção.
- `Tag.OK` no `router` provavelmente continua inalcançável por causa da ordem do `if/elif`.
- O fluxo de pagamento ainda não confirma lançamento como pago no Dietbox após “comprovante”.
- O valor financeiro lançado no Dietbox ainda não está alinhado com a promessa comercial de “sinal de 50%”.
- O handoff `retencao -> atendimento` em alguns cenários ainda depende de nova mensagem e pode ser melhorado.
- Ainda faltam testes end-to-end reais com Dietbox e geração de link em ambiente vivo usando conversa manual.

## 2. 🧠 Arquitetura resumida

### Como os agentes se comunicam hoje
- `app/router.py` é a peça central.
- `app/agents/orchestrator.py` classifica a intenção macro da mensagem.
- `router` decide:
  - continuar no agente ativo
  - trocar de agente
  - responder inline
  - escalar
- `AgenteAtendimento` faz o fluxo comercial principal.
- `AgenteRetencao` faz remarcação/cancelamento/retenção.
- `dietbox_worker` executa ações externas no Dietbox.
- `rede_worker` executa geração de link de cartão.

### Pontos críticos do fluxo
- `router` pode atrapalhar o contexto se interceptar dúvida demais.
- `AgenteAtendimento` precisa equilibrar fluxo estruturado com interpretação contextual.
- `AgenteRetencao` ainda precisa ganhar a mesma camada de interpretação refinada.
- Integrações externas são o ponto mais frágil:
  - Dietbox
  - Rede
  - Meta

## 3. 🚨 Problemas pendentes (priorizados)

### Alta
- ✅ Alinhar financeiro com a regra comercial real:
  - hoje a conversa fala em sinal de 50%
  - mas o lançamento ainda usa o valor integral
- ✅ Marcar pagamento como pago no Dietbox quando o comprovante for aceito.
- Melhorar handoff explícito `retencao -> atendimento` em:
  - `nova_consulta`
  - `perda_retorno`
- Revisar se o cancelamento real no Dietbox exige algum payload adicional além de `desmarcada=True`.

### Média
- Levar a mesma interpretação contextual para etapas críticas de retenção.
- Revisar a lógica de `tirar_duvida` no orquestrador para reduzir falsas classificações.
- Melhorar extração de nome/plano/modalidade para mensagens mais livres.
- Reduzir dependência de heurísticas fixas em `AgenteAtendimento`.

### Baixa
- Limpar inconsistências de documentação.
- Revisar mensagens fixas para mais naturalidade.
- Melhorar observabilidade/logs para depuração de conversa real.

## 4. 🎯 Próximos passos recomendados

### Ordem correta
1. Corrigir financeiro do agendamento.
2. Confirmar pagamento no Dietbox.
3. Melhorar handoff `retencao -> atendimento`.
4. Levar interpretação contextual forte para retenção.
5. Fazer bateria manual no `/test/chat` e depois no WhatsApp real.

### Explicação simples
- Passo 1:
  ajustar `processar_agendamento()` e o valor enviado ao financeiro para refletir o sinal real prometido no chat.
- Passo 2:
  ligar a confirmação do comprovante ao `confirmar_pagamento()` do Dietbox.
- Passo 3:
  quando retenção descobrir que não é remarcação válida, trocar explicitamente para atendimento em vez de depender da próxima mensagem.
- Passo 4:
  usar a mesma abordagem de interpretação por etapa no `AgenteRetencao`.
- Passo 5:
  validar na prática:
  - conversa livre
  - agendamento
  - remarcação
  - cancelamento
  - link de pagamento

## 5. 🛠️ Instruções técnicas para continuar amanhã

### Git
```bash
git status
git add app/agents/atendimento.py app/agents/retencao.py app/agents/dietbox_worker.py app/router.py tests/test_behavior.py tests/test_router.py tests/test_integration.py tests/test_dietbox_worker.py PROXIMOPASSO.md
git commit -m "refina interpretacao conversacional e corrige integracao dietbox"
```

### Subir ambiente
```bash
docker compose up -d
docker compose ps
```

### Rodar testes principais
```bash
docker run --rm -v /root/agente:/workspace -w /workspace agente-app python -m pytest -q tests/test_behavior.py tests/test_router.py tests/test_integration.py tests/test_state_manager.py tests/test_dietbox_worker.py
```

### Como iniciar o Codex
```bash
cd /root/agente
codex --full-auto
```

### Como retomar o contexto corretamente
- Ler primeiro este arquivo.
- Depois ler:
  - `app/agents/atendimento.py`
  - `app/agents/retencao.py`
  - `app/router.py`
  - `app/agents/dietbox_worker.py`
- Depois rodar:
  - `git diff --stat`
  - a suíte de testes acima
- Só então começar novas mudanças.

## 6. 💬 Prompt sugerido para recomeçar amanhã

```text
Continuar o projeto Agente Ana a partir do estado atual do repositório.

Leia primeiro:
- PROXIMOPASSO.md
- app/agents/atendimento.py
- app/agents/retencao.py
- app/router.py
- app/agents/dietbox_worker.py

Contexto:
- já foi implementada uma camada de interpretação contextual nas etapas críticas do atendimento
- remarcação agora conclui no mesmo turno
- cancelamento agora tenta cancelar no Dietbox
- atendimento não confirma mais consulta quando o Dietbox falha

Objetivo de hoje:
1. alinhar o financeiro com a regra de sinal de 50%
2. confirmar pagamento no Dietbox após comprovante
3. melhorar handoff retencao -> atendimento
4. manter ou ampliar cobertura de testes

Regras:
- não quebrar o fluxo conversacional atual
- preservar serialização dos agentes
- validar com testes dentro do container
- mostrar diff e explicar impacto real no fluxo
```

## 7. ⚠️ Cuidados importantes

- Não remover o fluxo estruturado inteiro de uma vez.
- Não transformar tudo em resposta livre do LLM sem controle de estado.
- Não mexer em `router` sem revisar impacto em interrupção, inline e persistência.
- Não assumir payload do Dietbox sem cobrir com teste.
- Não usar o container `app` como única fonte de verdade para testes de arquivo local:
  ele pode não refletir os testes mais recentes se o código não estiver montado.
- Preferir validar com:
  `docker run --rm -v /root/agente:/workspace -w /workspace agente-app python -m pytest ...`
- Antes de qualquer refatoração grande, confirmar manualmente o comportamento no `/test/chat`.
