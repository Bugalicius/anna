from __future__ import annotations

import pytest

from app.conversation.state import _mem_store, create_state, load_state, save_state
from app.conversation import orchestrator
from app.conversation.config_loader import config
from app.conversation.tools import ToolResult


pytestmark = pytest.mark.asyncio


SLOTS = [
    {"datetime": "2026-05-18T08:00:00", "data_fmt": "segunda, 18/05/2026", "hora": "08h"},
    {"datetime": "2026-05-19T15:00:00", "data_fmt": "terça, 19/05/2026", "hora": "15h"},
    {"datetime": "2026-05-20T18:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "18h"},
]


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _mem_store.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    async def fake_call_tool(name: str, input: dict):
        if name == "consultar_slots":
            return ToolResult(
                sucesso=True,
                dados={"slots": SLOTS, "match_exato": True, "slots_count": len(SLOTS)},
            )
        if name == "gerar_link_pagamento":
            return ToolResult(sucesso=True, dados={"url": "https://pagamento.test/link", "parcelas": 10})
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call_tool)


async def send(phone: str, text: str, msg_type: str = "text"):
    return await orchestrator.processar_turno(phone, {"type": msg_type, "text": text})


async def state_for(phone: str):
    return await load_state(orchestrator._phone_hash(phone), phone)


async def seed_state(
    phone: str,
    estado: str,
    *,
    collected_data: dict | None = None,
    flags: dict | None = None,
    appointment: dict | None = None,
    last_slots_offered: list[dict] | None = None,
):
    phone_hash = orchestrator._phone_hash(phone)
    state = orchestrator._ensure_v2_state(create_state(phone_hash, phone), phone)
    state["estado"] = estado
    state["collected_data"].update(collected_data or {})
    state["flags"].update(flags or {})
    state["appointment"].update(appointment or {})
    if last_slots_offered is not None:
        state["last_slots_offered"] = last_slots_offered
    await save_state(phone_hash, state)
    return state


def pix_total(plano: str = "ouro", modalidade: str = "presencial") -> float:
    plano_cfg = config.get_plano(plano)
    return float(plano_cfg.valores.pix_online if modalidade == "online" else plano_cfg.valores.pix_presencial)


async def test_fluxo_feliz_completo_presencial():
    phone = "553100000001"
    await send(phone, "oi")
    await send(phone, "Maria")
    await send(phone, "primeira_consulta")
    await send(phone, "emagrecer")
    await send(phone, "ouro")
    await send(phone, "não")
    await send(phone, "presencial")
    await send(phone, "segunda 8h")
    await send(phone, "slot_1")
    await send(phone, "pix")
    await send(phone, f"[comprovante valor={pix_total('ouro') / 2}]")
    result = await send(
        phone,
        "Nome completo: Maria Silva\nData de nascimento: 01/01/1990\nWhatsApp: 31999999999\nE-mail: maria@test.com",
    )

    state = await state_for(phone)
    assert result.sucesso is True
    assert state["estado"] == "concluido"
    assert any("consulta foi confirmada" in m.conteudo for m in result.mensagens_enviadas)


async def test_fluxo_feliz_online_envia_pdf_circunferencias():
    phone = "553100000002"
    await seed_state(
        phone,
        "aguardando_cadastro",
        collected_data={"nome": "Ana", "plano": "ouro", "modalidade": "online"},
        flags={"pagamento_confirmado": True},
        appointment={"slot_escolhido": SLOTS[0]},
    )
    result = await send(
        phone,
        "Nome completo: Ana Lima\nData de nascimento: 01/01/1990\nWhatsApp: 31999999999\nE-mail: ana@test.com",
    )

    assert any(m.tipo == "pdf" and "Circunferências" in (m.arquivo or "") for m in result.mensagens_enviadas)


async def test_nome_generico_bloqueado():
    phone = "553100000003"
    await send(phone, "oi")
    result = await send(phone, "consulta")
    state = await state_for(phone)
    assert state["estado"] == "aguardando_nome"
    assert any("nome" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_nome_e_primeira_consulta_na_mesma_mensagem_avanca_para_objetivo():
    phone = "553100000030"
    await send(phone, "oi")
    result = await send(phone, "Maria Silva, primeira consulta")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_objetivo"
    assert state["collected_data"]["nome"] == "Maria Silva"
    assert state["collected_data"]["status_paciente"] == "novo"
    assert any("objetivo" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_nome_e_retorno_na_mesma_mensagem_avanca_para_localizar_cadastro():
    phone = "553100000031"
    await send(phone, "oi")
    result = await send(phone, "João Pedro Souza, já sou paciente")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_nome_completo_retorno"
    assert state["collected_data"]["nome"] == "João Pedro Souza"
    assert state["collected_data"]["status_paciente"] == "retorno"
    assert any("localizar seu cadastro" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_primeira_mensagem_com_nome_status_e_objetivo_vai_para_planos():
    phone = "553100000032"
    result = await send(phone, "Oi, sou Mariana Alves, primeira consulta, quero emagrecer")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_escolha_plano"
    assert state["collected_data"]["nome"] == "Mariana Alves"
    assert state["collected_data"]["status_paciente"] == "novo"
    assert state["collected_data"]["objetivo"] == "emagrecer"
    assert any("opções" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cadastro_antes_do_comprovante_pix_nao_cai_em_fallback():
    phone = "553100000033"
    await seed_state(
        phone,
        "aguardando_pagamento_pix",
        collected_data={"nome": "Maria", "plano": "ouro", "modalidade": "presencial", "forma_pagamento": "pix"},
    )
    result = await send(phone, "12/03/1992")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_pagamento_pix"
    assert state.get("fallback_streak") in (None, 0)
    assert any("comprovante" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cadastro_incremental_data_e_email_confirma_usando_whatsapp_atual():
    phone = "553100000039"
    await seed_state(
        phone,
        "aguardando_cadastro",
        collected_data={"nome": "Maria Silva", "plano": "ouro", "modalidade": "presencial"},
        flags={"pagamento_confirmado": True},
        appointment={"slot_escolhido": SLOTS[0]},
    )
    first = await send(phone, "12/03/1992")
    final = await send(phone, "maria.silva@gmail.com")
    state = await state_for(phone)

    assert first.novo_estado == "aguardando_cadastro"
    assert final.novo_estado == "concluido"
    assert state["collected_data"]["whatsapp_contato"] == phone
    assert any("consulta foi confirmada" in m.conteudo for m in final.mensagens_enviadas)


async def test_cadastro_incremental_data_invalida_pede_formato():
    phone = "553100000040"
    await seed_state(
        phone,
        "aguardando_cadastro",
        collected_data={"nome": "Tatiane Ribeiro", "plano": "ouro", "modalidade": "presencial"},
        flags={"pagamento_confirmado": True},
        appointment={"slot_escolhido": SLOTS[0]},
    )
    result = await send(phone, "32/13/1999")

    assert result.novo_estado == "aguardando_cadastro"
    assert any("dd/mm/aaaa" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cadastro_incremental_email_invalido_pede_formato():
    phone = "553100000041"
    await seed_state(
        phone,
        "aguardando_cadastro",
        collected_data={"nome": "Isabela Martins", "plano": "ouro", "modalidade": "online", "data_nascimento": "10/10/1990"},
        flags={"pagamento_confirmado": True},
        appointment={"slot_escolhido": SLOTS[0]},
    )
    result = await send(phone, "isabela arroba gmail")

    assert result.novo_estado == "aguardando_cadastro"
    assert any("nome@dominio.com" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cadastro_completo_sem_slot_nao_confirma_sem_horario():
    phone = "553100000042"
    await seed_state(
        phone,
        "aguardando_cadastro",
        collected_data={"nome": "Ana Teste", "data_nascimento": "31/01/1990", "plano": "unica", "modalidade": "presencial"},
        flags={"pagamento_confirmado": True},
    )
    result = await send(phone, "ana.teste@gmail.com")

    assert result.novo_estado == "aguardando_preferencia_horario"
    assert any("falta escolher o horário" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cartao_paguei_responde_sem_silencio():
    phone = "553100000034"
    await seed_state(
        phone,
        "aguardando_pagamento_cartao",
        collected_data={"nome": "João", "plano": "ouro", "modalidade": "online", "forma_pagamento": "cartao"},
    )
    result = await send(phone, "paguei")

    assert result.novo_estado == "aguardando_pagamento_cartao"
    assert any("confirmação do cartão" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_cartao_dado_cadastral_antes_da_confirmacao_nao_cai_em_fallback():
    phone = "553100000036"
    await seed_state(
        phone,
        "aguardando_pagamento_cartao",
        collected_data={"nome": "João", "plano": "ouro", "modalidade": "online", "forma_pagamento": "cartao"},
    )
    result = await send(phone, "21/08/1989")

    assert result.novo_estado == "aguardando_pagamento_cartao"
    assert any("confirmação do cartão" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_troca_de_cartao_para_pix_envia_chave_pix():
    phone = "553100000037"
    await seed_state(
        phone,
        "aguardando_pagamento_cartao",
        collected_data={"nome": "Rafaela", "plano": "ouro", "modalidade": "presencial", "forma_pagamento": "cartao"},
    )
    result = await send(phone, "na verdade quero pix")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_pagamento_pix"
    assert state["collected_data"]["forma_pagamento"] == "pix"
    assert any("chave pix" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_consulta_individual_escolhe_plano_unica():
    phone = "553100000038"
    await seed_state(phone, "aguardando_escolha_plano", collected_data={"nome": "Mariana", "objetivo": "emagrecer"})
    result = await send(phone, "consulta individual")
    state = await state_for(phone)

    assert result.novo_estado == "oferecendo_upsell"
    assert state["collected_data"]["plano"] == "unica"
    assert any("com retorno" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_mudar_preferencia_depois_dos_slots_busca_novamente():
    phone = "553100000035"
    await seed_state(
        phone,
        "aguardando_escolha_slot",
        collected_data={"nome": "Ana", "plano": "ouro", "modalidade": "presencial"},
        last_slots_offered=SLOTS,
    )
    result = await send(phone, "na verdade prefiro noite")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_escolha_slot"
    assert state["collected_data"]["preferencia_horario"]["turno_extraido"] == "noite"
    assert any("qual prefere" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_escolher_slot_por_label_com_dia_e_hora_salva_slot():
    phone = "553100000043"
    await seed_state(
        phone,
        "aguardando_escolha_slot",
        collected_data={"nome": "Ana", "plano": "ouro", "modalidade": "online"},
        last_slots_offered=SLOTS,
    )
    result = await send(phone, "quarta, 20/05/2026 18h")
    state = await state_for(phone)

    assert result.novo_estado == "aguardando_forma_pagamento"
    assert state["appointment"]["slot_escolhido"] == SLOTS[2]


async def test_upsell_aceito_atualiza_plano():
    phone = "553100000004"
    await seed_state(phone, "oferecendo_upsell", collected_data={"nome": "Lia", "plano": "unica"})
    await send(phone, "sim")
    state = await state_for(phone)
    assert state["collected_data"]["plano"] == "com_retorno"


async def test_modalidade_ja_mencionada_pula_pergunta_modalidade():
    phone = "553100000005"
    await seed_state(phone, "aguardando_escolha_plano", collected_data={"nome": "Lia"})
    await send(phone, "quero premium online")
    state = await state_for(phone)
    assert state["collected_data"]["modalidade"] == "online"
    assert state["estado"] == "aguardando_preferencia_horario"


async def test_sexta_noite_recusa_e_mantem_preferencia():
    phone = "553100000006"
    await seed_state(phone, "aguardando_preferencia_horario", collected_data={"nome": "Lia", "modalidade": "online"})
    result = await send(phone, "sexta noite")
    assert result.novo_estado == "aguardando_preferencia_horario"
    assert any("Sexta" in m.conteudo for m in result.mensagens_enviadas)


async def test_horario_fora_da_grade_recusa():
    phone = "553100000007"
    await seed_state(phone, "aguardando_preferencia_horario", collected_data={"nome": "Lia", "modalidade": "online"})
    result = await send(phone, "segunda 14h")
    assert result.novo_estado == "aguardando_preferencia_horario"
    assert any("fora da agenda" in m.conteudo for m in result.mensagens_enviadas)


async def test_mesmo_dia_recusa():
    phone = "553100000008"
    await seed_state(phone, "aguardando_preferencia_horario", collected_data={"nome": "Lia", "modalidade": "online"})
    result = await send(phone, "hoje")
    assert result.novo_estado == "aguardando_preferencia_horario"
    assert any("hoje" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_rejeita_tres_slots_pede_outro_turno():
    phone = "553100000009"
    await seed_state(phone, "aguardando_escolha_slot", last_slots_offered=SLOTS)
    result = await send(phone, "outro turno")
    state = await state_for(phone)
    assert result.novo_estado == "aguardando_preferencia_horario"
    assert len(state["slots_rejeitados"]) == 3


async def test_pix_abaixo_do_sinal_pede_complemento():
    phone = "553100000010"
    await seed_state(phone, "aguardando_pagamento_pix", collected_data={"plano": "ouro", "modalidade": "presencial"})
    result = await send(phone, f"[comprovante valor={pix_total('ouro') / 2 - 10}]")
    assert result.novo_estado == "aguardando_pagamento_pix"
    assert any("sinal mínimo" in m.conteudo for m in result.mensagens_enviadas)


async def test_pix_exato_sinal_aprova_e_pede_cadastro():
    phone = "553100000011"
    await seed_state(phone, "aguardando_pagamento_pix", collected_data={"nome": "Lia", "plano": "ouro", "modalidade": "presencial"})
    result = await send(phone, f"[comprovante valor={pix_total('ouro') / 2}]")
    assert result.novo_estado == "aguardando_cadastro"
    assert any("cadastro" in m.conteudo.lower() for m in result.mensagens_enviadas)


async def test_pix_integral_marca_quitado():
    phone = "553100000012"
    await seed_state(phone, "aguardando_pagamento_pix", collected_data={"plano": "ouro", "modalidade": "presencial"})
    result = await send(phone, f"[comprovante valor={pix_total('ouro')}]")
    state = await state_for(phone)
    assert result.novo_estado == "aguardando_cadastro"
    assert state["flags"]["pago_integral"] is True


async def test_cadastro_incompleto_pede_faltantes():
    phone = "553100000013"
    await seed_state(phone, "aguardando_cadastro", collected_data={"nome": "Lia"})
    result = await send(phone, "meu email é lia@test.com")
    assert result.novo_estado == "aguardando_cadastro"
    assert result.mensagens_enviadas


async def test_gestante_recusa_e_escala():
    phone = "553100000014"
    await seed_state(phone, "aguardando_cadastro", collected_data={"nome": "Lia"})
    result = await send(phone, "estou grávida")
    assert result.novo_estado == "concluido_escalado"
    assert any("gestantes" in m.conteudo for m in result.mensagens_enviadas)


async def test_menor_de_16_recusa_e_escala():
    phone = "553100000015"
    await seed_state(phone, "aguardando_cadastro", collected_data={"nome": "Lia"})
    result = await send(
        phone,
        "Nome completo: Lia Souza\nData de nascimento: 01/01/2015\nWhatsApp: 31999999999\nE-mail: lia@test.com",
    )
    assert result.novo_estado == "concluido_escalado"


async def test_duvida_durante_fluxo_responde_e_mantem_estado():
    phone = "553100000016"
    await seed_state(phone, "aguardando_cadastro", collected_data={"nome": "Lia", "plano": "ouro"})
    result = await send(phone, "quanto custa?")
    assert result.novo_estado == "aguardando_cadastro"
    assert result.mensagens_enviadas
