# Erros Identificados nas Conversas Reais

Baseado em análise de 1.283 conversas, 20.386 mensagens.

---

## D.1 — Valor errado cobrado no link de pagamento

**Conversa real:** "Ana Camila boa noite. é pq vc mandou R$ 75 e a consulta é R$ 200"

**Problema:** O gateway (Rede) gerou link com valor divergente do plano escolhido.

**Solução implementada:** `app/tools/payments.py` — após gerar o link, compara `parcela_valor × parcelas` com o valor esperado do KB. Se divergir mais de R$1, loga `WARNING`. O link ainda é retornado (o valor correto é exibido na mensagem para o paciente pelo responder), mas o warning permite rastrear e corrigir o gateway.

---

## D.2 — Paciente frustrado ao tentar cancelar sem agendamento ativo

**Conversa real:** "vc é muito burro. quero meu dinheiro de volta"

**Problema:** Quando o Dietbox retorna 404 ou "sem agendamento ativo", o agente escalava como erro técnico, expondo linguagem interna e gerando frustração.

**Solução implementada:** `app/conversation/responder.py` — quando `cancelar` falha com erro de "não encontrado" ou "sem agendamento", retorna mensagem amigável: "Não encontrei sua consulta no sistema. Pode me confirmar seu nome completo? 💚" em vez de escalar.

---

## D.3 — Loop de remarcação sem fim

**Padrão identificado:** Pacientes que remarcaram 3+ vezes o mesmo horário, gerando atrito e sobrecarga.

**Solução implementada:**
- `app/conversation/state.py` — campo `remarcacoes_count` incrementado a cada `remarcar_dietbox` bem-sucedido
- `app/router.py` — ao atingir 3+ remarcações, envia notificação para o número interno (Breno): "Ana: {nome} está tentando remarcar pela {n}ª vez. Pode dar uma atenção especial? 💚"
- Flag `loop_remarcacao_notificado` evita notificações repetidas

---

## D.4 — Agente respondeu mensagem interna da Thaynara

**Conversa real:** Thaynara mandou instruções internas ("Renata Oliveira vai chamar aí e marcar") e o agente respondeu como se fosse paciente.

**Solução já existia:** `app/webhook.py` — `is_numero_interno(phone)` detecta o número da Thaynara/Breno e roteia para `processar_resposta_breno()` em vez de processar como paciente. Número configurado via env var `NUMERO_INTERNO`.

**Status:** Já corrigido em versão anterior. Monitorar via logs: `"Mensagem do número interno detectada"`.

---

## D.5 — Mensagem de fora do horário enviada em loop

**Problema:** Agente mandava "fora do meu horário de atendimento" em CADA mensagem recebida fora do horário.

**Solução já existia:** `app/webhook.py` — `_should_send_after_hours_once()` usa Redis SET NX com chave `after_hours:{phone_hash}:{data}` para enviar o aviso apenas UMA vez por dia por número.

**Status:** Já implementado. TTL de 24h. Env var `DISABLE_AFTER_HOURS_NOTICE=true` desativa para testes.
