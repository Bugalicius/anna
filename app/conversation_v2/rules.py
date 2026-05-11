"""
rules.py — Funções puras para regras invioláveis globais (R1-R16).

Todas as funções são puras (sem efeitos colaterais).
Cada função retorna RuleResult(passou=True/False, regra=..., motivo=...).

API principal:
    validar_resposta_completa(texto, contexto) -> list[RuleResult]
    validar_acao_pre_envio(acao, contexto)     -> list[RuleResult]
"""
from __future__ import annotations

import re
from typing import Any

from app.conversation_v2.models import AcaoAutorizada, RuleResult

# ─────────────────────────────────────────────────────────────────────────────
# Constantes (espelham o global.yaml — a verdade vem do YAML, aqui só defaults)
# ─────────────────────────────────────────────────────────────────────────────

_PALAVRAS_BRENO = [
    "Breno",
    "31 99205-9211",
    "31992059211",
    "5531992059211",
    "(31) 99205-9211",
]

_NOMES_GENERICOS = [
    "consulta", "agendar", "marcar", "retorno", "plano", "pagamento",
    "horário", "horario", "manhã", "manha", "tarde", "noite",
    "presencial", "online", "pix", "cartão", "cartao",
    "oi", "olá", "ola", "sim", "não", "nao", "ok",
    "tudo", "bem", "quero", "preciso", "gostaria",
]

_HORARIOS_VALIDOS = {
    "segunda": ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],
    "terca":   ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],
    "quarta":  ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],
    "quinta":  ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],
    "sexta":   ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00"],  # sem noite
}


def _ok(regra: str) -> RuleResult:
    return RuleResult(passou=True, regra=regra)


def _bloquear(regra: str, motivo: str, severidade: str = "BLOCKING") -> RuleResult:
    return RuleResult(passou=False, regra=regra, motivo=motivo, severidade=severidade)


# ─────────────────────────────────────────────────────────────────────────────
# R1 — R16
# ─────────────────────────────────────────────────────────────────────────────

def R1_nunca_expor_breno(texto: str) -> RuleResult:
    """Bloqueia se texto contém nome ou número do Breno."""
    regra = "R1_nunca_expor_breno"
    for palavra in _PALAVRAS_BRENO:
        if palavra.lower() in texto.lower():
            return _bloquear(regra, f"Texto contém referência proibida ao Breno: {palavra!r}")
    return _ok(regra)


def R2_contato_thaynara_apenas_paciente_existente(
    texto: str,
    paciente_status: str,
    fluxo_contexto: str = "",
) -> RuleResult:
    """Número da Thaynara só pode ser enviado para paciente já cadastrado."""
    regra = "R2_contato_thaynara_apenas_paciente_existente"
    numero_thaynara = "5531991394759"

    # Exceções declaradas no YAML
    excecoes = ("confirmacao_presenca", "confirmacao_final")
    if any(exc in fluxo_contexto for exc in excecoes):
        return _ok(regra)

    if numero_thaynara in texto and paciente_status not in ("existente", "retorno", "paciente"):
        return _bloquear(
            regra,
            "Contato da Thaynara só pode ser enviado a paciente já cadastrado.",
        )
    return _ok(regra)


def R3_nunca_inventar_valor(
    texto: str,
    valores_validos: list[float] | None = None,
) -> RuleResult:
    """Valores monetários devem corresponder à tabela de planos."""
    regra = "R3_nunca_inventar_valor"
    if not valores_validos:
        return _ok(regra)  # sem tabela de referência, não bloqueia

    # Extrai todos os valores monetários do texto (ex: R$ 690, R$690,00)
    matches = re.findall(r"R\$\s*([\d.,]+)", texto)
    for match in matches:
        valor_str = match.replace(".", "").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            continue
        # Permite diferença de ±1 centavo (arredondamento)
        if not any(abs(valor - v) < 0.02 for v in valores_validos):
            return _bloquear(
                regra,
                f"Valor R${valor} não consta na tabela de planos. "
                f"Válidos: {valores_validos}",
            )
    return _ok(regra)


def R4_nunca_oferecer_horario_fora_grade(
    dia_semana: str | None,
    horario: str | None,
) -> RuleResult:
    """Horário proposto deve estar na grade de atendimento."""
    regra = "R4_nunca_oferecer_horario_fora_grade"
    if not dia_semana or not horario:
        return _ok(regra)

    dia = dia_semana.lower().strip()
    if dia in ("sabado", "sábado", "domingo"):
        return _bloquear(regra, f"Não atende {dia_semana}.")

    horarios_dia = _HORARIOS_VALIDOS.get(dia)
    if horarios_dia is None:
        return _ok(regra)  # dia não mapeado — deixa passar

    # Normaliza horário para HH:MM
    horario_norm = horario.strip().replace("h", ":00").replace("H", ":00")
    if len(horario_norm) == 5 and ":" in horario_norm:
        pass  # já no formato correto
    elif re.match(r"^\d{1,2}$", horario_norm):
        horario_norm = f"{int(horario_norm):02d}:00"

    if horario_norm not in horarios_dia:
        return _bloquear(
            regra,
            f"Horário {horario} não está na grade para {dia_semana}. "
            f"Grade: {horarios_dia}",
        )
    return _ok(regra)


def R5_nunca_confirmar_sem_pagamento(pagamento_confirmado: bool) -> RuleResult:
    """Agendamento só confirma após pagamento confirmado."""
    regra = "R5_nunca_confirmar_sem_pagamento"
    if not pagamento_confirmado:
        return _bloquear(regra, "Tentativa de confirmar agendamento sem pagamento.")
    return _ok(regra)


def R6_nunca_aceitar_sinal_abaixo_50pct(
    valor_pago: float,
    valor_total: float,
) -> RuleResult:
    """PIX abaixo de 50% do valor total não aprova agendamento."""
    regra = "R6_nunca_aceitar_sinal_abaixo_50pct"
    if valor_total <= 0:
        return _ok(regra)
    sinal_minimo = valor_total * 0.50
    if valor_pago < sinal_minimo - 0.01:
        return _bloquear(
            regra,
            f"Sinal de R${valor_pago:.2f} é menor que o mínimo de "
            f"R${sinal_minimo:.2f} (50% de R${valor_total:.2f}).",
        )
    return _ok(regra)


def R7_nunca_dar_orientacao_clinica(texto: str) -> RuleResult:
    """LLM não deve responder dúvidas clínicas como nutricionista."""
    regra = "R7_nunca_dar_orientacao_clinica"
    # Padrões que indicam orientação clínica direta
    padroes = [
        r"\bpode comer\b",
        r"\bnão pode comer\b",
        r"\bcaloria[s]?\b.{0,20}\b(recomendo|indico|ideal)\b",
        r"\bdieta\b.{0,30}\b(para você|recomendo)\b",
        r"\bsuplemento\b.{0,20}\b(recomendo|tome|use)\b",
        r"\bconsuma\b.{0,20}\b(por dia|diariamente)\b",
    ]
    texto_lower = texto.lower()
    for padrao in padroes:
        if re.search(padrao, texto_lower):
            return _bloquear(
                regra,
                f"Resposta contém orientação clínica direta (padrão: {padrao!r}).",
            )
    return _ok(regra)


def R8_nunca_responder_b2b_multiplas_vezes(
    contador_b2b: int,
    janela_horas: int = 24,
) -> RuleResult:
    """Tentativas B2B recebem 1 resposta e depois são ignoradas."""
    regra = "R8_nunca_responder_b2b_multiplas_vezes"
    if contador_b2b > 1:
        return _bloquear(
            regra,
            f"Já respondido {contador_b2b}x. Ignorar por {janela_horas}h.",
            severidade="WARNING",
        )
    return _ok(regra)


def R9_desconto_dupla_nunca_proativo(
    texto: str,
    paciente_pediu: bool,
) -> RuleResult:
    """Desconto família/dupla só se paciente perguntar — nunca oferecer."""
    regra = "R9_desconto_dupla_nunca_proativo"
    if "10%" in texto and "famil" in texto.lower() and not paciente_pediu:
        return _bloquear(regra, "Desconto família não pode ser oferecido proativamente.")
    return _ok(regra)


def R10_validar_idade(data_nascimento_str: str | None) -> RuleResult:
    """Paciente deve ter 16 anos ou mais."""
    regra = "R10_validar_idade"
    if not data_nascimento_str:
        return _ok(regra)

    import datetime
    formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"]
    for fmt in formatos:
        try:
            nascimento = datetime.datetime.strptime(data_nascimento_str.strip(), fmt).date()
            hoje = datetime.date.today()
            idade = (hoje - nascimento).days // 365
            if idade < 16:
                return _bloquear(regra, f"Paciente tem {idade} anos (mínimo: 16).")
            return _ok(regra)
        except ValueError:
            continue
    return _ok(regra)  # formato não reconhecido — não bloqueia


def R11_recusar_gestante(
    texto: str,
    tem_duvida_clinica: bool = False,
) -> RuleResult:
    """Gestantes recebem recusa ou escalação silenciosa."""
    regra = "R11_recusar_gestante"
    termos_gestante = ["grávida", "gravida", "gestante", "gestação", "gestacao", "gravidez"]
    if any(t in texto.lower() for t in termos_gestante):
        if tem_duvida_clinica:
            return _bloquear(
                regra,
                "Gestante com dúvida clínica — escalar Breno silenciosamente.",
            )
        return _bloquear(regra, "Gestante — recusa direta necessária.")
    return _ok(regra)


def R12_validar_nome_nao_generico(nome: str) -> RuleResult:
    """Nome com palavras genéricas é rejeitado."""
    regra = "R12_validar_nome_nao_generico"
    nome_lower = nome.lower().strip()

    # Muito curto (1 char) ou apenas números
    if len(nome_lower) <= 1 or nome_lower.isdigit():
        return _bloquear(regra, f"Nome {nome!r} muito curto ou inválido.")

    for palavra in _NOMES_GENERICOS:
        if nome_lower == palavra.lower() or nome_lower == palavra.lower().strip():
            return _bloquear(regra, f"Nome genérico rejeitado: {nome!r}")

    return _ok(regra)


def R13_nunca_sobrescrever_nome_salvo(
    nome_no_estado: str | None,
    nome_novo: str | None,
    correcao_explicita: bool = False,
) -> RuleResult:
    """Nome já salvo não pode ser sobrescrito sem correção explícita."""
    regra = "R13_nunca_sobrescrever_nome_salvo"
    if nome_no_estado and nome_novo and not correcao_explicita:
        if nome_novo.lower() != nome_no_estado.lower():
            return _bloquear(
                regra,
                f"Tentativa de sobrescrever nome salvo {nome_no_estado!r} "
                f"com {nome_novo!r} sem correção explícita.",
            )
    return _ok(regra)


def R14_dietbox_cancelamento_via_put(acao_cancelamento: str) -> RuleResult:
    """Cancelamento/desmarcação sempre via PUT desmarcada=true, nunca DELETE."""
    regra = "R14_dietbox_cancelamento_via_put"
    if "DELETE" in acao_cancelamento.upper() or "delete" in acao_cancelamento:
        return _bloquear(
            regra,
            "Cancelamento via DELETE não permitido — usar PUT desmarcada=true.",
        )
    return _ok(regra)


def R15_nunca_informar_perda_valor(texto: str) -> RuleResult:
    """Nunca informar ao paciente que valor não será reembolsado."""
    regra = "R15_nunca_informar_perda_valor"
    padroes = [
        r"não (será|vai ser) reembolsado",
        r"sem reembolso",
        r"valor (perdido|perde|não retorna)",
        r"não devolvemos",
        r"não há reembolso",
    ]
    for padrao in padroes:
        if re.search(padrao, texto.lower()):
            return _bloquear(regra, f"Texto informa perda de valor ao paciente (padrão: {padrao!r}).")
    return _ok(regra)


def R16_comprovante_encaminhar_thaynara(
    comprovante_aprovado: bool,
    encaminhado: bool,
) -> RuleResult:
    """Todo comprovante aprovado deve ser encaminhado para Thaynara."""
    regra = "R16_comprovante_encaminhar_thaynara"
    if comprovante_aprovado and not encaminhado:
        return _bloquear(regra, "Comprovante aprovado mas não encaminhado para Thaynara.")
    return _ok(regra)


# ─────────────────────────────────────────────────────────────────────────────
# Validators de alto nível
# ─────────────────────────────────────────────────────────────────────────────

def validar_resposta_completa(
    texto: str,
    contexto: dict[str, Any],
) -> list[RuleResult]:
    """
    Roda todas as regras aplicáveis a uma mensagem de texto ao paciente.

    Contexto esperado (todos opcionais):
        paciente_status: str          — 'novo' | 'retorno' | 'existente'
        fluxo_contexto: str           — nome do fluxo atual
        valores_validos: list[float]  — valores do plano atual
        paciente_pediu_desconto: bool
    """
    resultados: list[RuleResult] = []

    # R1 — nunca expor Breno
    resultados.append(R1_nunca_expor_breno(texto))

    # R2 — contato Thaynara só pra paciente existente
    resultados.append(R2_contato_thaynara_apenas_paciente_existente(
        texto,
        paciente_status=contexto.get("paciente_status", ""),
        fluxo_contexto=contexto.get("fluxo_contexto", ""),
    ))

    # R3 — nunca inventar valor
    resultados.append(R3_nunca_inventar_valor(
        texto,
        valores_validos=contexto.get("valores_validos"),
    ))

    # R7 — nunca dar orientação clínica
    resultados.append(R7_nunca_dar_orientacao_clinica(texto))

    # R9 — desconto família nunca proativo
    resultados.append(R9_desconto_dupla_nunca_proativo(
        texto,
        paciente_pediu=contexto.get("paciente_pediu_desconto", False),
    ))

    # R15 — nunca informar perda de valor
    resultados.append(R15_nunca_informar_perda_valor(texto))

    return resultados


def validar_acao_pre_envio(
    acao: AcaoAutorizada,
    contexto: dict[str, Any],
) -> list[RuleResult]:
    """
    Valida ação operacional antes de executar tools ou enviar mensagens.

    Contexto esperado (todos opcionais):
        pagamento_confirmado: bool
        valor_pago: float
        valor_total: float
        acao_cancelamento: str
    """
    resultados: list[RuleResult] = []

    # R5 — nunca confirmar sem pagamento (se ação for de agendamento)
    if acao.tool_a_executar in ("tool_dietbox_agendar_consulta", "criar_agendamento"):
        resultados.append(R5_nunca_confirmar_sem_pagamento(
            pagamento_confirmado=contexto.get("pagamento_confirmado", False),
        ))

    # R6 — sinal mínimo 50%
    if contexto.get("valor_pago") and contexto.get("valor_total"):
        resultados.append(R6_nunca_aceitar_sinal_abaixo_50pct(
            valor_pago=float(contexto["valor_pago"]),
            valor_total=float(contexto["valor_total"]),
        ))

    # R14 — cancelamento via PUT
    if acao_str := contexto.get("acao_cancelamento", ""):
        resultados.append(R14_dietbox_cancelamento_via_put(acao_str))

    return resultados
