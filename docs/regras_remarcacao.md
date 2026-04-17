# Regras e Mensagens — Fluxo de Remarcação (Agente Ana)

> Edite este arquivo e devolva para o Claude implementar as correções.
> Seções marcadas com ⚠️ precisam de validação/correção sua.

---

## 1. Gatilho de entrada

O fluxo de remarcação é iniciado quando o paciente envia mensagens como:
- "quero remarcar"
- "remarcar minha consulta"
- "mudar data / mudar horário / trocar data / trocar horário"

⚠️ **Adicione aqui outras frases que devem acionar o fluxo:**
-
-

---

## 2. Janela de remarcação

⚠️ **Regra atual implementada (está ERRADA — corrija):**
- A busca de slots começa em amanhã ou na segunda-feira da semana seguinte
- Duração da janela: 7 dias a partir de HOJE

⚠️ **Regra CORRETA (conforme sua explicação):**
- A janela deve ser calculada a partir da DATA DA CONSULTA ORIGINAL
  - Ex: consulta era terça → pode remarcar até terça da semana seguinte (7 dias)
- Início da janela: ??? (amanhã? segunda da semana seguinte? livre?)
- Fim da janela: data original + 7 dias

---

## 3. Seleção de horários a oferecer

⚠️ **Regra atual implementada (está ERRADA — corrija):**
- Tenta filtrar por dia/hora preferida pelo paciente
- Se não achar a preferência exata, avisa e mostra qualquer slot disponível na janela
- Sempre tenta manter a preferência de horário (ex: 8h) mesmo quando muda o dia

⚠️ **Regra CORRETA (conforme sua explicação):**
- Opção 1 (se possível): oferecer 1 slot de acordo com a preferência do paciente
- Opções 2 e 3: de acordo com a disponibilidade da agenda (qualquer horário disponível)
- Total: sempre oferecer 3 opções
- Se não houver nenhum slot compatível com a preferência: oferecer as 3 primeiras opções disponíveis na janela
- Se não houver nenhum slot na janela: ??? (escalar para Thaynara?)

---

## 4. Mensagens fixas

### 4.1 Abertura do fluxo (quando recebe "quero remarcar")
```
Tudo bem, {nome}. Podemos remarcar sim, sem problema 😊

Só queria te orientar que no momento a agenda da Thaynara está bem cheia.
Se você conseguir fazer um esforço para manter o horário agendado,
seria ótimo para não prejudicar seu acompanhamento.

Caso realmente não consiga, conseguimos realizar o agendamento dentro dos
próximos 7 dias, que é o prazo máximo para a remarcação.

Quais são os melhores horários e dias para você? 📅
```
⚠️ Esta mensagem está correta? Altere abaixo se necessário:
```
[cole aqui a versão corrigida, se houver]
```

---

### 4.2 Quando não tem o slot exato que o paciente pediu
```
Não tenho {dia}-feira disponível nos próximos 7 dias, mas veja o que temos:
```
⚠️ Esta mensagem está correta? Altere abaixo se necessário:
```
[cole aqui a versão corrigida, se houver]
```

---

### 4.3 Apresentação das opções disponíveis
```
Ótimo! Encontrei estas opções disponíveis:

1. {dia}, {data} às {hora}
2. {dia}, {data} às {hora}
3. {dia}, {data} às {hora}

Qual funciona melhor pra você?
```
⚠️ Esta mensagem está correta? Altere abaixo se necessário:
```
[cole aqui a versão corrigida, se houver]
```

---

### 4.4 Confirmação da remarcação
```
✅ Consulta remarcada com sucesso!

📅 Nova data: {data} às {hora}
📍 Modalidade: {modalidade}

Qualquer dúvida, é só me chamar aqui 💚
```
⚠️ Esta mensagem está correta? Altere abaixo se necessário:
```
[cole aqui a versão corrigida, se houver]
```

---

### 4.5 Sem horários disponíveis na janela
```
Infelizmente não encontrei horários disponíveis nos próximos 7 dias.
Vou verificar com a Thaynara e te retorno em breve 🔍
```
⚠️ Esta mensagem está correta? Altere abaixo se necessário:
```
[cole aqui a versão corrigida, se houver]
```

---

## 5. Integração com Dietbox

⚠️ **Confirme as regras abaixo:**

- Após confirmar o novo horário com o paciente, o sistema deve atualizar o agendamento no Dietbox? **[ ] Sim [ ] Não (só registrar internamente)**
- O agendamento antigo deve ser cancelado no Dietbox? **[ ] Sim [ ] Não**
- Deve enviar mensagem de confirmação igual à do agendamento novo (com endereço, políticas)? **[ ] Sim [ ] Não**

---

## 6. Horários de atendimento por dia (base para geração de slots)

⚠️ **Confirme ou corrija os horários abaixo:**

| Dia       | Horários disponíveis                                      |
|-----------|-----------------------------------------------------------|
| Segunda   | 08h, 09h, 10h, 15h, 16h, 17h, 18h, 19h                  |
| Terça     | 08h, 09h, 10h, 15h, 16h, 17h, 18h, 19h                  |
| Quarta    | 08h, 09h, 10h, 15h, 16h, 17h, 18h, 19h                  |
| Quinta    | 08h, 09h, 10h, 15h, 16h, 17h, 18h, 19h                  |
| Sexta     | 08h, 09h, 10h, 15h, 16h, 17h                             |
| Sábado    | Não atende                                               |
| Domingo   | Não atende                                               |

---

## 7. Outras regras

⚠️ **Adicione aqui qualquer regra que esteja faltando:**
-
-
-
