"""Schemas Pydantic para configurações YAML e contratos do pipeline v2."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValoresPlano(StrictModel):
    pix_presencial: float
    pix_online: float
    cartao_presencial: float
    cartao_online: float


class Plano(StrictModel):
    nome_publico: str
    descricao: str
    consultas: int
    duracao_dias: int
    valores: ValoresPlano
    upsell_para: str | None = None


class BotaoInterativo(StrictModel):
    id: str
    label: str


class Situacao(StrictModel):
    trigger: str
    resposta: str | None = None
    resposta_template: str | None = None
    resposta_paciente: str | None = None
    resposta_marcador: str | None = None
    botoes_interativos: list[BotaoInterativo] = Field(default_factory=list)
    proximo_estado: str | None = None
    action: str | None = None
    acao: str | None = None
    acao_paralela: str | None = None
    salva_no_estado: dict[str, Any] = Field(default_factory=dict)
    permite_improviso: bool = False
    instrucao_para_llm: str | None = None
    usar_kb_objections: str | None = None
    max_tentativas: int | None = None
    ao_atingir_max: str | None = None
    agendar_remarketing: dict[str, Any] | None = None
    regras_escalacao: dict[str, Any] | None = None
    validacoes: dict[str, Any] | list[Any] | None = None
    situacao_secundaria: str | dict[str, Any] | None = None
    mensagem_breno_template: str | None = None
    mensagem_para_paciente_real_template: str | None = None
    notas: str | None = None

    def texto_resposta(self) -> str | None:
        return self.resposta or self.resposta_template or self.resposta_paciente

    @property
    def acao_declarada(self) -> str | None:
        return self.action or self.acao


class OnEnter(StrictModel):
    mensagem: str | None = None
    mensagem_template: str | None = None
    resposta: str | None = None
    resposta_paciente: str | None = None
    resposta_template: str | None = None
    mensagem_breno_template: str | None = None
    mensagem_notificacao_template: str | None = None
    proximo_estado: str | None = None
    proximo_estado_dinamico: str | bool | dict[str, Any] | None = None
    condicao: str | None = None
    acao: str | None = None
    acao_interna: str | None = None
    acao_interna_obrigatoria: str | None = None
    acao_se_pagamento_ja_feito: str | dict[str, Any] | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    saida: dict[str, Any] = Field(default_factory=dict)
    salva_no_estado: dict[str, Any] = Field(default_factory=dict)
    botoes_interativos: list[BotaoInterativo] = Field(default_factory=list)
    acoes: list[Any] | dict[str, Any] = Field(default_factory=list)
    acoes_em_sequencia: list[Any] | dict[str, Any] = Field(default_factory=list)
    condicional_modalidade: dict[str, Any] = Field(default_factory=dict)
    regras_upsell: dict[str, Any] = Field(default_factory=dict)
    decisao_dinamica: dict[str, Any] = Field(default_factory=dict)
    calcular: dict[str, Any] = Field(default_factory=dict)
    apos_busca: dict[str, Any] | str = Field(default_factory=dict)
    apos_consulta: dict[str, Any] | str = Field(default_factory=dict)
    apos_analise: dict[str, Any] | str = Field(default_factory=dict)
    apos_transcricao: dict[str, Any] = Field(default_factory=dict)
    apos_geracao: str | dict[str, Any] | None = None
    apos_sucesso: dict[str, Any] = Field(default_factory=dict)
    apos_falha: dict[str, Any] = Field(default_factory=dict)
    verificacao_inicial: dict[str, Any] | str = Field(default_factory=dict)
    caso_a_gestante_sem_pergunta_clinica: dict[str, Any] = Field(default_factory=dict)
    caso_b_gestante_com_pergunta_clinica: dict[str, Any] = Field(default_factory=dict)

    def texto_mensagem(self) -> str | None:
        return self.mensagem or self.mensagem_template or self.resposta or self.resposta_template


class Estado(StrictModel):
    descricao: str = ""
    on_enter: OnEnter | None = None
    on_enter_via_scheduler: OnEnter | None = None
    intents_aceitas: list[str] = Field(default_factory=list)
    situacoes: dict[str, Situacao] = Field(default_factory=dict)
    pre_check: dict[str, Any] | None = None
    triggers_classificacao: dict[str, Any] | list[Any] | None = None


class Fluxo(StrictModel):
    fluxo_id: str
    fluxo_nome: str = ""
    estado_inicial: str | None = None
    estado_final: str | None = None
    estados: dict[str, Estado]
    campos_coletados: dict[str, Any] = Field(default_factory=dict)
    regras_inviolaveis: dict[str, Any] = Field(default_factory=dict)
    tools: dict[str, Any] = Field(default_factory=dict)
    remarketing: dict[str, Any] = Field(default_factory=dict)
    comandos_suportados: dict[str, Any] = Field(default_factory=dict)
    numeros_autorizados: list[dict[str, Any]] = Field(default_factory=list)
    jobs: dict[str, Any] = Field(default_factory=dict)


class GlobalConfig(StrictModel):
    identidade: dict[str, Any]
    numeros: dict[str, Any]
    clinica: dict[str, Any] = Field(default_factory=dict)
    planos: dict[str, Plano]
    pagamento: dict[str, Any] = Field(default_factory=dict)
    grade_horarios: dict[str, Any] = Field(default_factory=dict)
    regras_agendamento: dict[str, Any] = Field(default_factory=dict)
    remarcacao: dict[str, Any] = Field(default_factory=dict)
    cancelamento: dict[str, Any] = Field(default_factory=dict)
    restricoes: dict[str, Any] = Field(default_factory=dict)
    duvidas_clinicas: dict[str, Any] = Field(default_factory=dict)
    escalacao: dict[str, Any] = Field(default_factory=dict)
    fora_contexto: dict[str, Any] = Field(default_factory=dict)
    programa_indicacao: dict[str, Any] = Field(default_factory=dict)
    regras_inviolaveis_globais: dict[str, Any] = Field(default_factory=dict)
    tom_estilo: dict[str, Any] = Field(default_factory=dict)


class Interpretacao(StrictModel):
    intent: str
    confidence: float = 1.0
    entities: dict[str, Any] = Field(default_factory=dict)
    botao_id: str | None = None
    message_type: str = "text"
    patient_message_type: str | None = None
    validacoes: dict[str, Any] = Field(default_factory=dict)
    texto_original: str = ""


class TipoAcao(str, Enum):
    enviar_mensagem = "enviar_mensagem"
    executar_tool = "executar_tool"
    improviso_llm = "improviso_llm"
    escalar = "escalar"
    redirecionar_fluxo = "redirecionar_fluxo"
    concluir = "concluir"
    nenhuma = "nenhuma"


class Mensagem(StrictModel):
    tipo: str = "texto"
    conteudo: str = ""
    botoes: list[BotaoInterativo] = Field(default_factory=list)
    arquivo: str | None = None
    delay_segundos: int = 0
    numero_contato: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AcaoAutorizada(StrictModel):
    tipo: TipoAcao
    proximo_estado: str | None = None
    mensagens: list[Mensagem] = Field(default_factory=list)
    mensagens_a_enviar: list[Mensagem] = Field(default_factory=list)
    tool_a_executar: str | None = None
    tool_input: dict[str, Any] = Field(default_factory=dict)
    permite_improviso: bool = False
    instrucao_improviso: str | None = None
    salvar_no_estado: dict[str, Any] = Field(default_factory=dict)
    dados: dict[str, Any] = Field(default_factory=dict)
    situacao_nome: str | None = None


class RuleResult(StrictModel):
    passou: bool
    regra: str = ""
    motivo: str | None = None
    severidade: str = "BLOCKING"


class ResultadoTurno(StrictModel):
    sucesso: bool
    mensagens_enviadas: list[Mensagem] = Field(default_factory=list)
    novo_estado: str | None = None
    fluxo_id: str | None = None
    regra_violada: str | None = None
    erro: str | None = None
    duracao_ms: int = 0
