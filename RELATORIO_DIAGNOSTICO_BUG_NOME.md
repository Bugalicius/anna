# Diagnostico — Bug "Agente nao entende nome Breno"

**Data:** 2026-05-14
**Branch:** refactor/agente-inteligente
**Investigacao:** estatica (leitura de codigo), sem execucao em producao

---

## Conversa de referencia

```
[19:04] Agente: "Ola! Que bom ter voce por aqui... Pra comecar, qual e o seu nome e sobrenome?"
[19:13] Paciente: "oi"
[19:13] Agente: "Acho que faltou seu nome Pode me mandar?"   <- correto
[19:14] Paciente: "Breno"
[19:14] Agente: "Pode me dar mais detalhes para eu te ajudar certinho?"   <- BUG
```

**Esperado:** agente aceitar "Breno" como nome valido e avancar para `aguardando_status_paciente`.

---

## Bug reproduzido localmente

**Script disponivel:** `scripts/debug_bug_nome.py`
**Execucao em prod:** nao necessaria — causa identificada por analise estatica do pipeline completo.

---

## Hipoteses validadas

### A — Confidence baixa do interpreter
- O estado `aguardando_nome` esta na lista `deterministic_states` do `interpreter.py` (linha 354-366).
- Quando o estado e deterministico e a heuristica retorna intent nao-ambigua, o Gemini **nao e chamado**.
- Para "Breno" em `aguardando_nome`: heuristica retorna `intent=informar_nome`, `confidence=0.75`.
- Nao ha threshold de confidence que descarte o resultado.
- **VEREDITO: NAO CULPADA**

### B — Estado errado apos "oi"
- Primeiro "oi": estado e `inicio` → `on_enter` dispara a saudacao, `proximo_estado = aguardando_nome`.
- Segundo "oi" (do print, 9 min depois): estado ja e `aguardando_nome`.
  - Heuristica: `_extrair_nome("oi")` → "Oi"; `R12("Oi")` → "oi" esta em `_NOMES_GENERICOS` → `passed=False`.
  - Trigger `nome_palavra_generica` casa: resposta correta "Acho que faltou seu nome".
  - Estado permanece `aguardando_nome`.
- Quando paciente manda "Breno", estado e `aguardando_nome`. Correto.
- **VEREDITO: NAO CULPADA**

### C — Validacao de nome muito rigorosa (R12)
- `_extrair_nome("Breno")` (`interpreter.py:105`): raw="Breno", len=5>=2, 1 palavra<=5 → retorna "Breno".
- `R12_validar_nome_nao_generico("Breno")` (`rules.py:364`):
  - len("breno")=5 > 1 ✓
  - "breno" NAO esta em `_NOMES_GENERICOS` ✓
  - Retorna `_ok(regra)` → `passed=True`
- `validacoes["validacao_nome_passou"] = True`
- **VEREDITO: NAO CULPADA**

### D — Trigger do YAML mal formado
- YAML (`config/fluxos/fluxo_1_agendamento.yaml`, linha 84):
  ```yaml
  nome_valido:
    trigger: "intent=informar_nome AND validacao_nome_passou=true"
  ```
- `_avaliar_trigger` em `state_machine.py:141`: divide por AND, avalia cada condicao.
- `_avaliar_condicao("validacao_nome_passou=true", ctx)` (`state_machine.py:128-129`):
  - regex `([\w.]+)\s*=\s*(.+)` casa.
  - `atual = True` (bool), `raw = "true"`.
  - `raw.lower() == "true"` → `return atual is True` → **True** ✓
- Trigger funciona corretamente para `validacao_nome_passou=True`.
- **VEREDITO: NAO CULPADA**

### E — Output do Gemini nao parseado corretamente
- Gemini nao e chamado (ver hipotese A).
- **VEREDITO: NAO CULPADA**

---

## CAUSA RAIZ IDENTIFICADA

**R1_nunca_expor_breno (`rules.py:155`) bloqueia a resposta do agente quando o PACIENTE se chama Breno.**

### Pipeline completo do turno com "Breno"

```
1. interpreter.py (heuristica):
   intent=informar_nome, validacao_nome_passou=True,
   entities={nome_extraido="Breno", primeiro_nome="Breno"}

2. state_machine.proxima_acao():
   trigger "nome_valido" CASA
   AcaoAutorizada(
     tipo=enviar_mensagem,
     mensagens=[Mensagem("Prazer, {primeiro_nome}! ...")],
     salvar_no_estado={"collected_data.nome": "Breno"},
     proximo_estado="aguardando_status_paciente"
   )

3. orchestrator.py linha 1707:
   _aplicar_salvar_no_estado(state, acao.salvar_no_estado)
   → state["collected_data"]["nome"] = "Breno"

4. orchestrator.py linha 1722:
   response_writer.escrever_async(acao, _contexto_template(state, entidades))
   → contexto["primeiro_nome"] = "Breno"
   → renderizar_template("Prazer, {primeiro_nome}! ...") = "Prazer, Breno! ..."

5. output_validator.validar_com_regeneracao():
   → R1_nunca_expor_breno("Prazer, Breno! ..."):
       re.search(r"\bbreno\b", "prazer, breno! ...") → MATCH!
       → _bloquear() → violacao BLOCKING

   → regenerador (response_writer._regenerador_sync):
       retorna [Mensagem("Pode me dar mais detalhes para eu te ajudar certinho?")]

   → segunda validacao: sem violacoes → APROVADO

6. Agente envia: "Pode me dar mais detalhes para eu te ajudar certinho?"
```

### Codigo exato que causa o problema

`app/conversation/rules.py`, funcao `R1_nunca_expor_breno` (linhas 155-167):

```python
def R1_nunca_expor_breno(texto: str) -> RuleResult:
    """Bloqueia se texto contem nome ou numero do Breno."""
    regra = "R1_nunca_expor_breno"
    texto_lower = texto.lower()
    for palavra in _PALAVRAS_BRENO:
        palavra_lower = palavra.lower()
        if palavra_lower == "breno":
            if re.search(r"\bbreno\b", texto_lower, flags=re.IGNORECASE):
                return _bloquear(regra, ...)   # <- bloqueia "Prazer, Breno!"
            continue
        ...
```

`_PALAVRAS_BRENO = ["Breno", "31 99205-9211", ...]` — contem o proprio nome.

A regra foi projetada para bloquear o agente de **revelar o contato interno do Breno** para pacientes. Porem, ela nao distingue entre:
- **Proibido:** "Fale com o Breno no 31 99205-9211" (expor contato interno)
- **Permitido:** "Prazer, Breno! Qual seu objetivo?" (usar o nome do PACIENTE)

---

## EVIDENCIA PRINCIPAL

Arquivo: `app/conversation/rules.py`, linha 162:
```python
if re.search(r"\bbreno\b", texto_lower, flags=re.IGNORECASE):
    return _bloquear(regra, f"Texto contém referência proibida ao Breno: {palavra!r}")
```

Arquivo: `app/conversation/response_writer.py`, linha 142-146:
```python
def _regenerar(violacoes, tentativa, atuais):
    logger.warning("Tentativa de regeneracao %d bloqueada por: %s", tentativa, aviso)
    return [Mensagem(tipo="texto", conteudo=_FALLBACK_PADRAO)]
```

`_FALLBACK_PADRAO = "Pode me dar mais detalhes para eu te ajudar certinho? 💚"` (linha 19).

---

## CORRECOES SUGERIDAS (em ordem de prioridade)

> **NOTA: Nenhuma correcao foi aplicada. Aguardando ordem.**

### Opcao 1 — Solucao cirurgica (recomendada)
Adicionar parametro `nome_paciente` ao contexto da validacao e excluir o nome do paciente da verificacao R1:

```python
def R1_nunca_expor_breno(texto: str, nome_paciente: str = "") -> RuleResult:
    regra = "R1_nunca_expor_breno"
    texto_lower = texto.lower()
    for palavra in _PALAVRAS_BRENO:
        palavra_lower = palavra.lower()
        if palavra_lower == "breno":
            # Se o paciente se chama Breno, permitir uso do nome na saudacao
            if nome_paciente.lower().split()[0] == "breno":
                continue
            if re.search(r"\bbreno\b", texto_lower, flags=re.IGNORECASE):
                return _bloquear(regra, ...)
            continue
        if palavra_lower in texto_lower:
            return _bloquear(regra, ...)
    return _ok(regra)
```

Requer propagar `nome_paciente` ate o `validar_resposta_completa`:
```python
def validar_resposta_completa(texto, contexto):
    nome_paciente = contexto.get("nome_paciente") or contexto.get("primeiro_nome") or ""
    resultados.append(R1_nunca_expor_breno(texto, nome_paciente=nome_paciente))
    ...
```

### Opcao 2 — Remover "Breno" de _PALAVRAS_BRENO, manter apenas o numero
R1 ja era suficiente com so o numero. O nome sozinho nunca deveria ser bloqueado:

```python
_PALAVRAS_BRENO = [
    # "Breno",  # <- removido: pacientes podem ter esse nome
    "31 99205-9211",
    "31992059211",
    "5531992059211",
    "(31) 99205-9211",
]
```

Porem isso exigiria garantir que o numero do Breno nao apareca em nenhuma mensagem.
A protecao pelo nome era uma camada adicional — avaliar se e necessaria.

### Opcao 3 — Ajustar o output_validator para nao chamar R1 em mensagens de saudacao
Menos preciso. Nao recomendado.

---

## TESTES QUE PRECISAM SER ADICIONADOS

1. **`test_r1_nao_bloqueia_nome_paciente_breno`** em `tests/conversation_v2/test_rules.py`:
   ```python
   def test_r1_nao_bloqueia_nome_paciente_breno():
       # R1 NAO deve bloquear quando o agente usa o nome do PROPRIO paciente
       result = R1_nunca_expor_breno("Prazer, Breno! E sua primeira consulta?")
       # Atualmente FALHA (bug confirmado)
       assert result.passou is True
   ```

2. **`test_paciente_chamado_breno_avancar_estado`** em `tests/conversation_v2/regression/`:
   ```python
   async def test_paciente_chamado_breno_avancar_estado():
       phone = "5599debug_breno"
       await send(phone, "oi")  # inicia conversa
       await send(phone, "oi")  # segundo oi → pede nome
       result = await send(phone, "Breno")  # deve avancar
       state = await state_for(phone)
       assert state["estado"] == "aguardando_status_paciente"
       assert state["collected_data"]["nome"] == "Breno"
       assert not any("mais detalhes" in m.conteudo for m in result.mensagens_enviadas)
   ```

3. **`test_r1_bloqueia_numero_mas_nao_nome_isolado`** para garantir que o numero do Breno
   continua bloqueado mesmo apos a correcao.

---

## POR QUE PASSOU NO HARDENING (Fase 8)

O runner E2E (`tests/conversation_v2/e2e/runner.py`) usa mocks para tools externos
(Dietbox, pagamento) mas **nao mocka o output_validator nem as regras inviolaveis**.
Portanto o pipeline inteiro roda com R1 ativo.

O problema e mais simples: **nenhuma conversa de teste usa o nome "Breno" para o paciente**.

Arquivo `tests/conversation_v2/e2e/test_fluxo_1_agendamento.py`, linha 76:
```python
await send(phone, "Maria")  # <- nome usado nos testes
```

Os 1063 cenarios do hardening usaram nomes como "Maria", "Maria Silva", "Ana" — nenhum
conflita com `_PALAVRAS_BRENO`. O avaliador de similaridade semantica provavelmente marcou
o fallback "Pode me dar mais detalhes" como "aceitavel" em outros contextos onde ele aparece
legitimamente, mascarando o bug.

---

## RESUMO EXECUTIVO

| Item | Detalhe |
|------|---------|
| Bug reproduzido | Sim (por analise estatica) |
| Causa raiz | `R1_nunca_expor_breno` bloqueia "Prazer, Breno!" porque contem `\bbreno\b` |
| Arquivo | `app/conversation/rules.py:162` |
| Efeito | `output_validator` chama regenerador → `_FALLBACK_PADRAO` |
| Resultado | Paciente recebe "Pode me dar mais detalhes..." em vez de avancar |
| Correcao preferida | Opcao 1 (propagar `nome_paciente` para R1) |
| Testes faltando | 3 (listados acima) |
| Por que passou no CI | Testes usaram "Maria" como nome, nunca "Breno" |

---

**STATUS: PARADO. Aguardando ordem para corrigir.**
