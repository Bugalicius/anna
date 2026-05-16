"""
Lookup de pacientes na base CSV importada no Redis.

Chave: agente:paciente:{telefone} -> JSON com nome, primeiro_nome, email, sexo
Suporta variacao do 9o digito (com/sem).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _variantes(phone: str) -> set[str]:
    digits = re.sub(r"\D", "", phone)
    if not digits.startswith("55"):
        digits = "55" + digits

    variants: set[str] = {digits}

    if len(digits) == 12:
        ddd, numero = digits[2:4], digits[4:]
        variants.add(f"55{ddd}9{numero}")

    if len(digits) == 13:
        ddd, numero = digits[2:4], digits[4:]
        if numero.startswith("9"):
            variants.add(f"55{ddd}{numero[1:]}")

    return variants


async def identificar_paciente(phone: str, redis: Any) -> dict[str, Any] | None:
    """
    Busca paciente pelo telefone no Redis (base CSV Dietbox).
    Retorna dict {nome, primeiro_nome, email, sexo, telefone} ou None.
    Fallback seguro: retorna None se Redis indisponivel.
    """
    if redis is None:
        return None
    try:
        for candidato in _variantes(phone):
            raw = await redis.get(f"agente:paciente:{candidato}")
            if raw:
                return json.loads(raw)
    except Exception as exc:
        logger.warning("Falha ao buscar paciente no Redis (phone=%s): %s", phone[-4:], exc)
    return None
