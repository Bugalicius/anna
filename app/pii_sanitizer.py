"""
Sanitizador de PII para compliance LGPD.

Mascara CPF, telefone brasileiro e e-mail em mensagens do paciente
antes de enviar historico para a API da Anthropic.
Detecta e trunca tentativas de prompt injection.

Uso: sanitize_historico(historico) retorna copia com PII mascarado
     em mensagens role=user. Mensagens role=assistant nao sao alteradas.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

# CPF formatado: 123.456.789-09 (formato canonico com pontos e traco)
_CPF_FORMATTED_RE = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')

# Telefone formatado: (31) 99205-9211 ou 31 9920-5921 (com espaco/parens)
_PHONE_FORMATTED_RE = re.compile(r'\(?\b\d{2}\)?\s\d{4,5}-?\d{4}\b')

# Telefone sem formatacao precedido por contexto de telefone
# Ex: "meu numero 31999059211"
_PHONE_CONTEXT_RE = re.compile(
    r'(?i)(?:numero|telefone|fone|tel|celular|whatsapp|contato)\s+(\d{10,11})\b'
)

# CPF sem formatacao (11 digitos) — captura numeros nao cobertos por contexto de telefone
# Aplicado apos _PHONE_CONTEXT_RE para evitar sobreposicao
_CPF_BARE_RE = re.compile(r'\b\d{11}\b')

# Alias para compatibilidade — padrao geral de CPF (com ou sem pontuacao)
_CPF_RE = _CPF_BARE_RE

# Alias para compatibilidade — padrao geral de telefone BR
_PHONE_BR_RE = _PHONE_FORMATTED_RE

# Email
_EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')

# Prompt injection patterns
_INJECTION_RE = re.compile(
    r'ignore\s+(all\s+)?previous|forget\s+(your\s+)?instructions?|'
    r'\n\n(human|assistant|system|user)\s*:',
    flags=re.IGNORECASE,
)


def sanitize_message(text: str) -> str:
    """
    Mascara PII e detecta prompt injection em texto do paciente.

    Chamado antes de adicionar mensagem ao historico para LLM.
    Nao mascara nomes (necessarios para personalizacao da Ana).

    Ordem de aplicacao:
    1. CPF formatado (123.456.789-09) — nao ambiguo
    2. Telefone formatado (com espacos/parens) — nao ambiguo
    3. Telefone sem formatacao precedido por palavra-chave (numero, cel, etc.)
    4. CPF sem formatacao (11 digitos restantes, default para CPF)
    5. Email
    6. Deteccao de prompt injection
    """
    # 1. CPF com pontuacao canonical — inequivoco
    text = _CPF_FORMATTED_RE.sub('[CPF]', text)

    # 2. Telefone formatado (com espaco entre DDD e numero, ou com parens)
    text = _PHONE_FORMATTED_RE.sub('[TELEFONE]', text)

    # 3. Telefone sem formatacao com contexto de telefone
    # Substitui o grupo capturado (apenas os digitos) dentro da frase
    text = _PHONE_CONTEXT_RE.sub(
        lambda m: m.group(0).replace(m.group(1), '[TELEFONE]'),
        text,
    )

    # 4. CPF sem pontuacao (11 digitos que sobraram — default: CPF)
    text = _CPF_BARE_RE.sub('[CPF]', text)

    # 5. Email
    text = _EMAIL_RE.sub('[EMAIL]', text)

    # 6. Prompt injection
    if _INJECTION_RE.search(text):
        logger.warning("Possivel prompt injection detectado, texto truncado.")
        text = text[:200] + ' [CONTEUDO FILTRADO]'

    return text


def sanitize_historico(historico: list[dict]) -> list[dict]:
    """
    Retorna COPIA do historico com PII mascarado em mensagens do usuario.

    Mensagens do assistente (role=assistant) nao sao alteradas.
    O historico original NAO e mutado.
    """
    result = []
    for msg in historico:
        if msg.get("role") == "user":
            result.append({"role": "user", "content": sanitize_message(msg["content"])})
        else:
            result.append(dict(msg))  # copia shallow
    return result
