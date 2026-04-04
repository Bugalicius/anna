# Instruções para Claude Code — Projeto Agente Ana

## Comportamento ao iniciar sessão

Ao iniciar qualquer sessão neste projeto, leia imediatamente o arquivo `PROGRESS.md` na raiz do projeto e continue o trabalho de onde parou — sem precisar de instrução adicional do usuário.

Se o usuário digitar apenas "continue" ou "pode continuar" ou similar, isso significa: retomar o `PROGRESS.md` e executar a próxima tarefa pendente.

## Sobre o projeto

Agente WhatsApp "Ana" para a nutricionista Thaynara Teixeira. Backend FastAPI com arquitetura multi-agentes. Documentação completa em `docs/superpowers/` e no arquivo `PROGRESS.md`.

## Regras importantes

- Nunca expor o número interno de escalação (31 99205-9211) para pacientes
- Nunca oferecer a modalidade "Formulário" proativamente
- LLM principal: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)
- Todos os novos módulos devem ter testes em `tests/`
- Rodar `python -m pytest tests/ -q` antes de cada commit
