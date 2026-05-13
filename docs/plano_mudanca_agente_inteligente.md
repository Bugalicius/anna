# Plano de mudanca para um agente inteligente

Documento para discussao tecnica sobre a evolucao da Ana, agente de atendimento da nutricionista Thaynara Teixeira.

Data: 2026-05-05

## 1. Contexto

A Ana ja tem um fluxo praticamente pronto:

- identifica paciente novo, retorno ou paciente antigo;
- coleta nome, objetivo, plano, modalidade e preferencia de horario;
- envia midia kit;
- oferece upsell quando faz sentido;
- consulta horarios reais;
- conduz pagamento via PIX ou cartao;
- coleta comprovante;
- coleta cadastro obrigatorio;
- lida com remarcacao, cancelamento, duvidas de plano, gestante, audio e duvidas clinicas;
- deve escalar para Breno quando nao souber responder com seguranca.

O problema atual nao e falta de fluxo. O problema e confiabilidade na execucao do fluxo.

O comportamento observado parece mais um chatbot com regras soltas do que um agente inteligente. Em varios momentos ele responde como se nao revisasse o estado da conversa, nao validasse a ultima mensagem do paciente e nao checasse se a resposta final esta coerente antes de enviar.

## 2. Bugs e sintomas observados

### 2.1 Upgrade Ouro virou Premium

Historico testado no numero `31 8321-9192`:

1. Paciente escolheu `Consulta com retorno`.
2. Bot ofereceu upgrade para `Plano Ouro`.
3. Paciente aceitou `upgrade_ouro`.
4. Bot seguiu para modalidade.
5. Paciente escolheu online.
6. Paciente pediu sexta as 17h.
7. Bot ofereceu horarios.
8. Paciente escolheu `slot_1`.
9. Bot cobrou valor de `Plano Premium`, mesmo o paciente tendo escolhido `Plano Ouro`.

Root cause encontrado:

- o interpretador ja convertia `upgrade_ouro` para `plano=ouro`;
- depois o planner aplicava a regra de upgrade de novo;
- na pratica: `com_retorno -> ouro -> premium`.

Correcao aplicada:

- quando o botao de upgrade ja chega como plano de destino (`ouro` ou `premium`), o planner nao aplica upgrade novamente.

### 2.2 Horarios seguidos no mesmo dia

Historico observado:

- paciente pediu `sexta as 17h`;
- bot ofereceu `sexta 17h`, `sexta 15h`, `sexta 16h`;
- isso gera tres consultas no mesmo dia, no mesmo turno, praticamente seguidas.

Regra correta:

- nunca oferecer 3 consultas no mesmo dia;
- nunca oferecer consultas seguidas no mesmo dia;
- se houver mais de uma opcao no mesmo dia, devem ser em turnos diferentes;
- no maximo 2 turnos por dia;
- nunca oferecer horario no mesmo dia do atendimento/teste;
- priorizar diversidade de dias e horarios.

Correcao aplicada:

- filtro de distribuicao de slots:
  - bloqueia horarios duplicados;
  - bloqueia mais de 2 slots no mesmo dia;
  - bloqueia dois slots do mesmo turno no mesmo dia;
  - bloqueia slots muito proximos no mesmo dia;
  - bloqueia horario no mesmo dia atual.

### 2.3 Preferencia de horario precisa ser interpretada, nao apenas botao

Exemplos reais:

- `segunda as 08h`;
- `sexta a noite`;
- `tem que ser segunda as 08h`;
- `nao consigo nesses horarios, nao tem nenhum na segunda-feira?`;
- `terça de manha`;
- `qualquer horario de tarde`.

Comportamento desejado:

- interpretar dia, hora e turno;
- validar se a Thaynara atende naquele dia e horario;
- se for invalido, explicar de forma humana e pedir outra preferencia;
- se for valido, buscar a primeira data disponivel que respeite exatamente o pedido, mesmo que distante;
- junto com o horario pedido, oferecer mais duas opcoes proximas do mesmo turno quando fizer sentido;
- se a preferencia for impossivel dentro da agenda/horario de atendimento, conversar e renegociar.

Mensagem desejada quando encontra a preferencia exata:

> Encontrei o horario solicitado e estou enviando dois outros horarios mais proximos caso o solicitado esteja distante.

### 2.4 Sexta a noite

Regra da clinica:

- segunda a sexta:
  - manha: 08h, 09h, 10h;
  - tarde: 15h, 16h, 17h;
  - noite: 18h, 19h;
- exceto sexta a noite.

Comportamento desejado:

- se paciente pedir `sexta a noite`, o bot nao deve repetir a pergunta de turno;
- deve explicar que sexta a noite esta fora dos horarios de atendimento;
- deve sugerir sexta de tarde ou noite de segunda a quinta;
- deve manter conversa natural e voltar ao fluxo.

### 2.5 Pagamento com valor maior

Caso observado:

- bot pediu sinal de 50%;
- paciente enviou comprovante com valor maior;
- bot nao conferiu corretamente o saldo.

Comportamento desejado:

- validar valor recebido contra valor total e valor do sinal;
- se pagou mais que o sinal e menos que o total, informar quanto fica para acertar no dia;
- se pagou o total, informar que nao ha saldo;
- se pagou menos que o sinal, pedir complemento;
- se nao conseguir ler/confirmar comprovante, escalar para Breno.

### 2.6 Cadastro incompleto

Campos obrigatorios:

- nome completo;
- data de nascimento;
- WhatsApp para contato;
- email.

Campos importantes, mas podem ser complementares:

- Instagram;
- profissao;
- CPF e endereco completo;
- indicacao/origem.

Problema observado:

- paciente respondeu apenas `Ana teste`;
- bot parou ou nao insistiu nos campos obrigatorios.

Comportamento desejado:

- detectar quais obrigatorios faltam;
- pedir somente os faltantes;
- insistir de forma educada;
- nao finalizar nem confirmar cadastro incompleto;
- se paciente foge do assunto, responder e voltar para os campos pendentes.

### 2.7 Fallback e escalamento

Problema observado:

- em algumas mensagens fora do caminho esperado, o bot nao responde ou repete mensagem mecanicamente.

Regra desejada:

- o bot sempre deve produzir uma resposta util;
- se nao sabe interpretar, deve fazer uma pergunta curta de esclarecimento;
- se envolve risco clinico, gestante, conduta nutricional, reclamacao sensivel, pagamento duvidoso ou falha de ferramenta, deve escalar para Breno;
- se escalar, deve avisar o paciente de forma natural.

## 3. Diagnostico arquitetural

O problema central nao e um bug isolado. E a distribuicao errada de responsabilidade entre LLM, planner, regras e estado.

Hoje a LLM participa demais de decisoes criticas:

- interpreta intencao;
- influencia o proximo passo;
- pode mudar campos do estado;
- pode repetir mensagens de fluxo;
- pode nao considerar regras de negocio antes da resposta final.

Isso cria fragilidade:

- uma mensagem inesperada pode derrubar o fluxo;
- uma interpretacao parcial pode sobrescrever estado correto;
- botoes podem ser interpretados como texto livre;
- o bot pode cobrar valor errado;
- o bot pode oferecer horario errado;
- o bot pode parar quando nao encontra acao clara.

Para um agente confiavel, a LLM deve ser inteligente na linguagem, mas nao deve ser a fonte de verdade das regras criticas.

## 4. Principio da nova arquitetura

A Ana deve ser uma agente com guardrails deterministicas.

Modelo recomendado:

1. A LLM interpreta a mensagem do paciente.
2. O sistema valida a interpretacao.
3. Uma maquina de estados decide o proximo passo.
4. Ferramentas consultam dados reais quando necessario.
5. Um motor de regras valida plano, horario, pagamento, cadastro e escalamento.
6. A LLM redige a resposta final somente dentro da acao autorizada.
7. Um validador final checa se a resposta esta coerente antes de enviar.

Resumo:

- LLM entende e conversa.
- Estado decide onde estamos.
- Regras decidem o que pode acontecer.
- Ferramentas trazem dados reais.
- Validador impede resposta errada.

## 5. Pipeline proposto por mensagem

### Etapa 1: carregar contexto

Entrada:

- numero do paciente;
- estado atual;
- historico recente;
- ultima mensagem do paciente;
- ultima acao enviada;
- botoes/listas ativos;
- dados ja coletados;
- pendencias obrigatorias;
- regras de negocio aplicaveis.

Saida:

- contexto consolidado para decisao.

### Etapa 2: interpretar mensagem

A LLM deve retornar apenas JSON estruturado.

Exemplo:

```json
{
  "intent": "informar_preferencia_horario",
  "confidence": 0.94,
  "entities": {
    "dia_semana": "sexta",
    "turno": "noite",
    "hora": null
  },
  "patient_message_type": "free_text",
  "needs_escalation": false,
  "reason": "Paciente informou preferencia de horario fora dos botoes."
}
```

Regras:

- a LLM nao decide valor;
- a LLM nao decide plano final sozinha;
- a LLM nao escolhe slot;
- a LLM nao confirma pagamento;
- a LLM nao finaliza cadastro sem validacao;
- a LLM apenas extrai e classifica.

### Etapa 3: normalizar e validar entidades

Exemplos:

- `sexta a noite` vira `dia_semana=sexta`, `turno=noite`;
- validar que sexta a noite e invalido;
- `upgrade_ouro` vira `plano_destino=ouro`;
- `slot_1` so e aceito se existirem slots ativos;
- comprovante precisa passar por OCR/leitura/validacao ou escalar.

### Etapa 4: maquina de estados

Estados principais sugeridos:

- `inicio`;
- `coletando_nome`;
- `identificando_status_paciente`;
- `coletando_objetivo`;
- `apresentando_planos`;
- `aguardando_plano`;
- `oferecendo_upsell`;
- `aguardando_upsell`;
- `aguardando_modalidade`;
- `aguardando_preferencia_horario`;
- `oferecendo_slots`;
- `aguardando_escolha_slot`;
- `aguardando_forma_pagamento`;
- `aguardando_pagamento_pix`;
- `aguardando_pagamento_cartao`;
- `validando_pagamento`;
- `coletando_cadastro`;
- `confirmacao_final`;
- `remarcacao_identificacao`;
- `remarcacao_busca_consulta`;
- `remarcacao_preferencia`;
- `cancelamento_motivo`;
- `escalado_breno`;
- `fallback_clarificacao`.

Cada estado deve ter:

- quais intents aceita;
- quais campos pode alterar;
- qual proxima acao pode gerar;
- quais ferramentas pode chamar;
- quais erros escalam;
- quais mensagens sao proibidas.

### Etapa 5: executar ferramentas

Ferramentas devem ser chamadas apenas por acao autorizada:

- buscar paciente;
- consultar agenda;
- buscar slots;
- criar link de pagamento;
- validar comprovante;
- criar/atualizar paciente;
- criar agendamento;
- enviar notificacao para Breno.

### Etapa 6: validar regra de negocio

Antes da resposta:

- plano e valor batem?
- modalidade bate?
- slot pertence aos slots oferecidos?
- slot respeita horario da clinica?
- slot nao e hoje?
- slots nao estao seguidos?
- cadastro obrigatorio esta completo?
- comprovante cobre sinal?
- caso clinico precisa escalar?
- mensagem nao esta repetindo a ultima de forma burra?

### Etapa 7: gerar resposta

A LLM pode gerar texto natural, mas recebe uma acao fechada.

Exemplo:

```json
{
  "action": "informar_horario_invalido",
  "reason": "sexta_noite_fora_do_atendimento",
  "allowed_content": {
    "explain": true,
    "ask_new_preference": true,
    "suggestions": ["sexta a tarde", "segunda a quinta a noite"]
  }
}
```

A LLM nao escolhe outra acao.

### Etapa 8: validador final

O sistema revisa a resposta gerada:

- contem valor errado?
- cita plano errado?
- pede campo ja respondido?
- deixa de pedir campo obrigatorio pendente?
- oferece horario invalido?
- repete a mesma mensagem apos o paciente corrigir?
- deveria escalar?

Se falhar:

- regenera com instrucao objetiva;
- ou usa template deterministico;
- ou escala para Breno.

## 6. Contrato de inteligencia desejado

A Ana deve ser inteligente para:

- entender linguagem natural;
- interpretar respostas incompletas;
- lidar com paciente que responde fora dos botoes;
- corrigir rota quando o fluxo nao encaixa;
- lembrar o que ja foi perguntado;
- nao repetir pergunta sem motivo;
- pedir esclarecimento quando faltar informacao;
- escalar quando ultrapassar conhecimento ou permissao;
- conversar com naturalidade.

A Ana nao deve improvisar em:

- valores;
- plano contratado;
- horarios permitidos;
- slots disponiveis;
- confirmacao de pagamento;
- cadastro obrigatorio;
- regras de remarcacao;
- orientacao clinica;
- excecoes sensiveis.

## 7. Regras criticas que devem sair do prompt e virar codigo

### Planos e valores

- Plano escolhido deve ser fonte de verdade.
- Upsell aceito deve mapear uma unica vez para o plano de destino.
- Valor deve ser calculado por tabela, nao por texto da LLM.
- Texto final deve ser validado contra plano, modalidade e forma de pagamento.

### Horarios

- Horarios permitidos:
  - segunda a sexta;
  - manha: 08h, 09h, 10h;
  - tarde: 15h, 16h, 17h;
  - noite: 18h, 19h;
  - sexta a noite proibido.
- Nunca oferecer slot hoje.
- Se paciente pedir dia/hora especificos, buscar a primeira data disponivel, mesmo distante.
- Oferecer o horario solicitado e mais duas alternativas relevantes.
- Nunca oferecer 3 horarios no mesmo dia.
- Nunca oferecer horarios seguidos no mesmo dia.
- Se oferecer 2 no mesmo dia, devem ser de turnos diferentes.
- Maximo 2 turnos por dia.

### Pagamento

- PIX exige sinal de 50%, salvo regra diferente.
- Se comprovante for maior que sinal:
  - calcular saldo restante;
  - se quitou total, informar que nao fica saldo.
- Se comprovante for menor que sinal:
  - pedir complemento.
- Se leitura duvidosa:
  - escalar para Breno.

### Cadastro

- Obrigatorios:
  - nome completo;
  - data de nascimento;
  - WhatsApp;
  - email.
- Nao finalizar cadastro faltando obrigatorio.
- Pedir apenas campos faltantes.
- Se paciente responder parcialmente, atualizar o que veio e pedir o resto.

### Escalamento

Escalar para Breno quando:

- duvida clinica;
- gestante;
- audio que nao foi transcrito com confianca;
- pagamento/comprovante duvidoso;
- paciente irritado;
- cancelamento sensivel;
- ferramenta indisponivel;
- estado inconsistente;
- LLM com baixa confianca;
- mais de 2 tentativas de fallback no mesmo ponto.

## 8. Mudanca tecnica recomendada

### 8.1 Criar um Orchestrator central

Modulo sugerido:

`app/conversation/orchestrator.py`

Responsabilidade:

- receber mensagem;
- carregar estado;
- chamar interpretador;
- chamar state machine;
- executar ferramentas;
- validar regras;
- gerar resposta;
- persistir estado;
- registrar trace.

### 8.2 Criar State Machine declarativa

Modulo sugerido:

`app/conversation/state_machine.py`

Cada estado deve declarar:

- intents aceitas;
- entidades esperadas;
- campos que pode alterar;
- transicoes permitidas;
- acao seguinte;
- fallback local;
- condicao de escalamento.

### 8.3 Criar Rule Engine

Modulo sugerido:

`app/conversation/rules.py`

Funcoes:

- `validate_plan_transition`;
- `validate_payment_amount`;
- `validate_slot_offer`;
- `validate_selected_slot`;
- `validate_required_registration_fields`;
- `should_escalate`;
- `validate_final_response`.

### 8.4 Separar Interpretador de Gerador

Interpretador:

- extrai intencao e entidades;
- retorna JSON;
- nao fala com paciente.

Gerador:

- recebe uma acao autorizada;
- escreve a mensagem final;
- nao altera estado;
- nao inventa regra.

### 8.5 Adicionar Decision Trace

Toda mensagem deve gerar log estruturado:

```json
{
  "phone_hash": "...",
  "state_before": "aguardando_preferencia_horario",
  "user_message": "sexta a noite",
  "interpreted_intent": "informar_preferencia_horario",
  "entities": {
    "dia_semana": "sexta",
    "turno": "noite"
  },
  "rule_checks": [
    {
      "rule": "sexta_noite_proibido",
      "result": "fail"
    }
  ],
  "action": "informar_horario_invalido",
  "state_after": "aguardando_preferencia_horario",
  "escalated": false
}
```

Isso permite auditar o motivo de cada resposta sem adivinhar.

## 9. Plano de implementacao por fases

### Fase 1: estabilizar regras criticas

Objetivo:

- impedir erros graves imediatamente.

Entregas:

- tabela unica de planos e valores;
- regra unica de upsell;
- validador de slots;
- validador de pagamento;
- validador de cadastro obrigatorio;
- fallback com escalamento.

### Fase 2: criar state machine

Objetivo:

- impedir que a LLM mude o fluxo sozinha.

Entregas:

- estados declarados;
- transicoes testadas;
- cada mensagem passa por estado atual;
- botoes/listas validados contra estado.

### Fase 3: separar LLM extractor e response writer

Objetivo:

- manter inteligencia conversacional sem perder controle.

Entregas:

- schema JSON para interpretacao;
- validacao com Pydantic;
- retry se JSON invalido;
- confidence baixa vira clarificacao ou escalamento;
- response writer recebe apenas acao autorizada.

### Fase 4: decision trace e testes E2E

Objetivo:

- descobrir regressao antes do paciente.

Entregas:

- log por turno;
- dump de estado por passo;
- bateria com cenarios completos:
  - paciente novo PIX;
  - upsell aceito + cartao;
  - remarcacao dentro do prazo;
  - paciente retorno que vira novo agendamento;
  - audio/duvida clinica/escalamento;
  - planos/gestante/cancelar/trocar plano;
  - horario especifico;
  - horario invalido;
  - pagamento a maior;
  - cadastro incompleto.

### Fase 5: avaliador automatico

Objetivo:

- medir se a Ana respondeu corretamente.

Entregas:

- testes com assert sobre estado;
- testes com assert sobre resposta;
- avaliador LLM opcional para naturalidade;
- regras deterministicas sempre vencem avaliador LLM.

## 10. Perguntas para discutir com Claude

1. Qual desenho de state machine e mais adequado para esse fluxo: declarativo por tabela, classes por estado ou grafo?
2. Como limitar a LLM a interpretacao e redacao sem deixar ela decidir regra critica?
3. Como modelar `intent + entities + confidence` para linguagem natural em portugues brasileiro?
4. Como validar resposta final antes de enviar ao WhatsApp?
5. Como criar um trace de decisao simples, legivel e barato?
6. Como testar E2E com Redis, `/test/chat` e agenda real/mockada?
7. O que deve ser template fixo e o que pode ser texto gerado pela LLM?
8. Como impedir sobrescrita indevida de estado por interpretacoes parciais?
9. Como tratar mensagens fora de fluxo sem parecer robo?
10. Como implementar escalamento para Breno com contexto completo?

## 11. Decisao tecnica sugerida

Nao vale continuar corrigindo um erro por vez como se fossem casos isolados.

A recomendacao e evoluir para:

- state machine deterministica;
- LLM como interpretador e redator;
- regras criticas em codigo;
- validacao final obrigatoria;
- decision trace por turno;
- bateria E2E como contrato do fluxo.

Isso ainda permite uma Ana inteligente. Na verdade, aumenta a inteligencia percebida, porque o bot passa a:

- entender o paciente;
- lembrar o contexto;
- responder de forma natural;
- nao inventar regra;
- nao cobrar valor errado;
- nao oferecer horario absurdo;
- pedir o que falta;
- escalar quando necessario.

O objetivo nao e tirar a LLM. O objetivo e colocar a LLM no lugar certo.

