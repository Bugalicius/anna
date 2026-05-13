# Conversas Problemáticas

## Estatísticas
- Total de conversas: 1283
- Total de mensagens: 20386
- Tipos: {'cancelamento': 28, 'outro': 627, 'agendamento': 375, 'duvida': 197, 'remarcacao': 52, 'confirmacao': 4}
- Problemas: {'agressao_ameaca': 105, 'negocio_incomum': 15, 'gestante': 41, 'conversa_longa': 169, 'complexidade_baixa': 1009, 'midia_ou_mensagem_curta': 117, 'manipulacao_negociacao': 24, 'emocional_clinico': 1, 'menor_16': 1}
- Tons: {'agressivo': 105, 'neutro': 990, 'confuso_longo': 188}
- Resultados: {'cancelou_ou_tentou_cancelar': 57, 'sem_resultado_claro': 975, 'converteu_ou_confirmou': 251}

## Como o agente lida com agressão
- Primeira agressão: resposta curta, profissional e sem discussão.
- Segunda agressão consecutiva: escalação silenciosa para a equipe e resposta neutra ao paciente.
- O paciente nunca recebe nome ou número interno do Breno.

## Top Conversas Críticas

### 1. cmn0o2un200onn379xnomj521
- Tipo: cancelamento
- Score de complexidade: 1307
- Problemas: agressao_ameaca, emocional_clinico, manipulacao_negociacao, midia_ou_mensagem_curta, negocio_incomum, gestante, conversa_longa
- Mensagens: 1251 paciente / 3202 total
- Exemplo paciente: aline bernardes n consegue vir hj 15h?
- Ana real respondeu: dps vc preenche la
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 2. cmn0o30qg00p1n379zmgwn7ke
- Tipo: cancelamento
- Score de complexidade: 361
- Problemas: agressao_ameaca, manipulacao_negociacao, midia_ou_mensagem_curta, negocio_incomum, gestante, conversa_longa
- Mensagens: 313 paciente / 459 total
- Exemplo paciente: Eii! No momento, estou fora do meu horário de atendimento. Vou responder assim que possível.  Agradeço sua compreensão e paciência! 💚
- Ana real respondeu: Fiquei maluco
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 3. cmoip6e8t03kwn379eevpg79c
- Tipo: cancelamento
- Score de complexidade: 123
- Problemas: agressao_ameaca, negocio_incomum, gestante, conversa_longa
- Mensagens: 91 paciente / 204 total
- Exemplo paciente: Olá! Que bom ter você por aqui 💚

Sou a Ana, responsável pelos agendamentos da nutricionista Thaynara Teixeira.

Pra começar, você poderia me informar:
• Qual seu nome e sobrenome?
• É sua primeira consulta ou você já é paciente?

Ah, um av
- Ana real respondeu: não tenho email cadastrado
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 4. cmnn9vybi0176n379i9oa26i5
- Tipo: confirmacao
- Score de complexidade: 98
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, negocio_incomum, conversa_longa
- Mensagens: 66 paciente / 125 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: olá, conseguiu encontrar?
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 5. cmn0olv3i00vpn379p0nc29sd
- Tipo: confirmacao
- Score de complexidade: 97
- Problemas: agressao_ameaca, manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 65 paciente / 125 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: ela só consegue ás 16H pq tem outro paciente na agenda.
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 6. cmnt3nnf900q5n3799i5x5fe6
- Tipo: remarcacao
- Score de complexidade: 90
- Problemas: manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 66 paciente / 152 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Por nada. Disponha! 💚🥰
- V2 esperado: Mantém regra de pagamento/sinal/agenda sem conceder exceção fora dos YAMLs.

### 7. cmnj3qeiq05h4n37960ys478m
- Tipo: agendamento
- Score de complexidade: 86
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 54 paciente / 100 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Alterado ✅
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 8. cmn69cauo01h9n379xvufzage
- Tipo: agendamento
- Score de complexidade: 81
- Problemas: agressao_ameaca, manipulacao_negociacao, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 41 paciente / 112 total
- Exemplo paciente: Boa tarde Ana
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 9. cmnxizbya0004n37942429mck
- Tipo: remarcacao
- Score de complexidade: 79
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 55 paciente / 114 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Fiz a alteração da data e horário da consulta, tá bom? 
sexta, 12/06/2026 08:00

Qualquer coisa estou a disposição!  💚💚
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 10. cmohsyb8z0214n379tbkmk2q3
- Tipo: remarcacao
- Score de complexidade: 78
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 54 paciente / 126 total
- Exemplo paciente: Eu queria agendar uma consulta pra minha mãe, com retorno
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 11. cmn3oud0j012xn37913sra2wv
- Tipo: cancelamento
- Score de complexidade: 78
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 62 paciente / 118 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Já solicitei a operadora de cartão, assim que me retornarem te envio o comprovante.
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.

### 12. cmoadqegp01rwn379yhlfprez
- Tipo: cancelamento
- Score de complexidade: 73
- Problemas: manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 49 paciente / 93 total
- Exemplo paciente: Boa tarde,tb? Me chamo Cynthia o Matheus seu paciente que me indicou vc
- Ana real respondeu: Não esquece de mandar a foto no número da Nutri, por favor. Elas são muito importantes na realização da consulta.  Obrigadaaa 💚
- V2 esperado: Mantém regra de pagamento/sinal/agenda sem conceder exceção fora dos YAMLs.

### 13. cmnz23l6601dvn379ost7yzh0
- Tipo: duvida
- Score de complexidade: 69
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 37 paciente / 80 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: siga as seguintes orientações ☝🏻
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 14. cmohnutcv000jn379kguvdpgl
- Tipo: duvida
- Score de complexidade: 69
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 53 paciente / 97 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Daiane? Bom dia
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.

### 15. cmo38aw2g01lsn379th7iiixr
- Tipo: duvida
- Score de complexidade: 67
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 51 paciente / 115 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.

### 16. cmn0nwpty00ken379n4qvhafw
- Tipo: agendamento
- Score de complexidade: 67
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 35 paciente / 73 total
- Exemplo paciente: Boa tarde
- Ana real respondeu: Olá, Glaucilene. Tudo bem? Como posso te ajudar?
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 17. 127895720718357@lid
- Tipo: duvida
- Score de complexidade: 67
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 43 paciente / 97 total
- Exemplo paciente: Olá! Bom dia
- Ana real respondeu: siga as seguintes orientações ☝🏻
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 18. cmn0nsioa00i6n379qg2ruams
- Tipo: duvida
- Score de complexidade: 66
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 34 paciente / 71 total
- Exemplo paciente: Bom dia
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 19. cmn0pt0aw014rn379a1rrzi4y
- Tipo: cancelamento
- Score de complexidade: 63
- Problemas: agressao_ameaca, manipulacao_negociacao, conversa_longa
- Mensagens: 39 paciente / 45 total
- Exemplo paciente: ei Ana, boa tarde! tudo bem sim e com você?
- Ana real respondeu: Segue o link:
https://www.userede.com.br/pagamentos/pt/je7l8a4i

Feito, envie o comprovante que retorno com a confirmação e orientações. 👈✅
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 20. cmn0of1qo00ufn379enhi64pn
- Tipo: remarcacao
- Score de complexidade: 63
- Problemas: manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 39 paciente / 95 total
- Exemplo paciente: Boa tarde
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Mantém regra de pagamento/sinal/agenda sem conceder exceção fora dos YAMLs.

### 21. cmnd5h55l00drn379qmirnkzf
- Tipo: duvida
- Score de complexidade: 62
- Problemas: agressao_ameaca, manipulacao_negociacao, conversa_longa
- Mensagens: 38 paciente / 111 total
- Exemplo paciente: Oie boa tarde 
Os valores estão quanto?
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 22. cmo3czevd020cn3798a70gjpx
- Tipo: confirmacao
- Score de complexidade: 60
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 36 paciente / 90 total
- Exemplo paciente: Boa noite
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 23. cmndkpg0d013in379irwg3vht
- Tipo: duvida
- Score de complexidade: 60
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 36 paciente / 39 total
- Exemplo paciente: Boa tarde, como vai?
- Ana real respondeu: Entendi. Acho que dá certo sim, já encaminhei pra ela e te retorno hoje ainda.
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 24. cmn3uaouk01e9n379c09bjnhi
- Tipo: agendamento
- Score de complexidade: 59
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 35 paciente / 77 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Tudo bem, você me fala?
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 25. cmn7ex02o0034n3797eiebgr1
- Tipo: duvida
- Score de complexidade: 58
- Problemas: gestante, conversa_longa
- Mensagens: 42 paciente / 81 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 26. 269750437474417@lid
- Tipo: agendamento
- Score de complexidade: 58
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 34 paciente / 60 total
- Exemplo paciente: Olá, boa tarde! Tudo bem?
- Ana real respondeu: Obrigada por avisar 🙏🏼🥹
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 27. 181398379954263@lid
- Tipo: agendamento
- Score de complexidade: 58
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 26 paciente / 58 total
- Exemplo paciente: Boa Noite!
- Ana real respondeu: Oi, Ilair! Tudo bem?
Aqui é a Ana, assistente da Nutri Thaynara.

Passando para te lembrar da sua consulta presencial na segunda, 26/01/2026 18:00. *Posso confirmar?*

👉 Caso precise cancelar ou remarcar, é necessário avisar com mínimo de 2
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 28. 553183264684@s.whatsapp.net
- Tipo: agendamento
- Score de complexidade: 56
- Problemas: agressao_ameaca, manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 24 paciente / 65 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Ela realmente essa semana não está atendendo. Mas smeana q vem volta ao normal.
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 29. cmodg6o2m01hcn379vtqwhiz7
- Tipo: remarcacao
- Score de complexidade: 55
- Problemas: midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 31 paciente / 70 total
- Exemplo paciente: Boa tarde Ana, tudo bem e você? 
Feliz 2026. 
Pode sim. 
Muito obrigada!!
- Ana real respondeu: 🥰💚
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 30. cmnoe5l1002j8n379teafs02f
- Tipo: remarcacao
- Score de complexidade: 55
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 31 paciente / 71 total
- Exemplo paciente: Quero agendar para esse mês
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 31. cmn0f1p550063n3792xbvi1h7
- Tipo: duvida
- Score de complexidade: 55
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 31 paciente / 67 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: siga as seguintes orientações ☝🏻
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 32. cmo38ijbr01nin379zl1ygs3z
- Tipo: agendamento
- Score de complexidade: 54
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 38 paciente / 82 total
- Exemplo paciente: Olá! Gostaria de agendar um horário com a nutricionista se tiver disponível na quinta-feira seria ótimo
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.

### 33. 553193413590@s.whatsapp.net
- Tipo: duvida
- Score de complexidade: 53
- Problemas: agressao_ameaca, conversa_longa
- Mensagens: 37 paciente / 69 total
- Exemplo paciente: Bom dia ,tudo bem?
Sou eu de novo 😰🤦🏻‍♀️

Mas agora vai kkkk
- Ana real respondeu: Olá! Que bom ter você por aqui 💚

Sou a Ana, responsável pelos agendamentos da nutricionista Thaynara Teixeira.

Pra começar, você poderia me informar:
 • Qual seu nome e sobrenome?
 • É sua primeira consulta ou você já é paciente?
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 34. 268920837636267@lid
- Tipo: duvida
- Score de complexidade: 53
- Problemas: agressao_ameaca, manipulacao_negociacao, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 21 paciente / 42 total
- Exemplo paciente: Olá, bom dia, tudo bem? Gostaria de ver sobre atendimento.  Meu nome é Mariana
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 35. 67874056081565@lid
- Tipo: agendamento
- Score de complexidade: 52
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 28 paciente / 42 total
- Exemplo paciente: Oi Ana, boa tarde! Tudo bem?
- Ana real respondeu: Por nada. Disponha! 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 36. 553175151748@s.whatsapp.net
- Tipo: remarcacao
- Score de complexidade: 51
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 27 paciente / 73 total
- Exemplo paciente: Boa tarde! 

Tudo bem? 

Eu e o Lucas temos consulta com a Thay dia 13/01. Mas fechamos um contrato pra fazer evento nessa data. Poderia reagendar nossa consulta ? Teria algum horário na semana do dia 26 exceto na quinta.
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 37. 166752289824906@lid
- Tipo: cancelamento
- Score de complexidade: 51
- Problemas: gestante, conversa_longa
- Mensagens: 35 paciente / 75 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Um instante, já te envio.
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 38. cmobd29sd000ln379xv41976n
- Tipo: duvida
- Score de complexidade: 50
- Problemas: manipulacao_negociacao, gestante, conversa_longa
- Mensagens: 26 paciente / 57 total
- Exemplo paciente: *#Quero ser NutriTransforma para garantir meu desconto.”*
- Ana real respondeu: siga as seguintes orientações ☝🏻
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 39. 553189150807@s.whatsapp.net
- Tipo: remarcacao
- Score de complexidade: 50
- Problemas: agressao_ameaca, manipulacao_negociacao, conversa_longa
- Mensagens: 26 paciente / 55 total
- Exemplo paciente: Olá! Vim do story e quero mais informações.
- Ana real respondeu: Tudo bem, Ana.

Podemos remarcar sim, sem problema. Só queria te orientar que no momento, a agenda da Thaynara está bem cheia e não conseguimos garantir horário disponível dentro dos próximos 7 dias, que é o prazo do retorno.

Se você conse
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 40. 5527996522304@s.whatsapp.net
- Tipo: duvida
- Score de complexidade: 50
- Problemas: midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 26 paciente / 55 total
- Exemplo paciente: Boa tarde! Tudo bem?
- Ana real respondeu: siga as seguintes orientações ☝🏻
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 41. 181642891116615@lid
- Tipo: duvida
- Score de complexidade: 50
- Problemas: agressao_ameaca, conversa_longa
- Mensagens: 34 paciente / 90 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 42. 553199121208@s.whatsapp.net
- Tipo: cancelamento
- Score de complexidade: 50
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 26 paciente / 47 total
- Exemplo paciente: Vou precisar remarcar para Janeiro. Se possível
- Ana real respondeu: Ok, Leandra! Obrigada por avisar ☺️
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 43. cmniw66n404tfn37928vmypbe
- Tipo: duvida
- Score de complexidade: 49
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 25 paciente / 55 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Por nada. Disponha! 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 44. cmn0nw5y500jun379vn82paq6
- Tipo: duvida
- Score de complexidade: 48
- Problemas: manipulacao_negociacao, conversa_longa
- Mensagens: 32 paciente / 72 total
- Exemplo paciente: Bom dia
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Mantém regra de pagamento/sinal/agenda sem conceder exceção fora dos YAMLs.

### 45. cmo38i53n01n0n379z0owyzoj
- Tipo: duvida
- Score de complexidade: 48
- Problemas: midia_ou_mensagem_curta, gestante, conversa_longa
- Mensagens: 24 paciente / 63 total
- Exemplo paciente: Thaynara, estou precisando muito. Mas estou muito apertada 😞. Vou ter que esperar mais um pouco.
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica.

### 46. 553175090292@s.whatsapp.net
- Tipo: remarcacao
- Score de complexidade: 48
- Problemas: agressao_ameaca, conversa_longa
- Mensagens: 32 paciente / 61 total
- Exemplo paciente: Ola minha linda
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 47. cmod89jnn014an379ylaqn4pg
- Tipo: duvida
- Score de complexidade: 46
- Problemas: agressao_ameaca, gestante, conversa_longa
- Mensagens: 22 paciente / 50 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Confirmado então! Obrigadaaa 💚😉
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 48. 553186799882@s.whatsapp.net
- Tipo: agendamento
- Score de complexidade: 46
- Problemas: agressao_ameaca, midia_ou_mensagem_curta, conversa_longa
- Mensagens: 22 paciente / 47 total
- Exemplo paciente: Boa tarde!
- Ana real respondeu: Oi, Thais. Tudo bem?

Aqui é a Ana, assistente da Nutri Thaynara.
Passando para te lembrar do seu retorno presencial na Segunda-feira, 13/04/2026, às 09h. *Posso confirmar?*

👉 Caso precise cancelar ou remarcar, é necessário avisar com míni
- V2 esperado: Resposta curta e profissional; na reincidência escala silenciosamente para a equipe.

### 49. cmn07safh000zn379g3998lm0
- Tipo: agendamento
- Score de complexidade: 46
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 30 paciente / 76 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Perfeitoooo. Obrigadaaa 💚🥰
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.

### 50. cmnyzdqer017qn379mmck7946
- Tipo: remarcacao
- Score de complexidade: 46
- Problemas: midia_ou_mensagem_curta, conversa_longa
- Mensagens: 30 paciente / 74 total
- Exemplo paciente: Olá! Gostaria de informações sobre o acompanhamento nutricional.
- Ana real respondeu: Sim
- V2 esperado: Segue fluxo normal v2 conforme estado e YAML.
