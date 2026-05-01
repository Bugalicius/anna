# Codigo legado

Arquivos movidos para fora do pacote `app` apos verificacao com `rg`.

Eles nao sao importados pelo fluxo atual de producao:

```text
app.webhook -> app.router -> app.conversation.engine -> app.tools/*
```

Mapeamento:

- `app_scheduling.py`: versao antiga de `app/tools/scheduling.py`.
- `app_state.py`: versao antiga de `app/conversation/state.py`.
- `app_tools_escalation.py`: wrapper antigo sem uso produtivo atual.
- `responder.py`: responder historico fora do pacote atual.

Se algum comportamento precisar voltar, migre para os modulos atuais em vez de
reativar estes arquivos diretamente.
