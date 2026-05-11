"""
Registry — registro central de tools disponíveis para o orchestrator.
"""
from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.conversation_v2.tools import ToolResult
from app.conversation_v2.tools import commands, media, notifications, patients, payments, scheduling

TOOLS = {
    "consultar_slots": scheduling.consultar_slots,
    "remarcar_dietbox": scheduling.remarcar_dietbox,
    "cancelar_dietbox": scheduling.cancelar_dietbox,
    "detectar_tipo_remarcacao": patients.detectar_tipo_remarcacao,
    "gerar_link_pagamento": payments.gerar_link_pagamento,
    "analisar_comprovante": payments.analisar_comprovante,
    "encaminhar_comprovante_thaynara": payments.encaminhar_comprovante_thaynara,
    "transcrever_audio": media.transcrever_audio,
    "classificar_imagem": media.classificar_imagem,
    "notificar_breno": notifications.notificar_breno,
    "notificar_thaynara": notifications.notificar_thaynara,
    "escalar_breno_silencioso": notifications.escalar_breno_silencioso,
    "interpretar_comando": commands.interpretar_comando,
}

TOOL_INPUT_MODELS: dict[str, type[BaseModel]] = {
    "consultar_slots": scheduling.ConsultarSlotsInput,
    "remarcar_dietbox": scheduling.RemarcarDietboxInput,
    "cancelar_dietbox": scheduling.CancelarDietboxInput,
    "gerar_link_pagamento": payments.GerarLinkPagamentoInput,
    "analisar_comprovante": payments.AnalisarComprovanteInput,
    "encaminhar_comprovante_thaynara": payments.EncaminharComprovanteInput,
    "transcrever_audio": media.TranscreverAudioInput,
    "classificar_imagem": media.ClassificarImagemInput,
    "interpretar_comando": commands.InterpretarComandoInput,
}


class _DetectarTipoRemarcacaoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telefone: str
    identificador: str | None = None


class _NotificarBrenoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mensagem: str


class _NotificarThaynaraInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mensagem: str
    anexo_imagem: bytes | None = None


class _EscalarBrenoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contexto: dict[str, Any]


TOOL_INPUT_MODELS["detectar_tipo_remarcacao"] = _DetectarTipoRemarcacaoInput
TOOL_INPUT_MODELS["notificar_breno"] = _NotificarBrenoInput
TOOL_INPUT_MODELS["notificar_thaynara"] = _NotificarThaynaraInput
TOOL_INPUT_MODELS["escalar_breno_silencioso"] = _EscalarBrenoInput


async def call_tool(name: str, input: dict[str, Any]) -> ToolResult:
    """Chama tool pelo nome com validação Pydantic de entrada."""
    func = TOOLS.get(name)
    if func is None:
        return ToolResult(sucesso=False, erro=f"Tool '{name}' não registrada")

    model_cls = TOOL_INPUT_MODELS.get(name)
    try:
        if model_cls is not None:
            payload = model_cls(**(input or {}))
            sig = inspect.signature(func)
            params = list(sig.parameters.values())
            if len(params) == 1 and params[0].name == "input":
                result = await func(payload)
            else:
                kwargs: dict[str, Any] = {}
                for param in params:
                    if hasattr(payload, param.name):
                        kwargs[param.name] = getattr(payload, param.name)
                result = await func(**kwargs)
        else:
            result = await func(**(input or {}))
    except Exception as exc:
        return ToolResult(sucesso=False, erro=f"Erro ao executar tool '{name}': {exc}")

    if isinstance(result, ToolResult):
        return result
    if isinstance(result, dict):
        return ToolResult(sucesso=bool(result.get("sucesso", True)), dados=result)
    return ToolResult(sucesso=True, dados={"resultado": result})
