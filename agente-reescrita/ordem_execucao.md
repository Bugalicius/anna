# ORDEM DE EXECUÇÃO — Reescrita Agente Ana
# Estratégia: Claude Code OU Codex (revezamento conforme tokens)
# Meta: ~7 dias úteis

---

## ANTES DE COMEÇAR

### Passo A — Baixar arquivos deste chat e organizar

Baixa os 16 arquivos numa pasta local:

```
~/agente-reescrita/
├── config/
│   ├── global.yaml                              ← renomear config_global.yaml
│   └── fluxos/
│       ├── fluxo_1_agendamento.yaml
│       ├── fluxo_2_3_remarcacao_cancelamento.yaml
│       ├── fluxo_4_confirmacao_presenca.yaml
│       ├── fluxo_5_recebimento_imagem.yaml
│       ├── fluxo_6_7_duvidas_casos_especiais.yaml
│       ├── fluxo_8_comandos_internos.yaml
│       ├── fluxo_9_midias_nao_textuais.yaml
│       └── fluxo_10_fora_de_contexto.yaml
└── prompts/
    ├── prompt_mestre_fase_0.md
    ├── prompt_fase_1_nucleo.md
    ├── prompt_fase_2_tools.md
    ├── prompts_fases_3_a_9.md
    └── testes_e2e.md
```

**Importante:** renomeia `config_global.yaml` pra apenas `global.yaml`.

### Passo B — Subir os YAMLs pro repositório

Antes de começar qualquer fase, sobe os YAMLs pro VPS ou local de trabalho:

```bash
cd /caminho/do/repo/agente
git checkout main
git pull
git checkout -b refactor/agente-inteligente
mkdir -p config/fluxos
cp ~/agente-reescrita/config/global.yaml config/
cp ~/agente-reescrita/config/fluxos/*.yaml config/fluxos/
git add config/
git commit -m "feat: YAMLs declarativos dos 10 fluxos"
git push -u origin refactor/agente-inteligente
```

A partir daqui, o Claude Code/Codex já encontra os YAMLs no repo.

---

## REGRA DE OURO PARA REVEZAMENTO

Sempre que precisar trocar de ferramenta:

1. **Antes de encerrar a sessão atual:** peça pra ela fazer commit + push do que está pronto
2. **Ao abrir a nova ferramenta:** peça pra fazer `git pull` antes de começar
3. **Sempre passe contexto:** "estamos na Fase X, a Fase Y já terminou (commit Z), continue daqui"

---

## SEQUÊNCIA DE EXECUÇÃO

### FASE 0 — Setup (30 minutos)

**Onde:** `prompts/prompt_mestre_fase_0.md`

**Passos:**
1. Abre Claude Code (ou Codex)
2. Cola o conteúdo INTEIRO do `prompt_mestre_fase_0.md`
3. Aguarda execução
4. Valida o checklist de aceitação ao final
5. Commit + push

**Critério pra avançar:** mensagem `✅ FASE 0 CONCLUÍDA` recebida.

---

### FASE 1 — Núcleo do sistema (1 dia)

**Onde:** `prompts/prompt_fase_1_nucleo.md`

**Passos:**
1. Cola o conteúdo INTEIRO no Claude Code ou Codex
2. Aguarda criação dos módulos: config_loader, models, state_machine, rules, response_writer, output_validator, orchestrator (esqueleto)
3. Verifica testes: `pytest tests/conversation_v2/ -v`
4. Commit + push

**Se tokens acabarem no meio:** peça commit do que está pronto + lista do que falta. Na próxima ferramenta, continua de onde parou.

---

### FASE 2 — Tools e integrações (1 dia)

**Onde:** `prompts/prompt_fase_2_tools.md`

**Passos:**
1. Cola conteúdo
2. Aguarda criação de todas as tools (scheduling, patients, payments, media, notifications, commands)
3. Testes: `pytest tests/conversation_v2/tools/ -v`
4. Commit + push

---

### FASE 3 — Fluxo 1 Agendamento (1-2 dias) ⚠️ MAIS CRÍTICO

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 3)

**Passos:**
1. Cola APENAS a seção "FASE 3" do arquivo
2. Aguarda implementação dos 19 estados do Fluxo 1
3. Roda os 16 testes E2E obrigatórios do `testes_e2e.md` (seção Fluxo 1)
4. Commit + push

**Atenção especial:** essa é a fase mais demorada. Provavelmente vai consumir bastante token. Esteja preparado pra revezar.

---

### FASE 4 — Fluxos 2 e 3 Remarcação + Cancelamento (1 dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 4)

**Passos:**
1. Cola APENAS a seção "FASE 4"
2. Implementa estados de remarcação e cancelamento
3. Roda testes E2E dos dois fluxos
4. Commit + push

---

### FASE 5 — Fluxos 4 e 5 Confirmação + Imagens (1 dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 5)

**Atenção:** Fase 5 envolve scheduler + interceptador, é mais complexa do que parece. Não pule testes.

---

### FASE 6 — Fluxos 6 e 7 Dúvidas + Casos Especiais (1 dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 6)

---

### FASE 7 — Fluxos 8, 9 e 10 Comandos + Mídias + Fora contexto (meio dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 7)

---

### FASE 8 — Testes E2E completos (1 dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 8) + `prompts/testes_e2e.md`

**Passos:**
1. Cola seção "FASE 8" + anexa o `testes_e2e.md` como referência
2. Aguarda criação do test runner + bateria completa
3. Roda tudo: `pytest tests/conversation_v2/ -v`
4. Recebe relatório `RELATORIO_FASE_8.md`
5. Se taxa de sucesso ≥ 85%: avança. Se não: corrige antes.

---

### FASE 9 — Cutover em produção (meio dia)

**Onde:** `prompts/prompts_fases_3_a_9.md` (seção FASE 9)

⚠️ **IMPORTANTE:** só executa essa fase quando Fase 8 estiver 100% validada.

**Passos:**
1. Cola seção "FASE 9"
2. Aguarda backup + cutover + smoke tests
3. Monitora produção por 48h

---

## TEMPLATE DE PROMPT PRA RETOMAR APÓS TROCA DE FERRAMENTA

Quando trocar de Claude Code pra Codex (ou vice-versa), abre a nova ferramenta e cola:

```
Estou no meio de uma reescrita do agente Ana (branch refactor/agente-inteligente).

CONTEXTO:
- Fases concluídas: 0, 1, 2 (commits XXX, YYY, ZZZ)
- Fase atual: FASE [N]
- Status da fase atual: [resumo do que já foi feito nesta fase]
- Arquivos YAML de configuração em config/global.yaml e config/fluxos/

PRIMEIRA AÇÃO:
1. Faz git pull pra pegar último estado
2. Lê REFACTOR.md pra entender contexto
3. Lê config/global.yaml e os YAMLs dos fluxos que vai implementar
4. Continua a Fase [N] do ponto em que ela parou

PROMPT DA FASE:
[cola aqui o conteúdo da fase que estava executando]
```

---

## CRONOGRAMA REALISTA

| Dia | Fase | Tempo aproximado |
|-----|------|------------------|
| 1 (manhã) | Fase 0 + Fase 1 (início) | 4h |
| 1 (tarde) | Fase 1 (fim) | 4h |
| 2 | Fase 2 | 8h |
| 3 | Fase 3 (Fluxo 1) | 8h |
| 4 | Fase 3 (fim) + Fase 4 (Remarc/Cancel) | 8h |
| 5 | Fase 5 (Confirm + Imagens) | 8h |
| 6 | Fase 6 + Fase 7 (Dúvidas/Especiais + Comandos/Mídias) | 8h |
| 7 | Fase 8 (Testes E2E) | 8h |
| 8 | Fase 9 (Cutover) + monitoramento | 4h |

**Total: ~7-8 dias úteis.** Pode ser mais rápido se as fases simples saírem em meio dia.

---

## CHECKLIST DIÁRIO

Antes de começar o dia:
- [ ] `git status` limpo
- [ ] `git pull` feito
- [ ] Branch correta: `refactor/agente-inteligente`
- [ ] Tokens da ferramenta atual: verificar se tem suficiente pra fase do dia

Antes de trocar de ferramenta:
- [ ] Pediu commit do que está pronto?
- [ ] Pediu push?
- [ ] Anotou commit hash e o que estava em andamento?

Antes de dormir:
- [ ] Commit + push do trabalho do dia
- [ ] Anotou em REFACTOR.md o que ficou pronto vs pendente

---

## SE ALGO TRAVAR

**Erro nos YAMLs:** verifica com `python scripts/validar_yamls.py`

**LLM gera resposta errada nos testes:** olha o `logs/metrics.jsonl` pra ver qual regra falhou

**Estado corrompido:** flush Redis local:
```bash
docker compose exec redis redis-cli FLUSHALL
```

**Falta de tokens no meio de uma fase:** ferramenta atual faz commit, troca ferramenta, abre nova, faz git pull, cola o contexto + resto da fase.

**Bug detectado em fase anterior já fechada:** pequenos bugs → corrige na hora. Bugs grandes → anota numa lista, corrige na Fase 8 (testes).

---

## ÚLTIMA DICA

Se o Claude Code/Codex começar a fazer coisa diferente do que está no prompt, **interrompa** e refaça o prompt sendo mais específico. Não deixe ele "improvisar" — o ponto da reescrita é justamente cortar improvisação.

Boa sorte! 💪
