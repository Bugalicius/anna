# Comparativo de LLMs para Chatbot WhatsApp - Nutricionista (Brasil)
### Atualizado: Março 2026 | Cotacao USD/BRL: ~5.31

---

## Resumo Executivo

Este documento compara 6 opcoes de LLM para um chatbot de WhatsApp voltado a uma clinica de nutricao no Brasil. O bot precisa de excelente compreensao e geracao de portugues brasileiro (formal e coloquial).

---

## Tabela Comparativa de Precos (por 1M de tokens)

| Modelo | Input (USD) | Input (BRL) | Output (USD) | Output (BRL) | Free Tier |
|--------|------------|------------|-------------|-------------|-----------|
| **Groq - Llama 3.3 70B** | $0.59 | R$3.13 | $0.79 | R$4.20 | Sim, com rate limits (~30 RPM, 6K TPM) |
| **Groq - Llama 3.1 8B** | $0.05 | R$0.27 | $0.08 | R$0.42 | Sim, com rate limits |
| **Gemini 2.0 Flash** | $0.10 | R$0.53 | $0.40 | R$2.12 | Sim: 15 RPM, 1000 req/dia |
| **Gemini 2.5 Flash** | $0.30 | R$1.59 | $2.50 | R$13.28 | Sim: 10 RPM, 250 req/dia |
| **Claude Haiku 4.5** | $1.00 | R$5.31 | $5.00 | R$26.55 | Nao (free credits limitados no console) |
| **GPT-4o-mini** | $0.15 | R$0.80 | $0.60 | R$3.19 | Nao (free credits de $5 p/ novos usuarios) |
| **DeepSeek V3** | $0.14 | R$0.74 | $0.28 | R$1.49 | Sim: 5M tokens gratis (30 dias) |
| **DeepSeek R1** | $0.55 | R$2.92 | $2.19 | R$11.63 | Incluido nos 5M tokens |
| **Ollama Local** | $0.00 | R$0.00 | $0.00 | R$0.00 | Totalmente gratuito (custo = hardware + energia) |

---

## Comparativo Detalhado por Modelo

### 1. Groq (Llama 3.3 70B / Llama 3.1 8B)

| Aspecto | Llama 3.3 70B | Llama 3.1 8B |
|---------|---------------|--------------|
| **Preco Input** | $0.59/1M tokens | $0.05/1M tokens |
| **Preco Output** | $0.79/1M tokens | $0.08/1M tokens |
| **Context Window** | 128K tokens | 128K tokens |
| **Velocidade** | 276-1665 t/s (com spec. decoding) | 750+ t/s |
| **Latencia (TTFT)** | ~0.77s | ~0.3s |
| **Portugues BR** | Bom. Llama 3.3 70B entende bem PT-BR formal e coloquial. Giriass e regionalismos podem falhar ocasionalmente. | Razoavel. Modelo menor, mais erros em nuances do PT-BR. |
| **Free Tier** | Sim, rate-limited (~30 RPM) | Sim, rate-limited |
| **Melhor para** | Melhor custo-beneficio para alta velocidade. Ideal para chatbot que precisa de respostas instantaneas. | Prototipagem e testes. Custo quase zero. |
| **Limitacoes** | Rate limits no free tier. Nao e tao inteligente quanto GPT-4o ou Claude para tarefas complexas. | Qualidade inferior para portugues. Respostas menos nuancadas. |

**Destaque Groq:** Velocidade absurda (LPU). O usuario recebe resposta quase instantanea no WhatsApp. Preco muito competitivo.

---

### 2. Google Gemini 2.0 Flash / Gemini 2.5 Flash

| Aspecto | Gemini 2.0 Flash | Gemini 2.5 Flash |
|---------|-------------------|-------------------|
| **Preco Input** | $0.10/1M tokens | $0.30/1M tokens |
| **Preco Output** | $0.40/1M tokens | $2.50/1M tokens |
| **Context Window** | 1M tokens | 1M tokens |
| **Velocidade** | ~150-200 t/s | ~150-250 t/s |
| **Latencia (TTFT)** | ~0.5-1.0s | ~0.5-1.0s |
| **Portugues BR** | Muito bom. Google tem forte investimento em multilingual. Entende girias e regionalismos brasileiros. | Excelente. Modelo mais recente com melhor compreensao contextual. |
| **Free Tier** | 15 RPM, 1000 req/dia | 10 RPM, 250 req/dia |
| **Melhor para** | Melhor opcao para custo + qualidade. Free tier generoso para comecar. | Quando precisa de raciocinio mais complexo (planos alimentares elaborados). |
| **Limitacoes** | Menos "inteligente" que 2.5. | Output caro ($2.50/1M). Free tier mais restrito. |

**Destaque Gemini:** Free tier extremamente generoso. Context window de 1M tokens (util se quiser manter historico longo de conversas). Excelente portugues.

---

### 3. Claude Haiku 4.5 (claude-haiku-4-5)

| Aspecto | Detalhes |
|---------|----------|
| **Preco Input** | $1.00/1M tokens |
| **Preco Output** | $5.00/1M tokens |
| **Batch (50% off)** | $0.50 input / $2.50 output |
| **Context Window** | 200K tokens |
| **Velocidade** | ~105 t/s (Anthropic), ate 126 t/s (AWS) |
| **Latencia (TTFT)** | ~0.58-0.68s |
| **Portugues BR** | Excelente. Claude e reconhecido pela qualidade de texto em portugues, tom natural, empatico. Entende girias e contexto cultural brasileiro. |
| **Free Tier** | Nao tem free tier de API. Uso via console limitado. |
| **Melhor para** | Melhor qualidade de conversa. Tom empatico e profissional ideal para saude/nutricao. Segue instrucoes com precisao. |
| **Limitacoes** | Mais caro que alternativas. Sem free tier. Rate limits: ~50 RPM no tier basico. |

**Destaque Claude:** Melhor qualidade de texto e seguimento de instrucoes. Tom natural e empatico, perfeito para area de saude. Mas e o mais caro da lista.

---

### 4. OpenAI GPT-4o-mini

| Aspecto | Detalhes |
|---------|----------|
| **Preco Input** | $0.15/1M tokens |
| **Preco Output** | $0.60/1M tokens |
| **Context Window** | 128K tokens |
| **Max Output** | 16K tokens |
| **Velocidade** | ~39-85 t/s |
| **Latencia (TTFT)** | ~0.5-1.0s |
| **Portugues BR** | Muito bom. GPT-4o-mini entende bem PT-BR, incluindo girias e expressoes coloquiais. Treinado com grande volume de dados em portugues. |
| **Free Tier** | $5 em creditos para novos usuarios (dura bastante com este modelo). |
| **Melhor para** | Equilibrio solido entre qualidade, preco e ecossistema. Ampla documentacao e bibliotecas. |
| **Limitacoes** | Velocidade mediana. Rate limits no tier gratuito (3 RPM). Content filtering pode ser restritivo. |

**Destaque GPT-4o-mini:** Ecossistema maduro, facil integracao. Preco competitivo. Bom portugues. E a opcao "segura" e bem documentada.

---

### 5. DeepSeek V3 / R1

| Aspecto | DeepSeek V3 | DeepSeek R1 |
|---------|-------------|-------------|
| **Preco Input** | $0.14/1M tokens | $0.55/1M tokens |
| **Preco Output** | $0.28/1M tokens | $2.19/1M tokens |
| **Context Window** | 128K tokens | 128K tokens |
| **Velocidade** | ~37 t/s (API propria) | ~33 t/s (API propria) |
| **Latencia (TTFT)** | ~1.8-7.0s | ~1.8-7.0s |
| **Portugues BR** | Bom, mas inferior a GPT/Claude/Gemini. Treinado com foco em chines/ingles. PT-BR funcional mas menos natural. | Mesmo que V3 para portugues. |
| **Free Tier** | 5M tokens gratis (30 dias). Desconto off-peak ate 75%. | Incluido nos 5M tokens. |
| **Melhor para** | Custo mais baixo entre APIs pagas. Bom para alto volume com qualidade aceitavel. | Raciocinio complexo (calculos nutricionais, planos detalhados). |
| **Limitacoes** | **LENTO** na API propria. Servidor na China = latencia alta do Brasil. Instabilidade historica de servico. Portugues menos natural. | Muito lento. Custo de output alto. |

**Destaque DeepSeek:** Mais barato entre as APIs, mas a latencia alta e o portugues inferior sao problemas reais para um chatbot de WhatsApp.

---

### 6. Ollama Local (Llama 3.3, Mistral, Qwen)

| Aspecto | Detalhes |
|---------|----------|
| **Preco por token** | $0.00 (custo = hardware + eletricidade) |
| **Hardware minimo (8B)** | GPU com 8-12GB VRAM (RTX 3060 ~R$1.600 usado) |
| **Hardware minimo (70B)** | GPU com 48GB+ VRAM (RTX 4090 ~R$12.000+) ou 2x RTX 3090 |
| **Velocidade (8B)** | 40+ t/s em RTX 3060 |
| **Velocidade (70B)** | 10-20 t/s em RTX 4090 |
| **Portugues BR** | Varia. Llama 3.3 70B: bom. Qwen 2.5 72B: bom. Mistral 7B: razoavel. Modelos 8B: limitados em PT-BR. |
| **Context Window** | Configuravel (geralmente 8K-32K, modelos suportam ate 128K) |
| **Free Tier** | Totalmente gratuito (open source) |
| **Melhor para** | Privacidade total dos dados (LGPD). Sem custo por token. Controle total. |
| **Limitacoes** | Requer servidor dedicado. Manutencao tecnica. Modelos menores (8B) tem PT-BR fraco. Escalabilidade limitada. Sem uptime garantido. |

**Destaque Ollama:** Zero custo por token e privacidade total (dados nunca saem do servidor). Ideal se ja tem infraestrutura ou quer investir em hardware. Ruim para quem nao tem equipe tecnica.

---

## Estimativa de Custo Mensal

### Cenario: Clinica pequena de nutricao
- **500 conversas/mes**
- **10 mensagens por conversa** (5 do usuario + 5 do bot)
- **200 tokens por mensagem** (media)
- **Total: 500 x 10 x 200 = 1.000.000 tokens/mes (1M)**
- Divisao estimada: **500K input + 500K output**

| Modelo | Custo Input | Custo Output | **Total USD/mes** | **Total BRL/mes** |
|--------|------------|-------------|-------------------|-------------------|
| **Groq Llama 3.1 8B** | $0.025 | $0.040 | **$0.065** | **R$0.35** |
| **Groq Llama 3.3 70B** | $0.295 | $0.395 | **$0.690** | **R$3.66** |
| **Gemini 2.0 Flash** | $0.050 | $0.200 | **$0.250** | **R$1.33** |
| **Gemini 2.5 Flash** | $0.150 | $1.250 | **$1.400** | **R$7.43** |
| **DeepSeek V3** | $0.070 | $0.140 | **$0.210** | **R$1.12** |
| **GPT-4o-mini** | $0.075 | $0.300 | **$0.375** | **R$1.99** |
| **Claude Haiku 4.5** | $0.500 | $2.500 | **$3.000** | **R$15.93** |
| **DeepSeek R1** | $0.275 | $1.095 | **$1.370** | **R$7.28** |
| **Ollama Local** | $0.00 | $0.00 | **$0.00** | **~R$30-50/mes eletricidade** |

> **Nota:** Com system prompts, historico de conversa e contexto, o consumo real pode ser 3-5x maior. Uma estimativa mais realista seria **3-5M tokens/mes**, multiplicando os valores acima por 3-5x.

### Estimativa Realista (3M tokens/mes, com contexto)

| Modelo | **Total USD/mes** | **Total BRL/mes** |
|--------|-------------------|-------------------|
| **Groq Llama 3.1 8B** | $0.20 | R$1.06 |
| **Groq Llama 3.3 70B** | $2.07 | R$10.99 |
| **Gemini 2.0 Flash** | $0.75 | R$3.98 |
| **Gemini 2.5 Flash** | $4.20 | R$22.30 |
| **DeepSeek V3** | $0.63 | R$3.35 |
| **GPT-4o-mini** | $1.13 | R$6.00 |
| **Claude Haiku 4.5** | $9.00 | R$47.79 |
| **Ollama Local** | $0.00 | ~R$30-50 eletricidade |

---

## Ranking de Qualidade em Portugues Brasileiro

1. **Claude Haiku 4.5** - Melhor tom, empatia, naturalidade. Excelente para saude.
2. **Gemini 2.5 Flash** - Muito bom. Google investe pesado em multilingual.
3. **GPT-4o-mini** - Muito bom. Grande volume de dados de treino em PT-BR.
4. **Gemini 2.0 Flash** - Bom, levemente inferior ao 2.5.
5. **Groq Llama 3.3 70B** - Bom, mas pode errar em nuances regionais.
6. **DeepSeek V3** - Funcional, mas menos natural. Foco em chines/ingles.
7. **Groq Llama 3.1 8B** - Razoavel. Modelo pequeno demais para PT-BR de qualidade.
8. **Ollama (Mistral 7B)** - Fraco em PT-BR. Melhor usar Llama 3.3 ou Qwen localmente.

---

## Ranking de Velocidade (Experiencia no WhatsApp)

1. **Groq Llama 3.1 8B** - 750+ t/s (resposta quase instantanea)
2. **Groq Llama 3.3 70B** - 276-1665 t/s (com speculative decoding)
3. **Gemini 2.0/2.5 Flash** - 150-250 t/s (rapido)
4. **Claude Haiku 4.5** - 105-126 t/s (bom)
5. **GPT-4o-mini** - 39-85 t/s (mediano)
6. **DeepSeek V3/R1** - 33-37 t/s na API propria (lento, pior do Brasil por latencia de rede)

---

## Recomendacao Final

### Para uma clinica de nutricao no Brasil, as melhores opcoes sao:

#### Opcao 1: **Gemini 2.0 Flash** (MELHOR CUSTO-BENEFICIO)
- Free tier generoso para comecar sem gastar nada
- ~R$1.33-4.00/mes no uso pago (baratissimo)
- Bom portugues brasileiro
- Rapido o suficiente para WhatsApp
- Context window de 1M tokens (otimo para manter historico)

#### Opcao 2: **GPT-4o-mini** (MAIS SEGURO/ESTAVEL)
- Ecossistema mais maduro e documentado
- ~R$2.00-6.00/mes
- Muito bom portugues
- Facil integracao com bibliotecas existentes
- Maior comunidade de suporte

#### Opcao 3: **Groq Llama 3.3 70B** (MAIS RAPIDO)
- Resposta instantanea (melhor UX no WhatsApp)
- ~R$3.66-11.00/mes
- Bom portugues
- Free tier para comecar
- Ideal se velocidade e prioridade

#### Opcao 4: **Claude Haiku 4.5** (MELHOR QUALIDADE)
- Melhor portugues e tom empatico
- ~R$15.93-48.00/mes (mais caro, mas ainda barato em termos absolutos)
- Ideal para area de saude pela qualidade das respostas
- Considere se qualidade > custo

#### NAO recomendado para este caso:
- **DeepSeek**: Latencia alta do Brasil, portugues inferior, instabilidade de servico
- **Ollama Local**: Complexidade de manutencao desproporcional para uma clinica pequena
- **Llama 3.1 8B**: Portugues insuficiente para atendimento profissional

---

## Observacoes Importantes

1. **LGPD**: Se dados de saude dos pacientes passam pelo chatbot, considere as implicacoes de enviar dados para APIs externas. Ollama local ou APIs com DPA (Data Processing Agreement) sao mais seguros.

2. **Escalabilidade**: Com 500 conversas/mes, QUALQUER opcao acima custa menos de R$50/mes. O custo de API e irrelevante comparado ao custo do desenvolvedor.

3. **System Prompt**: Um bom system prompt de nutricionista (com tom, limites eticos, disclaimer de "nao substitui consulta") e mais importante que a escolha do modelo.

4. **Fallback**: Considere usar Gemini 2.0 Flash como modelo principal e Claude Haiku como fallback para perguntas complexas.

---

*Documento gerado em Março 2026. Precos e especificacoes podem mudar. Consulte as paginas oficiais para valores atualizados.*
