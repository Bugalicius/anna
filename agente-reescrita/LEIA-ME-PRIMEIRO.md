# Reescrita do Agente Ana — Pacote Completo

## Por onde começar

1. Leia `ordem_execucao.md` primeiro — passo a passo de tudo
2. Depois siga as fases na ordem usando os arquivos da pasta `prompts/`
3. Os YAMLs em `config/` são a fonte de verdade — não edita à mão

## Estrutura

```
agente-reescrita/
├── LEIA-ME-PRIMEIRO.md          ← você está aqui
├── ordem_execucao.md            ← guia de execução passo a passo
│
├── config/                       ← copiar pro repo do agente
│   ├── global.yaml
│   └── fluxos/
│       ├── fluxo_1_agendamento.yaml
│       ├── fluxo_2_3_remarcacao_cancelamento.yaml
│       ├── fluxo_4_confirmacao_presenca.yaml
│       ├── fluxo_5_recebimento_imagem.yaml
│       ├── fluxo_6_7_duvidas_casos_especiais.yaml
│       ├── fluxo_8_comandos_internos.yaml
│       ├── fluxo_9_midias_nao_textuais.yaml
│       └── fluxo_10_fora_de_contexto.yaml
│
└── prompts/                      ← um por fase, copia e cola no Claude Code
    ├── prompt_mestre_fase_0.md  ← começa aqui
    ├── prompt_fase_1_nucleo.md
    ├── prompt_fase_2_tools.md
    ├── prompts_fases_3_a_9.md
    └── testes_e2e.md
```

## Fluxo de trabalho

1. Lê `ordem_execucao.md` completo
2. Faz a preparação (copia YAMLs pro repo, cria branch)
3. Executa fase por fase, na ordem
4. Cada fase tem checklist de aceitação — só avança quando passar
5. Cronograma: ~7-8 dias úteis

Boa sorte! 💪
