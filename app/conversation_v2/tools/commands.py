from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.conversation_v2.tools import ToolResult

logger = logging.getLogger(__name__)

_COMANDOS_SUPORTADOS = {
    "consultar_status_paciente",
    "perguntar_paciente_troca_horario",
    "cancelar_consulta",
    "remarcar_consulta",
    "responder_escalacao",
    "enviar_mensagem_para_paciente",
    "nao_reconhecido",
}


class InterpretarComandoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texto: str
    remetente: str


class ComandoInterpretado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comando_identificado: str
    parametros_extraidos: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0


async def interpretar_comando(texto: str, remetente: str) -> ToolResult:
    """
    Identifica comando interno via Gemini e extrai parâmetros estruturados.
    """
    from app import llm_client

    system = (
        "Classifique o comando interno e extraia parâmetros.\n"
        "Responda SOMENTE JSON válido com:\n"
        "{"
        '"comando_identificado":"consultar_status_paciente|perguntar_paciente_troca_horario|cancelar_consulta|remarcar_consulta|responder_escalacao|enviar_mensagem_para_paciente|nao_reconhecido",'
        '"parametros_extraidos":{},'
        '"confidence":0.0'
        "}"
    )
    user = f"Remetente: {remetente}\nMensagem: {texto}"
    try:
        raw = await llm_client.complete_text_async(system=system, user=user, max_tokens=300, temperature=0.0)
        parsed = json.loads(llm_client.strip_json_fences(raw))
        comando = str(parsed.get("comando_identificado", "nao_reconhecido"))
        if comando not in _COMANDOS_SUPORTADOS:
            comando = "nao_reconhecido"
        resultado = ComandoInterpretado(
            comando_identificado=comando,
            parametros_extraidos=parsed.get("parametros_extraidos") or {},
            confidence=float(parsed.get("confidence") or 0.0),
        )
        return ToolResult(sucesso=True, dados=resultado.model_dump())
    except Exception as exc:
        logger.warning("Falha ao interpretar comando interno: %s", exc)
        return ToolResult(
            sucesso=True,
            dados=ComandoInterpretado(comando_identificado="nao_reconhecido").model_dump(),
        )

