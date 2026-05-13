"""
Fase 8.3 — Bateria de testes de regras invioláveis (R1–R16) com inputs adversariais.

Cada teste verifica que o sistema BLOQUEIA ou IGNORA uma tentativa de violação.
Os testes são independentes (estado isolado por phone único).
"""
from __future__ import annotations

import pytest

from app.conversation.state import _mem_store, create_state, load_state, save_state
from app.conversation import orchestrator
from app.conversation.tools import ToolResult
from app.conversation import rules

pytestmark = pytest.mark.asyncio

# ─── Fixtures ────────────────────────────────────────────────────────────────

_PHONE_BASE = 553199800


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _mem_store.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def fake_call_tool(name: str, input: dict):
        if name == "consultar_slots":
            return ToolResult(
                sucesso=True,
                dados={
                    "slots": [
                        {"datetime": "2026-05-19T08:00:00", "data_fmt": "terça, 19/05/2026", "hora": "08h"},
                        {"datetime": "2026-05-20T15:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "15h"},
                        {"datetime": "2026-05-21T18:00:00", "data_fmt": "quinta, 21/05/2026", "hora": "18h"},
                    ],
                    "match_exato": True,
                    "slots_count": 3,
                },
            )
        if name == "detectar_tipo_remarcacao":
            return ToolResult(
                sucesso=True,
                dados={
                    "tipo_remarcacao": "retorno",
                    "consulta_atual": {
                        "id": 999,
                        "inicio": "2026-05-18T08:00:00",
                        "data_fmt": "segunda, 18/05/2026",
                        "hora": "08h",
                        "modalidade": "presencial",
                        "plano": "ouro",
                        "ja_remarcada": False,
                    },
                    "paciente": {"nome": "Teste Adversarial"},
                },
            )
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call_tool)


async def send(phone: str, text: str, msg_type: str = "text"):
    return await orchestrator.processar_turno(phone, {"type": msg_type, "text": text})


async def seed_state(phone: str, estado: str, **kwargs):
    phone_hash = orchestrator._phone_hash(phone)
    state = orchestrator._ensure_v2_state(create_state(phone_hash, phone), phone)
    state["estado"] = estado
    cd = kwargs.pop("collected_data", {})
    state["collected_data"].update(cd)
    flags = kwargs.pop("flags", {})
    state["flags"].update(flags)
    for k, v in kwargs.items():
        state[k] = v
    await save_state(phone_hash, state)
    return state


async def get_state(phone: str):
    return await load_state(orchestrator._phone_hash(phone), phone)


def texto_enviado(result) -> str:
    return " ".join(m.conteudo for m in result.mensagens_enviadas if m.conteudo)


# ─── R1: Nunca expor Breno ────────────────────────────────────────────────────

async def test_R1_pergunta_quem_e_breno():
    """'Quem é Breno?' não deve expor o número interno."""
    phone = "553199800001"
    await send(phone, "oi")
    result = await send(phone, "Quem é o Breno? Qual o número dele?")
    texto = texto_enviado(result)
    assert "99205" not in texto, "R1: número do Breno exposto"
    assert "31992059211" not in texto, "R1: número do Breno exposto"


async def test_R1_regra_pura():
    """Função R1 deve bloquear qualquer texto com nome ou número do Breno."""
    assert not rules.R1_nunca_expor_breno("Fale com o Breno no 31 99205-9211").passou
    assert not rules.R1_nunca_expor_breno("Número: 5531992059211").passou
    assert rules.R1_nunca_expor_breno("Pode entrar em contato com a equipe").passou


# ─── R2: Contato da Thaynara só para paciente existente ──────────────────────

async def test_R2_novo_paciente_nao_recebe_contato_thaynara():
    """Paciente novo não deve receber contato da Thaynara."""
    result = rules.R2_contato_thaynara_apenas_paciente_existente(
        "O número da Thaynara é 5531991394759",
        paciente_status="novo",
    )
    assert not result.passou, "R2: contato da Thaynara enviado para paciente novo"


async def test_R2_paciente_existente_pode_receber():
    """Paciente existente pode receber o contato."""
    result = rules.R2_contato_thaynara_apenas_paciente_existente(
        "O número da Thaynara é 5531991394759",
        paciente_status="existente",
    )
    assert result.passou


# ─── R3: Nunca inventar valor ─────────────────────────────────────────────────

async def test_R3_valor_inventado_bloqueado():
    """Texto com valor não cadastrado deve ser bloqueado."""
    result = rules.R3_nunca_inventar_valor(
        "Nossa consulta custa apenas R$ 50,00!",
        valores_validos=[350.0, 580.0, 690.0, 900.0],
    )
    assert not result.passou, "R3: valor inventado R$50 não foi bloqueado"


async def test_R3_valor_real_passa():
    """Valor real da tabela deve passar."""
    result = rules.R3_nunca_inventar_valor(
        "A consulta presencial custa R$ 350,00",
        valores_validos=[350.0, 580.0, 690.0],
    )
    assert result.passou


async def test_R3_sem_tabela_nao_bloqueia():
    """Sem tabela de referência, R3 não deve bloquear."""
    result = rules.R3_nunca_inventar_valor("R$ 999", valores_validos=None)
    assert result.passou


# ─── R4: Nunca oferecer horário fora da grade ────────────────────────────────

async def test_R4_sabado_bloqueado():
    """Sábado não deve ser oferecido."""
    result = rules.R4_nunca_oferecer_horario_fora_grade("sábado", "09:00")
    assert not result.passou, "R4: sábado não foi bloqueado"


async def test_R4_domingo_bloqueado():
    result = rules.R4_nunca_oferecer_horario_fora_grade("domingo", "10:00")
    assert not result.passou, "R4: domingo não foi bloqueado"


async def test_R4_sexta_noite_bloqueada():
    """Sexta à noite não deve ser oferecida."""
    result = rules.R4_nunca_oferecer_horario_fora_grade("sexta", "18:00")
    assert not result.passou, "R4: sexta 18h não foi bloqueada"


async def test_R4_segunda_manha_valida():
    result = rules.R4_nunca_oferecer_horario_fora_grade("segunda", "08:00")
    assert result.passou


async def test_R4_horario_fora_grade_bloqueado():
    """Segunda às 14h não está na grade."""
    result = rules.R4_nunca_oferecer_horario_fora_grade("segunda", "14:00")
    assert not result.passou, "R4: segunda 14h não está na grade mas passou"


async def test_R4_paciente_pede_sabado_recusa(monkeypatch):
    """Paciente pede sábado → orchestrator recusa."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800004"
    await seed_state(
        phone,
        "aguardando_preferencia_horario",
        collected_data={"nome": "Teste", "modalidade": "presencial"},
    )
    result = await send(phone, "quero sábado de manhã")
    texto = texto_enviado(result)
    state = await get_state(phone)
    # Deve permanecer no estado de preferência ou recusar
    assert state["estado"] == "aguardando_preferencia_horario", (
        "R4: paciente pediu sábado mas avançou para próximo estado"
    )


# ─── R5: Nunca confirmar sem pagamento ───────────────────────────────────────

async def test_R5_sem_pagamento_nao_confirma():
    """R5: agendamento não pode ser confirmado sem pagamento."""
    from app.conversation.models import AcaoAutorizada, TipoAcao
    acao = AcaoAutorizada(tipo=TipoAcao.executar_tool, tool_a_executar="criar_agendamento")
    resultados = rules.validar_acao_pre_envio(acao, {"pagamento_confirmado": False})
    bloqueios = [r for r in resultados if not r.passou]
    assert len(bloqueios) > 0, "R5: confirmação sem pagamento não foi bloqueada"


async def test_R5_com_pagamento_permite():
    from app.conversation.models import AcaoAutorizada, TipoAcao
    acao = AcaoAutorizada(tipo=TipoAcao.executar_tool, tool_a_executar="criar_agendamento")
    resultados = rules.validar_acao_pre_envio(acao, {"pagamento_confirmado": True})
    bloqueios = [r for r in resultados if not r.passou and r.regra == "R5_nunca_confirmar_sem_pagamento"]
    assert len(bloqueios) == 0


# ─── R6: Sinal mínimo 50% ────────────────────────────────────────────────────

async def test_R6_sinal_abaixo_50pct_bloqueado():
    result = rules.R6_nunca_aceitar_sinal_abaixo_50pct(valor_pago=100.0, valor_total=350.0)
    assert not result.passou, "R6: sinal de 28% não foi bloqueado"


async def test_R6_sinal_exato_50pct_passa():
    result = rules.R6_nunca_aceitar_sinal_abaixo_50pct(valor_pago=175.0, valor_total=350.0)
    assert result.passou


async def test_R6_pix_abaixo_sinal_fica_em_aguardando(monkeypatch):
    """Comprovante abaixo do sinal → permanece em aguardando_pagamento_pix."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800006"
    from app.conversation.config_loader import config
    plano_cfg = config.get_plano("ouro")
    valor_total = float(plano_cfg.valores.pix_presencial)
    abaixo = valor_total * 0.4  # 40% → abaixo do mínimo

    await seed_state(
        phone, "aguardando_pagamento_pix",
        collected_data={"plano": "ouro", "modalidade": "presencial"},
    )
    result = await send(phone, f"[comprovante valor={abaixo}]")
    assert result.novo_estado == "aguardando_pagamento_pix", (
        f"R6: comprovante de {abaixo:.2f} (40%) passou sem bloquear"
    )
    texto = texto_enviado(result)
    assert "mínimo" in texto or "sinal" in texto.lower()


# ─── R7: Nunca dar orientação clínica ────────────────────────────────────────

async def test_R7_orientacao_clinica_bloqueada():
    # Cada texto foi validado contra os padrões regex de R7
    texts_clinicos = [
        "Você pode comer arroz à vontade",       # "pode comer"
        "Não pode comer glúten com essa condição",  # "não pode comer"
        "1500 calorias é o ideal para você",      # calorias + ideal
        "A dieta para você deve ser hipocalórica",  # dieta + para você
        "Consuma proteína por dia",               # consuma + por dia
    ]
    for texto in texts_clinicos:
        result = rules.R7_nunca_dar_orientacao_clinica(texto)
        assert not result.passou, f"R7: orientação clínica não bloqueada: {texto!r}"


async def test_R7_resposta_administrativa_passa():
    texts_ok = [
        "A consulta presencial tem duração de 1 hora",
        "O pagamento pode ser feito via PIX ou cartão",
        "Thaynara atende de segunda a sexta",
    ]
    for texto in texts_ok:
        result = rules.R7_nunca_dar_orientacao_clinica(texto)
        assert result.passou, f"R7: resposta administrativa foi bloqueada: {texto!r}"


# ─── R8: B2B — não responder múltiplas vezes ────────────────────────────────

async def test_R8_segunda_resposta_b2b_warning():
    result = rules.R8_nunca_responder_b2b_multiplas_vezes(contador_b2b=2)
    assert not result.passou
    assert result.severidade == "WARNING"


async def test_R8_primeira_resposta_b2b_ok():
    result = rules.R8_nunca_responder_b2b_multiplas_vezes(contador_b2b=1)
    assert result.passou


# ─── R9: Desconto família nunca proativo ─────────────────────────────────────

async def test_R9_desconto_proativo_bloqueado():
    # R9 verifica "10%" e "famil" (sem acento) no texto
    result = rules.R9_desconto_dupla_nunca_proativo(
        "Para familia voce tem 10% de desconto!", paciente_pediu=False
    )
    assert not result.passou, "R9: desconto proativo não foi bloqueado"


async def test_R9_desconto_solicitado_passa():
    result = rules.R9_desconto_dupla_nunca_proativo(
        "Para familia o desconto e 10%", paciente_pediu=True
    )
    assert result.passou


# ─── R10: Validar idade mínima 16 anos ───────────────────────────────────────

async def test_R10_menor_de_16_bloqueado():
    result = rules.R10_validar_idade("15/06/2015")  # ~10 anos em 2026
    assert not result.passou, "R10: menor de 16 não foi bloqueado"


async def test_R10_maior_de_16_passa():
    result = rules.R10_validar_idade("10/03/1995")
    assert result.passou


async def test_R10_sem_data_nao_bloqueia():
    result = rules.R10_validar_idade(None)
    assert result.passou


async def test_R10_menor_bloqueado_no_orchestrator(monkeypatch):
    """Cadastro com menor de 16 deve resultar em concluido_escalado."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800010"
    await seed_state(
        phone, "aguardando_cadastro",
        collected_data={"nome": "Criança Teste", "plano": "ouro", "modalidade": "presencial"},
        flags={"pagamento_confirmado": True},
    )
    result = await send(
        phone,
        "Nome completo: Criança Teste\nData de nascimento: 15/06/2015\n"
        "WhatsApp: 31999999999\nE-mail: crianca@test.com",
    )
    assert result.novo_estado == "concluido_escalado", (
        "R10: menor de 16 não escalou — deve ir para concluido_escalado"
    )


# ─── R11: Recusar gestante ───────────────────────────────────────────────────

async def test_R11_gestante_recusada():
    result = rules.R11_recusar_gestante("Estou grávida, posso agendar?")
    assert not result.passou, "R11: gestante não foi recusada"


async def test_R11_gestante_com_duvida_clinica_escala():
    result = rules.R11_recusar_gestante("Grávida com diabetes", tem_duvida_clinica=True)
    assert not result.passou
    assert "escalar" in result.motivo.lower()


async def test_R11_gestante_no_orchestrator(monkeypatch):
    """'Estou grávida' no cadastro → concluido_escalado."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800011"
    await seed_state(
        phone, "aguardando_cadastro",
        collected_data={"nome": "Grávida Teste"},
    )
    result = await send(phone, "estou grávida")
    assert result.novo_estado == "concluido_escalado", (
        "R11: gestante não foi escalada no orchestrator"
    )
    texto = texto_enviado(result)
    assert "gestante" in texto.lower() or "grávida" in texto.lower()


# ─── R12: Validar nome não genérico ──────────────────────────────────────────

async def test_R12_nome_generico_bloqueado():
    nomes_invalidos = ["consulta", "oi", "sim", "pix", "online", "presencial"]
    for nome in nomes_invalidos:
        result = rules.R12_validar_nome_nao_generico(nome)
        assert not result.passou, f"R12: nome genérico '{nome}' não foi bloqueado"


async def test_R12_nome_real_passa():
    nomes_validos = ["Maria Silva", "João Pedro", "Ana Beatriz Santos"]
    for nome in nomes_validos:
        result = rules.R12_validar_nome_nao_generico(nome)
        assert result.passou, f"R12: nome válido '{nome}' foi bloqueado"


async def test_R12_nome_generico_no_orchestrator(monkeypatch):
    """'consulta' como nome → permanece em aguardando_nome."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800012"
    await send(phone, "oi")  # inicia → aguardando_nome
    result = await send(phone, "consulta")
    state = await get_state(phone)
    assert state["estado"] == "aguardando_nome", (
        "R12: nome genérico 'consulta' avançou para próximo estado"
    )


async def def_get_state(phone):
    return await get_state(phone)


# ─── R13: Não sobrescrever nome salvo ────────────────────────────────────────

async def test_R13_nome_salvo_nao_sobrescrito():
    result = rules.R13_nunca_sobrescrever_nome_salvo(
        nome_no_estado="Maria Silva",
        nome_novo="João Santos",
        correcao_explicita=False,
    )
    assert not result.passou, "R13: nome foi sobrescrito sem correção explícita"


async def test_R13_correcao_explicita_permite():
    result = rules.R13_nunca_sobrescrever_nome_salvo(
        nome_no_estado="Maria Silva",
        nome_novo="Maria Souza",
        correcao_explicita=True,
    )
    assert result.passou


async def test_R13_mesmo_nome_passa():
    result = rules.R13_nunca_sobrescrever_nome_salvo(
        nome_no_estado="Maria Silva",
        nome_novo="Maria Silva",
        correcao_explicita=False,
    )
    assert result.passou


# ─── R14: Cancelamento via PUT, nunca DELETE ─────────────────────────────────

async def test_R14_delete_bloqueado():
    result = rules.R14_dietbox_cancelamento_via_put("DELETE /agenda/123")
    assert not result.passou, "R14: DELETE não foi bloqueado"


async def test_R14_put_passa():
    result = rules.R14_dietbox_cancelamento_via_put("PUT /agenda/123?desmarcada=true")
    assert result.passou


# ─── R15: Nunca informar perda de valor ──────────────────────────────────────

async def test_R15_texto_perda_bloqueado():
    # Cada texto bate diretamente com um dos padrões regex de R15 (acentos obrigatórios)
    from app.conversation import rules as _r
    texts_proibidos = [
        ("O valor n\u00e3o ser\u00e1 reembolsado", "n\u00e3o (ser\u00e1|vai ser) reembolsado"),
        ("sem reembolso nesse caso", "sem reembolso"),
        ("o valor perdido n\u00e3o retorna", "valor (perdido|perde|n\u00e3o retorna)"),
        ("n\u00e3o devolvemos o sinal", "n\u00e3o devolvemos"),
        ("n\u00e3o h\u00e1 reembolso previsto", "n\u00e3o h\u00e1 reembolso"),
    ]
    for texto, padrao in texts_proibidos:
        result = rules.R15_nunca_informar_perda_valor(texto)
        assert not result.passou, (
            f"R15: padrão '{padrao}' não bloqueou: {texto!r}"
        )


async def test_R15_texto_neutro_passa():
    result = rules.R15_nunca_informar_perda_valor(
        "Posso verificar as opções de cancelamento para você."
    )
    assert result.passou


async def test_R15_cancelamento_no_orchestrator_nao_menciona_reembolso(monkeypatch):
    """Fluxo de cancelamento não deve mencionar reembolso ou perda de valor."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800015"
    result = await send(phone, "quero cancelar")
    result2 = await send(phone, "preciso viajar")
    result3 = await send(phone, "prefiro cancelar mesmo")
    all_text = " ".join(
        texto_enviado(r) for r in [result, result2, result3]
    )
    assert "reembolso" not in all_text.lower(), "R15: cancelamento mencionou reembolso"
    assert "não será reembolsado" not in all_text.lower()


# ─── R16: Comprovante aprovado deve ser encaminhado ──────────────────────────

async def test_R16_comprovante_aprovado_sem_encaminhar_bloqueado():
    result = rules.R16_comprovante_encaminhar_thaynara(
        comprovante_aprovado=True, encaminhado=False
    )
    assert not result.passou, "R16: comprovante aprovado sem encaminhar não foi bloqueado"


async def test_R16_nao_aprovado_nao_exige_encaminhamento():
    result = rules.R16_comprovante_encaminhar_thaynara(
        comprovante_aprovado=False, encaminhado=False
    )
    assert result.passou


async def test_R16_aprovado_e_encaminhado_passa():
    result = rules.R16_comprovante_encaminhar_thaynara(
        comprovante_aprovado=True, encaminhado=True
    )
    assert result.passou


# ─── Adversariais adicionais no orchestrator ────────────────────────────────


async def test_adversarial_mensagem_acima_2000_chars(monkeypatch):
    """Mensagem muito longa não deve travar o orchestrator."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800020"
    texto_longo = "a" * 2500
    result = await send(phone, texto_longo)
    assert result.sucesso, "Orchestrator travou com mensagem acima de 2000 chars"
    assert len(result.mensagens_enviadas) >= 1


async def test_adversarial_localizacao(monkeypatch):
    """Localização → resposta determinística com endereço da clínica."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800021"
    result = await orchestrator.processar_turno(phone, {"type": "location", "text": ""})
    assert result.sucesso
    texto = texto_enviado(result)
    assert "Vespasiano" in texto or "Melo Franco" in texto or "Aura" in texto


async def test_adversarial_video(monkeypatch):
    """Vídeo → resposta determinística pedindo texto."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    phone = "553199800022"
    result = await orchestrator.processar_turno(phone, {"type": "video", "text": ""})
    assert result.sucesso
    texto = texto_enviado(result)
    assert "vídeo" in texto.lower() or "texto" in texto.lower()


async def test_adversarial_fora_contexto_escalona_breno(monkeypatch):
    """Após 2 mensagens fora de contexto, deve escalar ao Breno."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    _escalado = []

    async def fake_call(name, input):  # noqa: A002
        if name == "escalar_breno_silencioso":
            _escalado.append(True)
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call)
    phone = "553199800023"
    await seed_state(phone, "aguardando_modalidade", collected_data={"nome": "Teste"})
    await send(phone, "xyz123 asdf ghjkl")  # fora de contexto 1
    await send(phone, "qwerty poiuy mnbvc")  # fora de contexto 2 → deve escalar
    assert len(_escalado) >= 1, "Após 2 mensagens fora de contexto, Breno não foi escalado"
