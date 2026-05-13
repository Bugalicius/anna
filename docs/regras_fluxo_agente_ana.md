# Regras do fluxo - Agente Ana

Este documento consolida as regras de atendimento, agendamento, pagamento e cadastro do agente Ana. Ele deve ser tratado como fonte revisavel do fluxo antes de novas alteracoes.

## Principios

- A Ana deve conversar com o paciente e conduzir o fluxo, nao apenas repetir menus.
- Quando a mensagem for clara, regras deterministicas vencem a LLM.
- Quando a mensagem for ambigua e o fluxo nao souber seguir com seguranca, a Ana deve pedir uma informacao objetiva ou escalar para Breno.
- A LLM nao deve decidir valores, regras de agenda, regras de pagamento ou regras clinicas sem validacao deterministica.
- A LLM pode ajudar a interpretar linguagem natural, mas a resposta final deve respeitar o estado e as regras do fluxo.

## Identificacao inicial

- Se nao houver nome completo salvo, pedir nome e sobrenome.
- Se houver nome completo salvo em contato antigo, usar esse nome apenas quando o contato nao foi zerado.
- Para teste, limpar Redis e contato no banco antes de simular conversa nova.
- Depois do nome, perguntar se e primeira consulta ou se ja e paciente.

## Objetivo

- Perguntar objetivo antes de planos.
- Objetivos validos:
  - emagrecer
  - ganhar massa
  - lipedema
  - outro
- Rotulos de plano nao podem contaminar objetivo:
  - consulta individual
  - consulta unica
  - consulta com retorno
  - plano ouro
  - plano premium

## Planos

- Depois de objetivo, enviar midia kit e lista de planos.
- Planos validos:
  - premium
  - ouro
  - com_retorno
  - unica
  - formulario
- Se paciente escolher plano, salvar exatamente o plano escolhido.
- Se paciente aceitar upsell por botao, salvar o plano de destino do botao.
- Nunca aplicar upsell duas vezes no mesmo clique.
  - `upgrade_ouro` salva `ouro`, nao pode virar `premium`.
  - `upgrade_premium` salva `premium`.
- Se paciente recusar upsell, manter plano atual e seguir para modalidade.

## Upsell

- `unica` pode receber upsell para `ouro`.
- `com_retorno` pode receber upsell para `ouro`.
- `ouro` pode receber upsell para `premium`.
- Botao de manter plano deve deixar claro que mantem a escolha atual.
- Botao de upgrade deve deixar claro que e upgrade.

## Modalidade

- Modalidades validas:
  - presencial
  - online
- Depois da modalidade, perguntar preferencia de horario em texto livre.
- Nao usar botoes fixos de turno nessa etapa.

## Horarios de atendimento

- Atendimento de segunda a sexta.
- Horarios gerais:
  - Manha: 08h, 09h, 10h
  - Tarde: 15h, 16h, 17h
  - Noite: 18h, 19h
- Sexta-feira nao tem atendimento a noite.
- Nao oferecer horario fora da grade.
- Se paciente pedir horario fora da grade, explicar e pedir outra opcao.
- Se paciente pedir sexta a noite, responder que sexta nao tem atendimento a noite e oferecer os horarios validos de sexta.
- Nunca oferecer consulta no mesmo dia do atendimento/teste.

## Interpretacao de preferencia de horario

- O agente deve interpretar qualquer combinacao de:
  - dia da semana
  - turno
  - hora especifica
- Exemplos:
  - segunda as 08h
  - terca as 15h
  - quarta de manha
  - quinta a tarde
  - sexta as 17h
  - sexta a noite
- A interpretacao deve validar se o pedido e atendido pela grade antes de buscar slots.

## Oferta de slots

- Se o paciente pedir dia e horario especificos, buscar ate 90 dias.
- Se encontrar o horario solicitado:
  - enviar o primeiro slot exato encontrado, mesmo que distante;
  - completar com dois horarios mais proximos do mesmo turno;
  - mensagem: "Encontrei o horario solicitado e estou enviando dois outros horarios mais proximos caso o solicitado esteja distante:"
- Se nao encontrar o horario solicitado:
  - enviar opcoes do mesmo turno;
  - completar com o proximo horario disponivel se faltar opcao.
- Se paciente rejeitar os slots e pedir outro dia/turno/hora, limpar slots anteriores e reconsultar.
- Se nao souber interpretar a rejeicao, perguntar objetivamente qual dia, turno ou horario atende.

## Regras de distribuicao de slots

- Nunca oferecer tres consultas seguidas no mesmo dia.
- Nao oferecer horarios consecutivos ou muito proximos no mesmo dia.
- Se houver mais de um slot no mesmo dia:
  - no maximo 2 slots por dia;
  - devem estar em turnos diferentes.
- Preferir diversidade de dias quando nao houver pedido especifico.
- Nao oferecer slots ja rejeitados na mesma rodada, salvo se for o unico horario exato pedido pelo paciente.

## Escolha de slot

- Aceitar clique de botao/lista (`slot_1`, `slot_2`, `slot_3`).
- Aceitar texto equivalente ao botao, por exemplo "sexta 08/05 10h".
- Depois de slot escolhido, perguntar forma de pagamento.

## Pagamento

- O agendamento so e confirmado apos pagamento antecipado.
- Para PIX, informar chave e valor do sinal de 50%.
- Se comprovante tiver valor menor que o sinal, avisar divergencia e pedir comprovante correto.
- Se comprovante tiver valor igual ao sinal, seguir cadastro.
- Se comprovante tiver valor maior que o sinal:
  - registrar valor pago;
  - calcular saldo restante pelo valor total PIX do plano/modalidade;
  - informar quanto fica para acertar no dia da consulta.
- Se comprovante quitar o valor total, informar que ficou quitado.

## Cadastro obrigatorio

- Campos obrigatorios:
  - nome completo
  - data de nascimento
  - WhatsApp de contato
  - e-mail
- Campos opcionais:
  - Instagram
  - profissao
  - CEP/endereco
  - indicacao/origem
- A Ana deve insistir campo a campo ate coletar obrigatorios.
- Se paciente mandar so o nome apos o pedido de cadastro, pedir data de nascimento.
- Se mandar data, pedir WhatsApp.
- Se mandar WhatsApp, pedir e-mail.
- So executar agendamento no Dietbox quando os obrigatorios estiverem validos.

## Remarcacao

- Se paciente pedir remarcacao, localizar consulta ativa.
- Se for retorno dentro da janela, oferecer remarcacao dentro do prazo.
- Se nao houver consulta ou o paciente disser que quer nova consulta, mudar para novo agendamento.
- Se paciente antigo disser "quero marcar nova consulta" ou "nao e remarcacao", limpar consulta atual e seguir fluxo de agendamento.

## Cancelamento

- Se houver consulta ativa, pedir motivo e seguir cancelamento.
- Se nao houver consulta ativa, explicar que nao encontrou consulta e pedir identificacao.
- Se paciente desistir sem consulta ativa, encerrar com mensagem cordial.

## Duvidas clinicas e restricoes

- Duvida clinica deve escalar para Breno.
- Gestante ou menor de 16 anos sem duvida clinica recebe recusa de atendimento.
- Gestante com pergunta clinica, exemplo diabetes/dieta/medicamento, deve escalar.

## Falhas e fallback

- Se uma regra deterministica nao encontrar proxima acao, nao repetir o mesmo menu indefinidamente.
- Se a Ana repetiu a mesma pergunta apos resposta clara do paciente, isso e bug de fluxo.
- Fallback correto:
  - tentar interpretar dia/turno/hora/plano/pagamento;
  - pedir uma informacao objetiva;
  - se ainda nao houver seguranca, escalar para Breno.

## Mudanca arquitetural recomendada

- Separar o sistema em tres camadas:
  - interpretador: transforma mensagem em dados estruturados;
  - state machine deterministica: decide a proxima etapa;
  - gerador de texto: escreve a mensagem final com base na decisao.
- A LLM nao deve controlar o fluxo principal diretamente.
- Toda transicao critica precisa ter contrato e teste:
  - plano escolhido
  - upsell aceito/recusado
  - modalidade
  - preferencia de horario
  - slots
  - pagamento
  - cadastro
  - agendamento
- Criar uma bateria E2E com conversas reais antes de deploy.
- Registrar em log a decisao estruturada por turno:
  - turno extraido
  - estado antes/depois
  - regra aplicada
  - resposta enviada
