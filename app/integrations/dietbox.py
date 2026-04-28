"""
Integrations — Dietbox.
Re-exporta as funções do worker existente como API pública da camada de integração.
"""
from app.agents.dietbox_worker import (
    alterar_agendamento,
    agendar_consulta,
    buscar_paciente_por_identificador,
    buscar_paciente_por_telefone,
    cancelar_agendamento,
    confirmar_pagamento,
    consultar_agendamento_ativo,
    consultar_slots_disponiveis,
    processar_agendamento,
    verificar_lancamento_financeiro,
)

__all__ = [
    "alterar_agendamento",
    "agendar_consulta",
    "buscar_paciente_por_identificador",
    "buscar_paciente_por_telefone",
    "cancelar_agendamento",
    "confirmar_pagamento",
    "consultar_agendamento_ativo",
    "consultar_slots_disponiveis",
    "processar_agendamento",
    "verificar_lancamento_financeiro",
]
