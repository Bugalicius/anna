# ROTEIRO DE TESTES — Agente Ana

> 25 cenarios completos de conversa para teste via `/test/chat`
> Objetivo: cobrir situacoes atipicas, de borda, e fluxos nunca testados em producao.
> Cada cenario tem: contexto, script de mensagens, e resultado esperado.

---

## COMO EXECUTAR

Usar o endpoint `POST /test/chat` ou a interface HTML em `GET /test/chat`.
Antes de cada cenario, chamar `POST /test/reset` para limpar o estado.

```
POST /test/reset  {"phone": "5531900001001"}
POST /test/chat   {"phone": "5531900001001", "message": "..."}
```

---

## CATEGORIA 1: TROCA BRUSCA DE OBJETIVO / CORRECAO MID-FLOW

### TESTE 01 — Paciente troca de plano no meio do agendamento

**Contexto:** Paciente ja escolheu plano "unica", ja recusou upsell, ja escolheu modalidade, e agora quer trocar para "ouro".

**Script:**
```
1. Paciente: "Oi, meu nome e Maria Silva"
2. Paciente: "Sou nova"
3. Paciente: "Quero emagrecer"
   -> Ana envia PDF de planos
4. Paciente: "Quero o plano unica"
   -> Ana oferece upsell (unica -> ouro)
5. Paciente: "Nao, quero unica mesmo"
   -> Ana pergunta modalidade
6. Paciente: "Presencial"
   -> Ana pergunta preferencia de horario
7. Paciente: "Na verdade, quero trocar o plano. Quero o ouro."
```

**Esperado:**
- Interpreter detecta `correcao: {campo: "plano", valor_novo: "ouro"}`
- State atualiza plano para "ouro"
- Como upsell ja foi oferecido, nao oferece de novo
- Ana confirma a troca e continua perguntando preferencia de horario

---

### TESTE 02 — Paciente troca modalidade apos escolher slot

**Contexto:** Paciente ja tem slot presencial escolhido, mas quer mudar para online.

**Script:**
```
1-6. (mesmo setup do Teste 01 ate escolher horario)
7. Paciente: "Prefiro de manha"
   -> Ana consulta slots e oferece 3 opcoes presenciais
8. Paciente: "1"
   -> Ana pergunta forma de pagamento
9. Paciente: "Na verdade quero online, nao presencial"
```

**Esperado:**
- Interpreter detecta `correcao: {campo: "modalidade", valor_novo: "online"}`
- State limpa slot_escolhido (slots presenciais nao servem mais)
- State limpa last_slots_offered
- Ana confirma troca e consulta novos slots online

---

### TESTE 03 — Paciente troca forma de pagamento (cartao -> pix)

**Contexto:** Paciente escolheu cartao, link foi gerado, mas agora quer PIX.

**Script:**
```
1-8. (setup completo ate forma de pagamento)
9. Paciente: "Cartao"
   -> Ana gera link de pagamento
10. Paciente: "Mudei de ideia, quero pagar por PIX"
```

**Esperado:**
- Override Regra 6 detecta `forma_pagamento=pix` em contexto de pagamento
- Ana envia chave PIX e instrucoes
- State atualiza forma_pagamento para "pix"

---

## CATEGORIA 2: DIFICULDADE COM DATAS E HORARIOS

### TESTE 04 — Paciente nao gosta de nenhum dos 3 slots

**Contexto:** Ana ofereceu 3 slots e o paciente quer outros.

**Script:**
```
1-6. (setup ate preferencia de horario)
7. Paciente: "Prefiro quarta de manha"
   -> Ana oferece 3 slots
8. Paciente: "Nenhum desses serve pra mim, tem outro?"
```

**Esperado:**
- Planner consulta novos slots (rodada_negociacao incrementa)
- Ana oferece 3 novos slots diferentes dos anteriores
- Se nao houver mais slots, Ana informa que nao tem outros horarios disponiveis

---

### TESTE 05 — Paciente responde preferencia de horario de forma vaga

**Contexto:** Paciente nao da preferencia clara.

**Script:**
```
1-6. (setup ate pergunta de horario)
7. Paciente: "Qualquer um, tanto faz"
```

**Esperado:**
- Interpreter extrai `preferencia_horario: {tipo: "qualquer"}`
- Planner consulta slots sem filtro especifico
- Ana oferece 3 slots diversificados (um por dia, turnos variados)

---

### TESTE 06 — Paciente pede horario que nao existe (sabado, domingo)

**Script:**
```
1-6. (setup ate pergunta de horario)
7. Paciente: "Sabado de manha"
```

**Esperado:**
- Interpreter extrai preferencia mas dia_semana=5 ou 6 (fim de semana)
- Slots retornam vazio (nao atende fim de semana)
- Ana informa que so atende segunda a sexta e pede nova preferencia

---

### TESTE 07 — Paciente da horario fora do range (6h da manha, 22h)

**Script:**
```
1-6. (setup ate pergunta de horario)
7. Paciente: "As 6 da manha"
```

**Esperado:**
- Preferencia registrada mas nenhum slot casa (range e 8h-19h)
- Ana informa horarios disponiveis e pede nova preferencia

---

## CATEGORIA 3: DESISTENCIA E RETOMADA

### TESTE 08 — Paciente diz "desistir" na primeira mensagem

**Script:**
```
1. Paciente: "Desisto, nao quero mais"
```

**Esperado:**
- Interpreter classifica intent=cancelar
- Override cancelamento detecta: sem consulta agendada
- Action = abandon_process
- Ana responde graciosamente: "Tudo bem, sem problemas! Se mudar de ideia..."
- Status = concluido

---

### TESTE 09 — Paciente desiste e depois volta querendo agendar

**Script:**
```
1. Paciente: "Oi, quero marcar consulta"
2. Paciente: "Maria Costa"
3. Paciente: "Sou nova"
4. Paciente: "Deixa pra la, nao quero mais"
   -> Ana: "Tudo bem, sem problemas..."
5. Paciente: "Oi"
```

**Esperado:**
- Msg 5: _SAUDACAO detectada + goal=cancelar + intent!=cancelar
- State reseta goal para "desconhecido"
- Ana recomeça fluxo de boas-vindas normalmente
- Dados anteriores (nome "Maria Costa") preservados no state

---

### TESTE 10 — Paciente diz "nao quero mais" no meio do pagamento

**Contexto:** Slot ja escolhido, forma pagamento definida (PIX), aguardando comprovante.

**Script:**
```
1-9. (setup completo ate await_payment com PIX)
10. Paciente: "Desisto, nao quero mais"
```

**Esperado:**
- Intent=cancelar, mas sem id_agenda (consulta nao foi agendada ainda)
- Override cancelamento: abandon_process (cenario A — sem consulta)
- Ana encerra graciosamente, status=concluido

---

## CATEGORIA 4: ESCALACAO PARA BRENO (RELAY COMPLETO)

### TESTE 11 — Duvida clinica de lead (fluxo D-06 completo)

**Contexto:** Paciente nao e cadastrado, faz pergunta clinica. Ana escala para Breno, Breno responde, resposta e retransmitida.

**Script:**
```
1. Paciente: "Oi, sou a Julia Mendes, sou nova"
2. Paciente: "Tenho refluxo gastrico, a nutricionista pode me ajudar com isso?"
```

**Esperado:**
- Interpreter: intent=duvida_clinica, tem_pergunta=true
- Planner: action=escalate
- Router: _handle_escalation()
- Escalation cria PendingEscalation no DB
- Envia contexto para Breno (5531992059211) com historico resumido
- Paciente recebe: "Vou verificar com a Thaynara..."
- **PROXIMO PASSO (simular resposta do Breno):**

```
3. [Breno responde no 31992059211]: "Sim, a Thaynara atende pacientes com refluxo"
```

**Esperado:**
- Relay detecta PendingEscalation pendente
- Resposta retransmitida para Julia
- PendingEscalation marcada como respondida
- Resposta salva como FAQ aprendido (se aplicavel)

---

### TESTE 12 — Pergunta fora de escopo que precisa de humano (D-07)

**Script:**
```
1. Paciente: "Oi, sou o Carlos, sou novo"
2. Paciente: "Voces aceitam convenio medico?"
```

**Esperado:**
- Interpreter: intent=tirar_duvida, topico_pergunta=null (nao cai em pagamento/planos/modalidade/politica)
- Se o LLM nao souber responder: action=escalate ou respond_fora_de_contexto
- Ana redireciona ou responde que nao tem essa informacao

---

## CATEGORIA 5: MENSAGENS ATIPICAS / FORMATOS INESPERADOS

### TESTE 13 — Paciente manda audio no meio do pagamento

**Contexto:** Status=aguardando_pagamento, paciente envia audio ao inves de comprovante.

**Script:**
```
1-9. (setup completo ate await_payment)
10. Paciente: "[audio transcrito: 'oi tudo bem eu ja paguei o pix viu']"
```

**Esperado:**
- Interpreter detecta confirmou_pagamento=true (disse "ja paguei")
- Mas valor_comprovante=null (audio nao tem valor)
- Planner pede comprovante/confirmacao do valor
- Ana: "Recebi, mas nao consegui identificar o valor. Pode enviar o comprovante em imagem?"

---

### TESTE 14 — Paciente manda emoji/sticker como resposta

**Script:**
```
1. Paciente: "Oi, Maria Santos, sou nova"
2. Paciente: "Emagrecer"
   -> Ana envia planos
3. Paciente: "👍"
```

**Esperado:**
- Interpreter: intent provavelmente fora_de_contexto ou agendar
- Nenhum plano extraido
- Planner: ask_field plano (continua perguntando qual plano)
- Ana nao trava, pede escolha de plano normalmente

---

### TESTE 15 — Paciente manda mensagem gigante (>500 chars) com multiplas informacoes

**Script:**
```
1. Paciente: "Oi meu nome e Ana Paula Ferreira da Silva, sou paciente nova, meu objetivo e emagrecer porque tenho lipedema e preciso perder peso urgente. Quero o plano ouro, modalidade presencial, de preferencia quarta ou quinta de manha. Meu email e anapaula@gmail.com, nasci em 15/03/1990, moro no CEP 33400-000, meu instagram e @anapaula e fui indicada pela minha amiga Carla."
```

**Esperado:**
- Interpreter extrai TODOS os campos de uma vez: nome, status_paciente, objetivo, plano, modalidade, preferencia_horario, email, data_nascimento, cep_endereco, instagram, indicacao_origem
- Planner avanca para o ponto mais adiantado possivel (send_planos ou offer_upsell)
- Nenhum campo perdido, fluxo acelerado

---

### TESTE 16 — Paciente responde com numero sem contexto

**Contexto:** Ana perguntou o objetivo, paciente responde "2".

**Script:**
```
1. Paciente: "Oi, Pedro Souza, sou novo"
2. Paciente: "2"
```

**Esperado:**
- Se "2" corresponde a opcao de objetivo (ex: "Ganhar massa" como segunda opcao)
  - Interpreter pode ou nao mapear
- Se nao mapeia: Planner pede objetivo novamente com as opcoes
- Ana nao trava, re-pergunta se necessario

---

## CATEGORIA 6: COMPROVANTE E PAGAMENTO — CENARIOS DE BORDA

### TESTE 17 — Comprovante com valor errado (esperado R$130, recebido R$100)

**Contexto:** Plano unica presencial (R$260, sinal 50% = R$130).

**Script:**
```
1-9. (setup completo, plano=unica, presencial, PIX)
10. Paciente: "[comprovante valor=100.00]"
```

**Esperado:**
- Override Regra 7: valor_recebido=100, valor_esperado=130
- Diferenca > 0.01
- Ana informa: "O valor identificado foi R$100.00 e o sinal e R$130.00. Confere pra mim?"
- Nao avanca para cadastro

---

### TESTE 18 — Paciente insiste em pagar no consultorio

**Script:**
```
1-8. (setup ate forma de pagamento)
9. Paciente: "Posso acertar la na hora?"
```

**Esperado:**
- Override Regra 6a: regex `_PAGAR_CONSULTORIO` detecta "la na hora"
- Ana explica politica: "A politica da clinica exige pagamento antecipado..."
- Nao avanca, continua aguardando escolha PIX ou cartao

---

### TESTE 19 — Paciente tenta enviar comprovante ANTES de escolher forma de pagamento

**Contexto:** Paciente tem slot escolhido mas ainda nao indicou PIX ou cartao.

**Script:**
```
1-7. (setup ate slot escolhido)
8. Ana pergunta forma de pagamento
9. Paciente: "[comprovante valor=130.00]"
```

**Esperado:**
- Interpreter: confirmou_pagamento=true, valor_comprovante=130
- Planner: contexto_pagamento_ativo=true (slot escolhido)
- Se valor bate: avanca, assume PIX como forma_pagamento default
- Fluxo nao trava

---

## CATEGORIA 7: PACIENTE DE RETORNO — CENARIOS ESPECIAIS

### TESTE 20 — Paciente de retorno que nao existe no Dietbox

**Script:**
```
1. Paciente: "Oi, sou a Fernanda Lima"
2. Paciente: "Ja sou paciente, quero remarcar"
```

**Esperado:**
- Interpreter: intent=remarcar, status_paciente=retorno
- Planner: execute_tool detectar_tipo_remarcacao
- Dietbox nao encontra paciente -> tipo_remarcacao=nova_consulta
- State atualiza status_paciente para "novo"
- Ana: "Nao encontrei cadastro no sistema. Vamos agendar como novo paciente?"
- Fluxo continua como novo agendamento

---

### TESTE 21 — Paciente de retorno quer remarcar mas perdeu a janela de 7 dias

**Contexto:** Paciente tem consulta agendada ha mais de 7 dias.

**Script:**
```
1. Paciente: "Oi, Fernanda Lima, sou paciente"
2. Paciente: "Preciso remarcar minha consulta"
```

**Esperado (se janela expirou):**
- detectar_tipo_remarcacao retorna tipo=retorno mas fim_janela ja passou
- Planner informa que janela de remarcacao expirou
- Oferece opcao de agendar como nova consulta (perda_retorno)

---

### TESTE 22 — Paciente de retorno quer cancelar consulta existente (fluxo B completo)

**Script:**
```
1. Paciente: "Oi, Ana Beatriz, ja sou paciente"
2. Paciente: "Quero cancelar minha consulta"
   -> Ana pergunta motivo
3. Paciente: "Vou viajar e nao vou conseguir ir"
   -> Ana executa cancelamento no Dietbox
4. (Sistema confirma cancelamento)
```

**Esperado:**
- Override cancelamento cenario B (tem consulta)
- B1: ask_motivo_cancelamento
- B2: execute_tool cancelar com motivo "vou viajar..."
- B3: send_confirmacao_cancelamento
- Status = concluido

---

## CATEGORIA 8: FLUXOS ALTERNATIVOS

### TESTE 23 — Paciente escolhe plano formulario (fluxo diferente)

**Script:**
```
1. Paciente: "Oi, Lucas Oliveira, sou novo"
2. Paciente: "Quero emagrecer"
   -> Ana envia planos
3. Paciente: "Quero o formulario"
```

**Esperado:**
- plano=formulario
- Nao oferece upsell (formulario nao e elegivel)
- Nao pergunta modalidade (formulario nao tem)
- Ana envia instrucoes de pagamento do formulario (R$100)
- Status = aguardando_pagamento
- Apos comprovante: envia link do Google Forms
- Status = concluido

---

### TESTE 24 — Paciente aceita upsell (unica -> ouro)

**Script:**
```
1. Paciente: "Oi, Mariana Costa, nova"
2. Paciente: "Quero ganhar massa"
   -> Ana envia planos
3. Paciente: "Quero unica"
   -> Ana oferece upsell: "Por apenas R$X a mais voce tem 3 consultas no Ouro..."
4. Paciente: "Sim, quero o ouro!"
```

**Esperado:**
- Interpreter: aceita_upgrade=true
- Planner: atualiza plano de "unica" para "ouro"
- upsell_oferecido=true (nao oferece de novo)
- Ana pergunta modalidade normalmente com plano=ouro
- Valores exibidos sao do plano ouro, nao unica

---

### TESTE 25 — Paciente recusa remarketing

**Contexto:** Paciente recebeu mensagem de remarketing apos dias de silencio.

**Script:**
```
[Estado pre-configurado: goal=desconhecido, contact.stage=remarketing_sequence]
1. Paciente: "Para de me mandar mensagem, nao quero"
```

**Esperado:**
- Router detecta stage=remarketing_sequence, reseta para "new"
- Interpreter: intent=recusou_remarketing
- Planner: action=handle_remarketing_refusal, new_status=concluido
- Ana: mensagem de despedida respeitosa
- Contact.stage -> lead_perdido

---

## CATEGORIA 9: MENSAGENS FORA DE CONTEXTO NO MEIO DO FLUXO

### TESTE 26 — Paciente manda mensagem totalmente aleatoria no meio do fluxo

**Contexto:** Paciente esta no meio do agendamento (ja deu nome, objetivo).

**Script:**
```
1. Paciente: "Oi, Rafael Mendes, novo"
2. Paciente: "Emagrecer"
   -> Ana envia planos
3. Paciente: "Quanto custa o dolar hoje?"
```

**Esperado:**
- Interpreter: intent=fora_de_contexto
- Planner: goal=agendar_consulta (ativo) -> ignora intent fora_de_contexto
- Ana continua o fluxo: pergunta qual plano sem se perder
- NAO responde sobre dolar

---

### TESTE 27 — Paciente faz pergunta sobre planos ANTES de receber o PDF

**Script:**
```
1. Paciente: "Oi, quero saber os precos dos planos"
```

**Esperado:**
- Interpreter: intent=tirar_duvida, topico_pergunta=planos
- Planner: answer_question com contexto de planos OU pede nome primeiro
- Ana nao manda PDF sem coletar nome/objetivo antes
- Responde a duvida e guia para o fluxo

---

### TESTE 28 — Paciente pergunta endereco da clinica no meio do pagamento

**Script:**
```
1-8. (setup completo ate forma de pagamento)
9. Paciente: "PIX"
   -> Ana envia chave PIX
10. Paciente: "Qual o endereco da clinica?"
```

**Esperado:**
- Interpreter: tem_pergunta=true, topico_pergunta=clinica
- Mas status=aguardando_pagamento e slot_escolhido nao e null
- Regra 3 do planner: NAO responde pergunta (prioridade absolutas excluem status=aguardando_pagamento)
- Planner mantem await_payment OU responde pergunta e mantem estado
- Ana responde endereco e lembra de enviar o comprovante

---

## CATEGORIA 10: SEGURANCA E RESTRICOES

### TESTE 29 — Paciente gestante tenta agendar

**Script:**
```
1. Paciente: "Oi, Carolina Santos, sou nova"
2. Paciente: "Estou gravida e quero acompanhamento nutricional"
```

**Esperado:**
- Boas-vindas ja informam restricao de gestantes
- Interpreter pode detectar como duvida_clinica ou agendar
- Ana deve reiterar que Thaynara nao atende gestantes no momento
- Oferecer encaminhamento ou despedida respeitosa

---

### TESTE 30 — Verificar que numero interno NUNCA aparece nas respostas

**Contexto:** Em TODOS os 29 testes acima.

**Verificacao:**
- Nenhuma resposta da Ana contem "99205-9211" ou "992059211" ou "31992059211"
- Numero interno so aparece em logs (ultimos 4 digitos) e na mensagem enviada ao Breno
- Quando paciente precisa falar com Thaynara, recebe 5531991394759 (numero publico)

---

## CATEGORIA 11: STRESS E RESILIENCIA

### TESTE 31 — Multiplas mensagens rapidas (burst)

**Script:**
```
1. Paciente: "Oi"
2. Paciente: "Meu nome e Patricia Alves"
3. Paciente: "Sou nova"
4. Paciente: "Quero emagrecer"
(todas em sequencia rapida, sem esperar resposta)
```

**Esperado:**
- Cada mensagem processada sequencialmente
- Estado acumula: nome, status_paciente, objetivo
- Nenhuma mensagem perdida
- Ao final, Ana deve estar pronta para enviar planos
- Sem duplicacao de respostas

---

### TESTE 32 — Paciente manda mesma mensagem 3 vezes

**Script:**
```
1. Paciente: "Oi quero marcar consulta"
2. Paciente: "Oi quero marcar consulta"
3. Paciente: "Oi quero marcar consulta"
```

**Esperado:**
- Deduplicacao no webhook (meta_message_id) impede reprocessamento
- Se IDs diferentes: cada mensagem processada, mas estado nao regride
- Ana nao repete boas-vindas 3 vezes

---

## RESUMO DE COBERTURA

| # | Cenario | Categoria | Fluxo principal |
|---|---------|-----------|-----------------|
| 01 | Trocar plano mid-flow | Correcao | Agendamento |
| 02 | Trocar modalidade apos slot | Correcao | Agendamento |
| 03 | Trocar pagamento cartao->pix | Correcao | Pagamento |
| 04 | Nenhum slot serve | Horarios | Agendamento |
| 05 | Preferencia vaga "tanto faz" | Horarios | Agendamento |
| 06 | Horario fim de semana | Horarios | Agendamento |
| 07 | Horario fora do range | Horarios | Agendamento |
| 08 | Desistir na 1a mensagem | Desistencia | Cancelamento |
| 09 | Voltar apos desistir | Desistencia | Reset |
| 10 | Desistir no pagamento | Desistencia | Cancelamento |
| 11 | Duvida clinica lead (D-06) | Escalacao | Relay Breno |
| 12 | Pergunta fora de escopo | Escalacao | D-07 |
| 13 | Audio no pagamento | Formato atipico | Pagamento |
| 14 | Emoji como resposta | Formato atipico | Generico |
| 15 | Mensagem gigante multi-info | Formato atipico | Agendamento |
| 16 | Numero sem contexto | Formato atipico | Generico |
| 17 | Comprovante valor errado | Pagamento | Validacao |
| 18 | Pagar no consultorio | Pagamento | Politica |
| 19 | Comprovante antes de escolher forma | Pagamento | Ordem |
| 20 | Retorno nao existe no Dietbox | Retorno | Reclassificacao |
| 21 | Retorno janela expirada | Retorno | Remarcacao |
| 22 | Cancelar consulta existente | Retorno | Cancel B |
| 23 | Plano formulario | Alternativo | Formulario |
| 24 | Aceitar upsell | Alternativo | Upgrade |
| 25 | Recusar remarketing | Alternativo | Lead perdido |
| 26 | Mensagem aleatoria mid-flow | Fora contexto | Resiliencia |
| 27 | Pergunta preco sem nome | Fora contexto | Pre-fluxo |
| 28 | Pergunta endereco no pagamento | Fora contexto | Mid-flow |
| 29 | Gestante tenta agendar | Restricao | Seguranca |
| 30 | Numero interno nunca exposto | Seguranca | Todos |
| 31 | Mensagens em rajada | Stress | Resiliencia |
| 32 | Mensagem duplicada | Stress | Deduplicacao |

---

## PRIORIDADE DE EXECUCAO

**Criticos (testar primeiro):**
- T08, T09, T10 — Desistencia/retomada (bugs comuns)
- T11 — Relay Breno (fluxo nunca testado end-to-end)
- T17, T18, T19 — Pagamento edge cases
- T01, T02 — Correcoes mid-flow

**Importantes:**
- T04, T05, T06, T07 — Horarios atipicos
- T20, T21, T22 — Retorno
- T23, T24, T25 — Fluxos alternativos
- T26, T27, T28 — Fora de contexto

**Complementares:**
- T13, T14, T15, T16 — Formatos atipicos
- T29, T30, T31, T32 — Seguranca e stress
