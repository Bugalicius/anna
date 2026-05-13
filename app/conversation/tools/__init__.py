"""
Tools — ações concretas com integrações externas.

Padrão:
    - Cada tool é uma função async
    - Input/output via Pydantic
    - Sempre retorna ToolResult(sucesso, dados, erro)
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sucesso: bool
    dados: dict[str, Any] = Field(default_factory=dict)
    erro: str | None = None

