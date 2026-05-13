"""
Testes de conversas reais — 7 casos baseados em cenários frequentes de atendimento.

Cada teste valida o comportamento correto do planner e/ou responder para uma
situação específica, sem depender de chamadas reais ao LLM.

Casos:
  1. Fernanda Coimbra   — retorno diz "bom dia"; planner detecta tipo antes de prosseguir
  2. Débora Oliveira    — pede remarcação; planner consulta consulta existente primeiro
  3. Camila Gonçalves   — pergunta prazo do formulário; KB deve ter a informação
  4. Bruna Martins      — pergunta duração; NÃO escala (não é dúvida clínica)
  5. Clara Ramos        — pede horário inexistente; responder não inventa slots
  6. Lead de lipedema   — dúvida clínica; Ana escala, não responde
  7. Lead de preço      — pergunta parcelamento; resposta usa valores reais do KB
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ────────────────────────────────────────────────────────────────────

def _state(**kw) -> dict:
    cd = dict(
        nome=None, status_paciente=None, objetivo=None, plano=None,
        modalidade=None, preferencia_horario=None, forma_pagamento=None,
        data_nascimento=None, email=None, instagram=None, profissao=None,
        cep_endereco=None, indicacao_origem=None, motivo_cancelamento=None,
    )
    flags = dict(
        upsell_oferecido=False, planos_enviados=False,
        pagamento_confirmado=False, aguardando_motivo_cancel=False,
    )
    appt = dict(
        slot_escolhido=None, id_agenda=None, id_paciente=None,
        id_transacao=None, consulta_atual=None,
    )
    for k in list(cd):
        if k in kw:
            cd[k] = kw.pop(k)
    for k in list(flags):
        if k in kw:
            flags[k] = kw.pop(k)
    for k in list(appt):
        if k in kw:
            appt[k] = kw.pop(k)
    return {
        "goal":               kw.get("goal", "desconhecido"),
        "status":             kw.get("status", "coletando"),
        "phone":              kw.get("phone", "5531999999999"),
        "phone_hash":         kw.get("phone_hash", "testhash001"),
        "tipo_remarcacao":    kw.get("tipo_remarcacao", None),
        "last_action":        kw.get("last_action", None),
        "collected_data":     cd,
        "appointment":        appt,
        "flags":              flags,
        "last_slots_offered": kw.get("slots", []),
        "history":            kw.get("history", []),
    }


def _turno(**kw) -> dict:
    base = dict(
        intent="agendar", nome=None, status_paciente=None, objetivo=None,
        plano=None, modalidade=None, forma_pagamento=None, escolha_slot=None,
        aceita_upgrade=None, confirmou_pagamento=False, valor_comprovante=None,
        tem_pergunta=False, topico_pergunta=None, preferencia_horario=None,
        data_nascimento=None, email=None, instagram=None, profissao=None,
        cep_endereco=None, indicacao_origem=None, correcao=None,
    )
    return {**base, **kw}


def _mock_llm(json_text: str):
    """Substitui anthropic.Anthropic retornando json_text como resposta do LLM."""
    resp = MagicMock()
    resp.content = [MagicMock(text=json_text)]
    resp.usage = MagicMock(
        input_tokens=100, output_tokens=30,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    client = MagicMock()
    client.messages.create.return_value = resp
    return client


def _plano_base(action: str, **kw) -> dict:
    return {
        "action": action, "tool": kw.get("tool"), "params": kw.get("params", {}),
        "ask_context": kw.get("ask_context"), "new_status": None,
        "update_data": {}, "update_appointment": {}, "update_flags": {},
        "draft_message": None,
    }


# ── Caso 1: Fernanda Coimbra — paciente de retorno diz "bom dia" ──────────────

@pytest.mark.asyncio
async def test_fernanda_retorno_bom_dia_aciona_detectar_tipo():
    """
    Fernanda é paciente de retorno identificada (nome + status_paciente preenchidos),
    mas ainda sem plano/modalidade escolhidos (acaba de se identificar).
    Ao dizer "bom dia", planner deve acionar detectar_tipo_remarcacao (Etapa 1c)
    para saber se tem consulta ativa antes de prosseguir com o fluxo.

    Estado: nenhum override da Regra 1-4 ativa (plano=None impede Regras 3/4),
    então o LLM decide.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(
        goal="agendar_consulta",
        nome="Fernanda Coimbra",
        status_paciente="retorno",
        objetivo="emagrecer",
        # plano/modalidade/preferencia ainda não coletados — Fernanda acabou de se identificar
        # Como retorno, já passou pela fase de planos/upsell na consulta original
        planos_enviados=True,
        upsell_oferecido=True,
        tipo_remarcacao=None,
    )
    turno = _turno(intent="agendar")

    llm_json = (
        '{"action":"execute_tool","tool":"detectar_tipo_remarcacao",'
        '"params":{"telefone":"5531999999999"}}'
    )
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"


# ── Caso 2: Débora Oliveira — pede remarcação ─────────────────────────────────

@pytest.mark.asyncio
async def test_debora_remarcacao_detecta_consulta_existente_primeiro():
    """
    Débora pede remarcação. Antes de oferecer novos slots, planner deve
    detectar a consulta existente. Não deve pular para ask_field.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(
        goal="agendar_consulta",
        nome="Débora Oliveira",
        status_paciente="retorno",
        tipo_remarcacao=None,
    )
    turno = _turno(intent="remarcar")

    llm_json = (
        '{"action":"execute_tool","tool":"detectar_tipo_remarcacao",'
        '"params":{"telefone":"5531999999999"}}'
    )
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "detectar_tipo_remarcacao"
    assert plano["action"] != "ask_field"


@pytest.mark.asyncio
async def test_debora_tipo_retorno_busca_slots_remarcar():
    """
    Após detectar tipo=retorno, planner deve usar consultar_slots_remarcar
    (dentro da janela de retorno), não consultar_slots comum.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(
        goal="agendar_consulta",
        nome="Débora Oliveira",
        status_paciente="retorno",
        modalidade="presencial",
        tipo_remarcacao="retorno",
        preferencia_horario={"tipo": "qualquer", "descricao": "qualquer horário"},
    )
    turno = _turno(intent="remarcar")

    llm_json = (
        '{"action":"execute_tool","tool":"consultar_slots_remarcar",'
        '"params":{"modalidade":"presencial","preferencia":{},"fim_janela":null,"excluir":[]}}'
    )
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "execute_tool"
    assert plano["tool"] == "consultar_slots_remarcar"


# ── Caso 3: Camila Gonçalves — prazo de entrega do formulário ─────────────────

@pytest.mark.xfail(reason="GAP: KB não tem entrada sobre prazo de formulário — adicionar ao knowledge_base/")
def test_camila_kb_tem_info_sobre_prazo_formulario():
    """
    Base de conhecimento deve conter informação sobre prazo de entrega da dieta
    para pacientes que escolheram a modalidade formulário (5 dias úteis).
    Marcado como xfail para documentar o gap — deve passar após adicionar ao KB.
    """
    from app.knowledge_base import kb

    faq = kb.faq_combinado()
    entradas_prazo = [
        item for item in faq
        if any(kw in (item.get("pergunta") or "").lower()
               for kw in ("prazo", "dieta", "formulário", "dias", "entrega", "receber"))
        or any(kw in (item.get("resposta") or "").lower()
               for kw in ("5 dias", "úteis", "formulário", "dieta"))
    ]
    assert len(entradas_prazo) >= 1, (
        "KB não tem entrada sobre prazo de entrega da dieta via formulário. "
        "Adicione ao knowledge_base/ ou FAQ."
    )


def test_camila_resposta_prazo_menciona_dias():
    """
    A entrada de prazo no FAQ deve mencionar quantos dias o paciente espera.
    """
    from app.knowledge_base import kb

    faq = kb.faq_combinado()
    for item in faq:
        pergunta = (item.get("pergunta") or "").lower()
        if any(kw in pergunta for kw in ("prazo", "dieta", "quando", "entrega", "receber")):
            resposta = (item.get("resposta") or "").lower()
            assert any(kw in resposta for kw in ("dias", "úteis", "5")), (
                f"Resposta sobre prazo não menciona dias: '{item.get('resposta')}'"
            )
            return  # basta uma entrada válida


# ── Caso 4: Bruna Martins — pergunta duração da consulta ─────────────────────

def test_bruna_duracao_nao_e_duvida_clinica_no_fallback():
    """
    Dúvida sobre duração da consulta (topico=modalidade) NÃO deve ser escalada.
    O fallback do planner para tirar_duvida não deve retornar escalate.
    """
    from app.conversation_legacy.planner import _fallback

    turno = _turno(intent="tirar_duvida", tem_pergunta=True, topico_pergunta="modalidade")
    state = _state()

    plano = _fallback(turno, state)

    assert plano["action"] != "escalate", (
        "Pergunta sobre duração da consulta foi escalada incorretamente — "
        "apenas dúvidas clínicas devem escalar."
    )


@pytest.mark.asyncio
async def test_bruna_planner_answer_question_sem_escalar():
    """
    Planner deve retornar answer_question para dúvida sobre duração.
    Nunca escalate nem respond_fora_de_contexto para esse caso.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(goal="desconhecido")
    turno = _turno(intent="tirar_duvida", tem_pergunta=True, topico_pergunta="modalidade")

    llm_json = (
        '{"action":"answer_question","ask_context":"modalidade",'
        '"draft_message":"A consulta presencial dura até 1h. '
        'O retorno costuma ser mais rápido, entre 40 e 50 min."}'
    )
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano["action"] != "escalate"
    assert plano["action"] != "respond_fora_de_contexto"


# ── Caso 5: Clara Ramos — pede horário que não existe ────────────────────────

@pytest.mark.asyncio
async def test_clara_sem_slots_responder_nao_inventa_horario():
    """
    Quando Dietbox retorna lista vazia de slots, responder deve comunicar
    indisponibilidade sem inventar horários ou botões de opção.
    """
    from app.conversation_legacy.responder import gerar_resposta

    state = _state(
        goal="agendar_consulta",
        nome="Clara Ramos",
        status_paciente="novo",
        objetivo="emagrecer",
        plano="ouro",
        modalidade="presencial",
        preferencia_horario={"tipo": "turno", "turno": "manha", "descricao": "manhã"},
        planos_enviados=True,
        upsell_oferecido=True,
    )
    plano = _plano_base("execute_tool", tool="consultar_slots")
    resultado_tool = {"sucesso": True, "slots": []}

    respostas = await gerar_resposta(state, plano, resultado_tool)

    assert len(respostas) >= 1
    ultima = respostas[-1]
    # Não deve retornar dict interativo com botões de slots
    assert isinstance(ultima, str), (
        "Responder retornou botões de slot com lista vazia — está inventando horários"
    )
    assert any(kw in ultima.lower() for kw in ("não encontrei", "horários", "verificar", "thaynara"))


def test_clara_escolha_fora_do_range_nao_confirma_slot_inexistente():
    """
    Se o paciente digita "4" mas só há 3 slots, o override da Regra 5
    não deve confirmar o slot nem avançar para pagamento.
    """
    from app.conversation_legacy.planner import _override_deterministic

    slots = [
        {"datetime": "2026-05-05T08:00:00", "data_fmt": "segunda, 05/05", "hora": "08h"},
        {"datetime": "2026-05-05T09:00:00", "data_fmt": "segunda, 05/05", "hora": "09h"},
        {"datetime": "2026-05-05T10:00:00", "data_fmt": "segunda, 05/05", "hora": "10h"},
    ]
    state = _state(
        goal="agendar_consulta",
        nome="Clara Ramos",
        status_paciente="novo",
        objetivo="emagrecer",
        plano="ouro",
        modalidade="presencial",
        preferencia_horario={"tipo": "turno", "turno": "manha", "descricao": "manhã"},
        planos_enviados=True,
        upsell_oferecido=True,
        slots=slots,
    )
    turno = _turno(intent="agendar", escolha_slot=4)  # slot 4 não existe

    override = _override_deterministic(turno, state)

    if override is not None:
        assert override["action"] != "ask_forma_pagamento", (
            "Override confirmou slot inexistente (escolha 4 com apenas 3 slots disponíveis)"
        )


# ── Caso 6: Lead de lipedema — dúvida clínica ────────────────────────────────

def test_lipedema_fallback_escala_duvida_clinica():
    """
    Mesmo quando o LLM falha e o fallback é acionado, dúvidas clínicas
    devem escalar. Ana nunca responde perguntas médicas diretamente.
    """
    from app.conversation_legacy.planner import _fallback

    turno = _turno(intent="duvida_clinica", tem_pergunta=True, topico_pergunta="clinica")
    state = _state()

    plano = _fallback(turno, state)

    assert plano["action"] == "escalate", (
        f"Dúvida clínica deveria escalar, mas fallback retornou: {plano['action']}"
    )


@pytest.mark.asyncio
async def test_lipedema_llm_escala_duvida_clinica():
    """
    LLM deve retornar escalate para 'posso comer X tendo lipedema?'
    O planner não deve retornar answer_question para questões clínicas.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(goal="desconhecido")
    turno = _turno(intent="duvida_clinica", tem_pergunta=True, topico_pergunta="clinica")

    llm_json = '{"action":"escalate"}'
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "escalate"
    assert plano["action"] not in ("answer_question", "respond_fora_de_contexto"), (
        "Ana respondeu diretamente uma dúvida clínica — viola a regra de escalação"
    )


# ── Caso 7: Lead de preço — pergunta parcelamento ────────────────────────────

def test_preco_kb_tem_parcelas_reais_para_todos_planos():
    """
    KB deve ter valores reais de parcelamento para os planos que oferecem cartão.
    Nenhum valor pode ser zero ou inconsistente.
    """
    from app.knowledge_base import kb

    for nome_plano in ("premium", "ouro", "com_retorno"):
        plano = kb.get_plano(nome_plano)
        assert plano is not None, f"Plano '{nome_plano}' não encontrado no KB"

        valor = kb.get_valor(nome_plano, "presencial")
        parcelas = kb.get_parcelas(nome_plano)
        assert valor > 0, f"Plano '{nome_plano}' tem valor zero"
        assert parcelas >= 1, f"Plano '{nome_plano}' tem parcelas inválidas"

        parcela_unit = plano.get("parcela_presencial")
        if parcela_unit:
            # Soma das parcelas >= valor integral (cartão sem juros)
            assert parcela_unit * parcelas >= valor * 0.99, (
                f"{nome_plano}: {parcela_unit}x{parcelas} < {valor} — "
                "parcelamento inconsistente no KB"
            )


def test_preco_resposta_usa_valores_reais_sem_desconto_inventado():
    """
    _answer_from_kb para tópico 'pagamento' deve citar o valor real do KB.
    Não deve mencionar descontos fictícios (80%, 90%, grátis).
    """
    from app.conversation_legacy.responder import _answer_from_kb
    from app.knowledge_base import kb

    cd = {"plano": "ouro", "modalidade": "presencial"}
    resposta = _answer_from_kb("pagamento", cd)

    valor_real = kb.get_valor("ouro", "presencial")
    assert str(int(valor_real)) in resposta, (
        f"Resposta não menciona o valor real R${valor_real:.0f}: {resposta}"
    )
    assert "80%" not in resposta
    assert "90%" not in resposta
    assert "grátis" not in resposta.lower()
    assert "gratuito" not in resposta.lower()


@pytest.mark.asyncio
async def test_preco_planner_retorna_answer_question_para_pagamento():
    """
    Pergunta sobre parcelamento → planner retorna answer_question com
    ask_context=pagamento. Nunca respond_fora_de_contexto.
    """
    from app.conversation_legacy.planner import decidir_acao

    state = _state(goal="desconhecido", status="coletando")
    turno = _turno(intent="tirar_duvida", tem_pergunta=True, topico_pergunta="pagamento")

    llm_json = '{"action":"answer_question","ask_context":"pagamento","draft_message":null}'
    with patch("anthropic.Anthropic", return_value=_mock_llm(llm_json)):
        plano = await decidir_acao(turno, state)

    assert plano["action"] == "answer_question"
    assert plano["ask_context"] == "pagamento"
    assert plano["action"] != "respond_fora_de_contexto"
