# Testes legados

Estes testes cobrem a arquitetura antiga baseada em `app.agents.atendimento`,
`app.agents.retencao` e `app.state_manager`.

Eles foram movidos para fora de `tests/` porque esses modulos nao fazem parte do
caminho atual de producao. O fluxo atual passa por:

```text
app.webhook -> app.router -> app.conversation.engine -> app.conversation.state
```

Ao reutilizar algum cenario daqui, migre o teste para `ConversationEngine` antes
de coloca-lo novamente na suite principal.
