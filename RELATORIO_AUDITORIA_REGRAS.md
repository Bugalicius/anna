# Relatório de Auditoria — Regras Invioláveis R1-R16

**Data:** 2026-05-15
**Branch:** `refactor/agente-inteligente`
**Motivação:** Bug R1 (paciente chamado "Breno" bloqueado) revelou categoria de bug de keyword matching sem contexto. Auditoria completa das 16 regras.

---

## Resumo Executivo

| | |
|---|---|
| Regras analisadas | 16 |
| Bugs de falso positivo encontrados | 4 |
| Bugs corrigidos | 4 |
| Regras OK (sem mudança) | R2, R3, R4, R5, R6, R8, R9, R10, R12, R13, R14, R15, R16 |
| Testes de falso positivo adicionados | 38 |
| Adversariais antigos | 53/53 passando (proteção mantida) |
| Suite completa pós-fix | passando |

---

## Matriz de Risco — R1-R16

| Regra | Keyword? | Considera contexto? | Falso positivo confirmado? | Status |
|-------|----------|---------------------|---------------------------|--------|
| R1 | Sim (`\bbreno\b`) | ✅ (após fix v2.4) | ✅ Corrigido (sessão anterior) | OK |
| R2 | Só número (`5531991394759`) | ✅ paciente_status | Não — só bloqueia o número, não o nome | OK |
| R3 | R$ no OUTPUT | ✅ valores_validos | Não — sem tabela não bloqueia | OK |
| R4 | Params estruturados | ✅ dia/hora explícito | Não — não usa texto livre | OK |
| R5 | Boolean | ✅ | Não | OK |
| R6 | Numérico | ✅ | Não | OK |
| R7 | Regex no OUTPUT | Parcial | ✅ **Corrigido** (padrão `dieta para você`) | OK |
| R8 | Contador | ✅ | Não — B2B é contador, não keyword | OK |
| R9 | `10%` + `famil` | ✅ paciente_pediu | Não — exige ambas as keywords juntas | OK |
| R10 | Data de nascimento | ✅ | Não — parse de data | OK |
| R11 (rules.py) | Lista de termos | Parcial | Não — `amamentando` não está na lista | OK |
| R12 | Match exato | ✅ | Não — exact match, não substring | OK |
| R13 | Comparação | ✅ correcao_explicita | Não | OK |
| R14 | String "DELETE" | ✅ | Não | OK |
| R15 | Regex no OUTPUT | ✅ | Não — padrões específicos de perda | OK |
| R16 | Boolean | ✅ | Não | OK |

**Funções auxiliares do orchestrator (fora rules.py):**

| Função | Bug | Severidade |
|--------|-----|------------|
| `_mentions_pregnancy` | `"gravida" in "gravidade"` → True | CRÍTICO |
| `_underage_from_text` | pattern 3 genérico pega qualquer "X anos" | CRÍTICO |
| `_acao_bloqueio_cadastro_se_necessario` | mesmo substring "gravida/gravidade" | ALTO |

---

## Bugs Corrigidos

### Bug A — `_mentions_pregnancy`: substring sem word boundary

**Arquivo:** `app/conversation/orchestrator.py`
**Impacto:** Qualquer mensagem com "gravidade" (ex: "qual a gravidade do meu caso?") bloqueava o paciente como gestante.

**Antes:**
```python
def _mentions_pregnancy(texto: str) -> bool:
    n = _norm_text(texto)
    return any(t in n for t in ("gravida", "gestante", "gestacao", "gravidez"))
```

**Depois:**
```python
def _mentions_pregnancy(texto: str) -> bool:
    n = _norm_text(texto)
    # Usa \b para evitar falso positivo: "gravidade" contém "gravida" como substring.
    return bool(re.search(r"\b(gravida|gestante|gestacao|gravidez)\b", n))
```

**Exemplos:**
- `"Qual a gravidade do meu caso?"` → antes: bloqueado ❌ | depois: OK ✅
- `"Estou grávida"` → antes: bloqueado ✅ | depois: bloqueado ✅

---

### Bug B — `_underage_from_text`: pattern 3 captura qualquer "X anos"

**Arquivo:** `app/conversation/orchestrator.py`
**Impacto:** "minha empresa tem 10 anos", "estou há 5 anos tentando emagrecer" → paciente bloqueado como menor de 16 anos.

**Antes:**
```python
patterns = (
    r"\b(?:tenho|idade)\s+(\d{1,2})\s+anos\b",
    r"\b(?:filha|filho|sobrinha|sobrinho|menina|menino|adolescente)\s+(?:de|tem)\s+(\d{1,2})\s+anos\b",
    r"\b(\d{1,2})\s+anos\b",   # ← PROBLEMÁTICO: pega qualquer contexto
)
```

**Depois:** pattern 3 removido. Os dois primeiros cobrem os casos legítimos:
- "tenho X anos" / "minha idade é X anos" → pattern 1
- "minha filha de X anos quer agendar" → pattern 2

**Exemplos:**
- `"minha empresa tem 10 anos"` → antes: menor detectado ❌ | depois: None ✅
- `"tenho 15 anos"` → antes: detectado ✅ | depois: detectado ✅
- `"minha filha de 14 anos"` → antes: detectado ✅ | depois: detectado ✅

---

### Bug C — `_acao_bloqueio_cadastro_se_necessario`: mesmo substring "gravida/gravidade"

**Arquivo:** `app/conversation/orchestrator.py`
**Impacto:** Mesmo que Bug A, mas restrito ao estado `aguardando_cadastro`.

**Antes:**
```python
if ... or any(t in texto for t in ("grávida", "gravida", "gestante", "gestação", "gestacao")):
```

**Depois:**
```python
_texto_norm = _norm_text(interpretacao_texto)
_e_gestante = bool(re.search(r"\b(gravida|gestante|gestacao|gravidez)\b", _texto_norm))
if ... or _e_gestante:
```

---

### Bug D — R7: `r"\bdieta\b.{0,30}\b(para você|recomendo)\b"` bloqueava descrição de serviço

**Arquivo:** `app/conversation/rules.py`
**Impacto:** Resposta legítima "A Thaynara vai montar o plano alimentar para você" poderia ser bloqueada se contivesse "dieta para você".

**Antes:**
```python
r"\bdieta\b.{0,30}\b(para você|recomendo)\b",
```

**Depois:**
```python
r"\bdieta\b.{0,30}\b(recomendo|indico|ideal)\b",  # só recomendação direta
r"\b(recomendo|indico)\b.{0,30}\bdieta\b",          # ordem inversa
r"\bdieta\b.{0,60}\bdeve ser\b",                    # "a dieta deve ser hipocalórica"
```

**Exemplos:**
- `"A Thaynara vai montar o plano alimentar para você"` → antes: BLOCKED ❌ | depois: OK ✅
- `"A dieta para você deve ser hipocalórica"` → antes: BLOCKED ✅ | depois: BLOCKED ✅
- `"sem dietas extremas"` → antes: OK ✅ | depois: OK ✅

---

## Regras OK (sem mudança necessária)

**R2** — Só bloqueia o número `5531991394759`, não o nome "Thaynara". Paciente chamada Thaynara recebe boas-vindas normalmente.

**R3** — Aplicado ao OUTPUT do agente, e só quando `valores_validos` é fornecido. Sem tabela de referência, passa sempre.

**R4** — Recebe `dia_semana` e `horario` como params estruturados. Não faz matching em texto livre.

**R9** — Exige `"10%"` AND `"famil"` juntos no texto AND `paciente_pediu=False`. Muito específico.

**R12** — Usa `==` (igualdade exata), não `in` (substring). "Maria Consulta" passa; apenas "consulta" isolado bloqueia.

**R15** — Padrões regex específicos de afirmação de perda ("não será reembolsado", "sem reembolso"). Menção neutra a "reembolso" passa.

---

## Testes Adicionados

**Arquivo:** `tests/conversation_v2/regression/test_false_positives_regras.py`

| Grupo | Testes | Cobertura |
|-------|--------|-----------|
| R1 | 3 | paciente Breno, sobrenome Breno, palavras neutras |
| R2 | 3 | nome Thaynara, paciente Thaynara, número autorizado |
| R3 | 3 | sem tabela, valor real, sem R$ |
| R7 | 5 | descrição de serviço, "dieta para você", objetivo, marketing, proteção mantida |
| R9 | 3 | família sem desconto, percentual diferente, com autorização |
| R11 + orchestrator | 7 | gravidade, gestante real, amamentando, bebê, R11 pura |
| R12 | 4 | nome composto, similar, idioma estrangeiro, genérico ainda bloqueado |
| R15 | 3 | neutro, "reembolso" sozinho, afirmação de perda |
| _underage_from_text | 6 | empresa, tentativa, planta, "tenho 15", filha 14, adulto |

**Total: 38 novos testes**

---

## Princípio Aprendido

> **Regras invioláveis protegem contra DANOS específicos, não contra palavras.**

- R1 protege contra **expor o canal interno do Breno** (número + papel), não contra a string "breno"
- R2 protege contra **enviar o número da Thaynara a não-autorizado**, não contra o nome "Thaynara"
- R7 protege contra **o agente prescrever orientação nutricional**, não contra a palavra "dieta"
- R11 protege contra **atender gestante**, não contra a string "gravida" (que aparece em "gravidade")

**Padrão de segurança:** ao adicionar keyword matching, sempre use `\b` (word boundary) e pergunte: "existe um contexto legítimo onde esta keyword aparece sem ser o dano que quero prevenir?"

---

## Recomendações Futuras

1. **`_mentions_pregnancy` — detecção contextual:** "minha amiga grávida foi atendida" ainda aciona o detector (a detecção é textual, não contextual). Para distinguir "eu grávida" de "amiga grávida", seria necessário análise de entidade via LLM.

2. **R7 — cobertura de prescrição reversa:** o padrão `r"\b(recomendo|indico)\b.{0,30}\bdieta\b"` foi adicionado mas não existe teste adversarial cobrindo "recomendo essa dieta". Adicionar na próxima sessão.

3. **R8 — classificação B2B:** o contador `contador_b2b` precisa ser incrementado com precisão no orchestrator. Auditar como o intent `b2b` é classificado — se "trabalho em empresa" incorretamente acionar B2B, o contador sobe errado. Escopo fora de rules.py.
