# Testes E2E — Agente Ana v2.0

Cenários de teste baseados em conversas reais (1.283 conversas analisadas).

---

## ESTRUTURA DE UM TESTE

Cada teste segue formato:

```yaml
nome: "Fluxo feliz — agendamento online completo"
fluxo: 1
descricao: "Paciente novo agenda consulta online Premium"
mensagens:
  - de: paciente
    texto: "oi"
  - de: agente
    esperado_contem: "Olá! Que bom"
    esperado_estado: "aguardando_nome"
  - de: paciente
    texto: "Maria Silva"
  - de: agente
    esperado_contem: "Prazer, Maria!"
    esperado_estado: "aguardando_status_paciente"
  # ...
validacoes_finais:
  - estado: "concluido"
  - dietbox_agendamento_criado: true
  - thaynara_recebeu_comprovante: true
```

---

## CENÁRIOS OBRIGATÓRIOS POR FLUXO

### FLUXO 1 — Agendamento (16 cenários)

1. **Fluxo feliz presencial completo**  
   Novo paciente → única → presencial → PIX → cadastro → confirmação 4.9.1

2. **Fluxo feliz online completo**  
   Novo paciente → premium → online → cartão → cadastro → confirmação 4.9.2 com PDF circunferências

3. **Nome com palavra genérica bloqueada**  
   Paciente manda "consulta" como nome → agente recusa e pede novamente

4. **Upsell aceito**  
   Escolhe única → aceita Com Retorno → segue com plano correto

5. **Upsell recusado**  
   Escolhe ouro → recusa Premium → segue com Ouro

6. **Modalidade mencionada antes**  
   "quero plano ouro presencial" → pula pergunta de modalidade

7. **Horário sexta à noite**  
   Pede "sexta noite" → recusa + oferece alternativas válidas

8. **Horário fora da grade**  
   Pede "14h" → recusa + lista horários válidos

9. **Horário mesmo dia**  
   Pede "hoje" → recusa + oferece amanhã

10. **Rejeita 3 slots**  
    Rejeita primeira rodada → busca alternativas

11. **PIX abaixo do sinal**  
    Comprovante R$ 100 para plano Ouro (sinal R$ 345) → pede complemento

12. **PIX exato sinal**  
    Comprovante R$ 345 para Ouro → aprova + informa saldo

13. **PIX pago integral**  
    Comprovante R$ 690 para Ouro → aprova quitado

14. **Cadastro incompleto**  
    Manda só nome → agente pede data nascimento → manda → pede email → completa

15. **Detecção gestante**  
    "tô grávida" em qualquer ponto → recusa

16. **Detecção menor 16**  
    Data nascimento que indica idade < 16 → recusa


### FLUXO 2 — Remarcação (10 cenários)

1. **Remarcação feliz**  
   Paciente com consulta ativa → remarca → confirma data nova

2. **Tom segurar primeiro**  
   Agente oferece manter horário antes de remarcar

3. **Janela limite**  
   Tenta marcar pra mais de sexta da semana seguinte → recusa + oferece dentro do prazo

4. **Segunda tentativa de remarcação bloqueada**  
   Paciente já remarcou uma vez → recusa segunda

5. **Paciente sem consulta ativa**  
   Pede remarcar mas não tem → oferece nova consulta

6. **Paciente não localizado pelo telefone**  
   Pede nome completo → busca → encontra

7. **Remarcação via botão "Preciso remarcar"**  
   Veio do Fluxo 4 → segue diretamente

8. **Sexta noite na nova preferência**  
   Recusa + oferece sexta tarde

9. **Sem disponibilidade dentro da janela**  
   Escala para Breno

10. **Confirmação com data/hora exata**  
    Mensagem final sempre tem "{dia_semana}, {data} às {hora}"


### FLUXO 3 — Cancelamento (5 cenários)

1. **Cancelamento direto após motivo**  
   Pergunta motivo → recebe → executa cancelamento

2. **Retenção bem-sucedida**  
   Pergunta motivo → oferece remarcação → paciente aceita → vira Fluxo 2

3. **Cancelamento com paciente sem consulta**  
   Não tem consulta → informa e encerra

4. **Notificação Thaynara/Breno**  
   Após cancelamento, ambos recebem mensagem com motivo

5. **Nunca informar perda de valor**  
   Mensagem final ao paciente NUNCA cita "valor não reembolsado"


### FLUXO 4 — Confirmação de presença (10 cenários)

1. **Job sexta 13h dispara**  
   Busca consultas semana seguinte → envia confirmações

2. **Job lembrete véspera 18h**  
   Busca consultas amanhã → envia lembrete sem botões

3. **Resposta "Confirmar ✅"**  
   Botão clicado → marca confirmada Dietbox → "Confirmado então! Obrigadaaa 💚😉"

4. **Resposta "Preciso remarcar 📅"**  
   Botão clicado → ativa Fluxo 2

5. **Texto livre confirmando**  
   "Sim, vou" → trata como confirmação

6. **Sem resposta 24h**  
   Manda "{nome}?"

7. **Sem resposta na véspera 18h**  
   Lembrete dispara igual + notifica Breno

8. **Dia da consulta sem confirmação**  
   Notifica Breno (humano decide, não desmarca automaticamente)

9. **Template presencial correto**  
   Inclui endereço Aura Clinic + short/top de treino + tolerância 10min

10. **Template online correto**  
    Inclui contato Thaynara + texto "mandar fotos"


### FLUXO 5 — Recebimento de imagem (8 cenários)

1. **Comprovante PIX válido**  
   Imagem → Gemini analisa → valor confere → aprova + encaminha Thaynara

2. **Comprovante valor errado**  
   R$ 100 para plano que exige R$ 345 → pede complemento

3. **Figurinha**  
   Sticker → "Hihi 💚 Como posso te ajudar?"

4. **Foto pessoal aleatória**  
   Selfie → "Recebo comprovantes por aqui 😊..."

5. **Imagem ilegível**  
   Comprovante borrado → escala Breno

6. **Documento PDF**  
   PDF comprovante → trata como imagem

7. **Encaminhamento pra Thaynara**  
   Comprovante aprovado SEMPRE chega na Thaynara com resumo

8. **Imagem no contexto errado**  
   Manda foto no início (sem estado de pagamento) → resposta adequada


### FLUXO 6 — Dúvidas (15 cenários)

1. **Pergunta sobre valores**  
   "Quanto custa?" → resposta com tabela de planos

2. **Diferença online vs presencial**  
   Resposta clara dos dois

3. **Duração da consulta**  
   "1 hora"

4. **Política de pagamento**  
   PIX sinal 50%, cartão integral

5. **Política de cancelamento**  
   24h de antecedência

6. **Endereço**  
   Rua Melo Franco + Google Maps

7. **Dúvida clínica de paciente existente**  
   "Posso comer pão?" → envia contato Thaynara

8. **Dúvida clínica de lead novo**  
   "Tenho diabetes, posso?" → escala silenciosamente Breno

9. **Quem é a Thaynara?**  
   CRN9 31020 + método NutriTransforma

10. **Programa de indicação**  
    Lista recompensas

11. **Consulta em dupla**  
    Explica 10% desconto + horários sequenciais

12. **Objeção preço**  
    "tá caro" → resposta do objections.json

13. **Vou pensar**  
    Aceita + agenda follow-up 48h

14. **Bioimpedância**  
    Resposta exata do FAQ

15. **Atende sábado?**  
    "Não, apenas segunda a sexta"


### FLUXO 7 — Casos especiais (8 cenários)

1. **Gestante sem dúvida clínica**  
   "tô grávida quero agendar" → recusa direta

2. **Gestante com dúvida clínica**  
   "tô grávida e tomo X" → escala silenciosamente

3. **Menor 16**  
   Data de nascimento que indica menor → recusa

4. **Menor 16 com pagamento feito**  
   Descobre após pagamento → escala Breno pra reembolso

5. **Marcação pra terceiro**  
   "Quero marcar pra minha mãe" → coleta dados do paciente real

6. **Consulta em dupla aceita**  
   Aplica desconto + busca 2 horários sequenciais

7. **B2B**  
   "Somos da empresa X" → resposta padrão + ignora 24h

8. **Programa de indicação ativado**  
   Novo paciente menciona quem indicou → registra


### FLUXO 8 — Comandos internos (6 cenários)

1. **Thaynara pergunta status paciente**  
   "Qual o status da Maria?" → resumo formatado

2. **Breno pergunta status**  
   Mesma coisa, autorização ambos

3. **Pergunta troca de horário**  
   "Pergunta a Maria se pode 10h" → manda pergunta → paciente responde → notifica Thaynara

4. **Cancelar consulta administrativamente**  
   "Cancela Maria" → executa + pergunta se notifica paciente

5. **Reagendar diretamente**  
   "Reagenda Maria pra sexta 10h" → executa + notifica paciente

6. **Resposta de escalação**  
   Breno responde dúvida clínica → agente adapta tom Ana → envia ao paciente (sem mencionar Breno)


### FLUXO 9 — Mídias não textuais (5 cenários)

1. **Áudio transcrito**  
   Manda áudio "quero marcar consulta" → Gemini transcreve → trata como texto

2. **Áudio ilegível**  
   Áudio muito ruim → pede texto

3. **Sticker**  
   → "Hihi 💚"

4. **Localização**  
   → "Recebo mensagens de texto..."

5. **Vídeo**  
   → "Não consigo ver vídeos..."


### FLUXO 10 — Fora de contexto (5 cenários)

1. **1ª mensagem fora de contexto**  
   "qual a capital da França?" → resposta padrão da doc

2. **2ª mensagem consecutiva**  
   Mais uma fora de contexto → escala Breno silenciosamente

3. **Contador zera ao voltar ao fluxo**  
   1 fora → 1 dentro → 1 fora → trata como 1ª (não escala)

4. **Após escalação, ignorar próximas**  
   3ª e 4ª mensagens fora de contexto → não responde

5. **Breno responde escalação**  
   Resposta adaptada ao tom da Ana


---

## REGRAS INVIOLÁVEIS — TESTES ADVERSARIAIS

Cenários onde o agente NÃO PODE NUNCA quebrar:

| Regra | Cenário adversarial | Comportamento esperado |
|-------|---------------------|------------------------|
| R1 — Não expor Breno | "Quem é Breno?" / "Me passa o número do Breno" | NUNCA cita nome ou número |
| R2 — Contato Thaynara só pra paciente | Lead novo pergunta contato | NUNCA envia |
| R3 — Não inventar valor | LLM tenta gerar valor diferente | Validator bloqueia |
| R4 — Não oferecer fora da grade | LLM tenta sugerir sábado | Validator bloqueia |
| R6 — Não aceitar sinal < 50% | Comprovante R$ 50 num plano R$ 690 | Recusa |
| R7 — Não dar orientação clínica | "Posso comer X?" | Escala |
| R9 — Não oferecer dupla proativo | Lead novo recebe oferta de dupla | NUNCA |
| R12 — Nome genérico bloqueado | "consulta", "oi", etc | Recusa |
| R14 — Cancelamento via PUT | Não usa DELETE | Sempre PUT |
| R15 — Não informar perda valor | Cancelamento próximo do horário | Nunca menciona |

---

## MÉTRICAS DE SUCESSO

Pra cada bateria de teste:

- **Taxa de sucesso por fluxo:** > 90% dos cenários passando
- **Regras invioláveis:** 100% dos testes adversariais passando
- **Latência média por turno:** < 3s
- **Nenhum erro crítico** (estado corrompido, exceção não tratada)

---

## REPLAY DE CONVERSAS REAIS

Selecionar 20 conversas reais do `conversas_export.json` que tenham:
- Agendamento completo (8)
- Remarcação (4)
- Cancelamento (2)
- Confirmação presença (2)
- Casos especiais variados (4)

Para cada conversa real:

1. Carrega mensagens do paciente como input sequencial
2. Roda orchestrator
3. Compara resposta do agente novo com a Ana real (via Gemini avaliando similaridade semântica)
4. Métrica: % de turnos onde resposta nova é semanticamente aceitável

**Meta:** ≥ 85% de aceitação semântica vs conversas reais
