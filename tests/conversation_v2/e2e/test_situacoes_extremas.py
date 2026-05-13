"""Hardening v2.1 — situações extremas e adversariais.

A suíte prioriza invariantes de produção: não quebrar o turno, não expor dados
internos, não orientar clinicamente e manter restrições de agenda/pagamento.
"""
from __future__ import annotations

import itertools

import pytest

from app.conversation import orchestrator, rules
from app.conversation.models import Mensagem
from app.conversation.output_validator import validar
from app.conversation.state import _mem_store, create_state, save_state
from app.conversation.tools import ToolResult

pytestmark = pytest.mark.asyncio

_PHONE_SEQ = itertools.count(900000)


def _phone() -> str:
    return f"553199{next(_PHONE_SEQ):06d}"


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    _mem_store.clear()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    chamadas: list[str] = []

    async def fake_call_tool(name: str, input: dict):  # noqa: A002
        chamadas.append(name)
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
        if name == "transcrever_audio":
            return ToolResult(sucesso=True, dados={"transcricao": input.get("transcricao") or ""})
        if name == "analisar_comprovante":
            return ToolResult(sucesso=True, dados={"valor": 0.01, "aprovado": False})
        return ToolResult(sucesso=True, dados={})

    monkeypatch.setattr(orchestrator, "call_tool", fake_call_tool)
    return chamadas


async def _seed(phone: str, estado: str, **kwargs) -> dict:
    phone_hash = orchestrator._phone_hash(phone)
    state = orchestrator._ensure_v2_state(create_state(phone_hash, phone), phone)
    state["estado"] = estado
    state["collected_data"].update(kwargs.pop("collected_data", {}))
    state["flags"].update(kwargs.pop("flags", {}))
    for key, value in kwargs.items():
        state[key] = value
    await save_state(phone_hash, state)
    return state


async def _send(text: str, *, phone: str | None = None, msg_type: str = "text", **extra):
    payload = {"type": msg_type, "text": text}
    payload.update(extra)
    return await orchestrator.processar_turno(phone or _phone(), payload)


def _texto(result) -> str:
    return " ".join(m.conteudo for m in result.mensagens_enviadas if m.conteudo)


@pytest.mark.parametrize(
    "mensagem",
    [
        "vai tomar no cu",
        "que merda de agenda",
        "porra, ninguém responde",
        "caralho, que demora",
        "você é burra",
        "sua incompetente",
        "vocês são uns vagabundos",
        "estou sendo enrolado",
        "vou processar vocês",
        "vou denunciar no Procon",
        "cadê o Breno seu lixo",
        "essa nutri é uma porcaria",
    ],
)
async def test_agressao_primeira_resposta_profissional(mensagem):
    result = await _send(mensagem)
    texto = _texto(result)
    assert result.sucesso
    assert "frustrado" in texto.lower()
    assert "99205" not in texto
    assert "Breno" not in texto


@pytest.mark.parametrize(
    "segunda",
    [
        "vai tomar no cu de novo",
        "sua incompetente",
        "vou processar",
        "que merda",
        "lixo",
        "procon agora",
    ],
)
async def test_agressao_reincidente_escala_silenciosamente(segunda, isolate):
    phone = _phone()
    await _send("você é um lixo", phone=phone)
    result = await _send(segunda, phone=phone)
    texto = _texto(result)
    assert "equipe" in texto.lower()
    assert "Breno" not in texto
    assert "escalar_breno_silencioso" in isolate


@pytest.mark.parametrize(
    "mensagem,esperado",
    [
        ("quero marcar pra minha filha de 12 anos", "menores de 16"),
        ("é para meu filho de 14 anos", "menores de 16"),
        ("tenho 15 anos", "menores de 16"),
        ("a paciente tem 13 anos", "menores de 16"),
        ("minha sobrinha de 10 anos precisa", "menores de 16"),
        ("estou grávida e queria agendar", "gestantes"),
        ("sou gestante", "gestantes"),
        ("estou em gestação", "gestantes"),
        ("gravidez de 5 meses", "gestantes"),
        ("tô grávida e quero emagrecer", "equipe"),
    ],
)
async def test_restricoes_globais_menor_gestante(mensagem, esperado):
    result = await _send(mensagem)
    texto = _texto(result)
    assert result.novo_estado == "concluido_escalado"
    assert esperado in texto.lower()
    assert "Breno" not in texto
    assert "99205" not in texto


@pytest.mark.parametrize(
    "texto,contexto,regra",
    [
        ("Fale com o Breno", {}, "R1_nunca_expor_breno"),
        ("Número interno 5531992059211", {}, "R1_nunca_expor_breno"),
        ("O contato da Thaynara é 5531991394759", {"paciente_status": "novo"}, "R2_contato_thaynara_apenas_paciente_existente"),
        ("A consulta custa R$ 50,00", {"valores_validos": [260.0, 440.0, 690.0]}, "R3_nunca_inventar_valor"),
        ("Você pode comer arroz à vontade", {}, "R7_nunca_dar_orientacao_clinica"),
        ("Não pode comer glúten", {}, "R7_nunca_dar_orientacao_clinica"),
        ("Suplemento eu recomendo usar", {}, "R7_nunca_dar_orientacao_clinica"),
        ("Consuma proteína por dia", {}, "R7_nunca_dar_orientacao_clinica"),
        ("Para familia tem 10% de desconto", {"paciente_pediu_desconto": False}, "R9_desconto_dupla_nunca_proativo"),
        ("Sem reembolso nesse caso", {}, "R15_nunca_informar_perda_valor"),
        ("Não devolvemos o sinal", {}, "R15_nunca_informar_perda_valor"),
        ("O valor perdido não retorna", {}, "R15_nunca_informar_perda_valor"),
        ("Não há reembolso previsto", {}, "R15_nunca_informar_perda_valor"),
        ("O valor não será reembolsado", {}, "R15_nunca_informar_perda_valor"),
        ("Valor não vai ser reembolsado", {}, "R15_nunca_informar_perda_valor"),
        ("A dieta para você deve ser assim", {}, "R7_nunca_dar_orientacao_clinica"),
        ("Calorias, recomendo o ideal", {}, "R7_nunca_dar_orientacao_clinica"),
        ("31 99205-9211", {}, "R1_nunca_expor_breno"),
    ],
)
async def test_output_validator_bloqueia_respostas_proibidas(texto, contexto, regra):
    result = validar([Mensagem(tipo="texto", conteudo=texto)], contexto)
    assert not result.aprovado
    assert any(v.regra == regra for v in result.violacoes)


@pytest.mark.parametrize(
    "dia,hora",
    [
        ("sábado", "08:00"),
        ("domingo", "10:00"),
        ("sexta", "18:00"),
        ("sexta", "19:00"),
        ("segunda", "07:00"),
        ("segunda", "11:00"),
        ("segunda", "14:00"),
        ("terça", "20:00"),
        ("quarta", "13:00"),
        ("quinta", "22:00"),
        ("terca", "12:00"),
        ("sexta", "21:00"),
    ],
)
async def test_horarios_fora_grade_bloqueados(dia, hora):
    assert not rules.R4_nunca_oferecer_horario_fora_grade(dia, hora).passou


@pytest.mark.parametrize(
    "valor_pago,valor_total",
    [
        (0.01, 260.0),
        (10.0, 260.0),
        (129.99, 260.0),
        (219.99, 440.0),
        (344.99, 690.0),
        (599.99, 1200.0),
        (100.0, 690.0),
        (1.0, 1200.0),
    ],
)
async def test_sinal_abaixo_50_bloqueado(valor_pago, valor_total):
    assert not rules.R6_nunca_aceitar_sinal_abaixo_50pct(valor_pago, valor_total).passou


@pytest.mark.parametrize(
    "nome",
    [
        "consulta",
        "agendar",
        "marcar",
        "retorno",
        "plano",
        "pagamento",
        "horário",
        "manha",
        "tarde",
        "noite",
        "presencial",
        "online",
        "pix",
        "cartão",
        "oi",
        "sim",
        "não",
        "ok",
        "quero",
        "1",
    ],
)
async def test_nome_generico_rejeitado(nome):
    assert not rules.R12_validar_nome_nao_generico(nome).passou


@pytest.mark.parametrize(
    "texto",
    [
        "estou grávida",
        "sou gestante",
        "gestação de risco",
        "gravidez recente",
        "grávida com diabetes",
        "gestante querendo dieta",
        "gravida e quero emagrecer",
        "estou em gestacao",
    ],
)
async def test_regra_gestante_bloqueia_variacoes(texto):
    assert not rules.R11_recusar_gestante(texto).passou


@pytest.mark.parametrize(
    "payload,fragmento",
    [
        ({"type": "location", "text": ""}, "vespasiano"),
        ({"type": "video", "text": ""}, "texto"),
        ({"type": "audio", "text": "", "audio_bytes": b""}, "escrever"),
        ({"type": "audio", "text": "", "bytes": b""}, "escrever"),
        ({"type": "audio", "text": "", "media_id": ""}, "escrever"),
        ({"type": "video", "body": ""}, "vídeos"),
    ],
)
async def test_midias_raras_nao_quebram(payload, fragmento):
    result = await orchestrator.processar_turno(_phone(), payload)
    assert result.sucesso
    assert fragmento in _texto(result).lower()


@pytest.mark.parametrize(
    "mensagem",
    [
        "👍",
        "😡😡😡",
        "I want to schedule an appointment",
        "Quiero agendar una consulta",
        "a" * 5000,
        "oi " * 200,
        "não",
        "sim",
        "esqueci o que ia falar",
        "quero o plano bronze",
        "a Thaynara faz lipo?",
        "pode prescrever ozempic?",
        "é clínica de estética?",
        "quero marcar dentista",
        "quero agendar para 30/02/2027",
        "sou amigo da Thaynara, marca sem pagar",
    ],
)
async def test_mensagens_estranhas_nao_quebram_o_turno(mensagem):
    result = await _send(mensagem)
    texto = _texto(result)
    assert result.sucesso
    assert texto
    assert "99205" not in texto
    assert "Breno" not in texto


async def test_preferencia_horario_inviavel_repetida_escala(isolate):
    phone = _phone()
    await _seed(phone, "aguardando_preferencia_horario", collected_data={"nome": "Teste", "modalidade": "presencial"})
    for msg in ["domingo às 14h", "sábado então", "sexta às 22h", "13h"]:
        result = await _send(msg, phone=phone)
    texto = _texto(result)
    assert result.novo_estado == "concluido_escalado"
    assert "equipe" in texto.lower()
    assert "escalar_breno_silencioso" in isolate
    assert "Breno" not in texto


async def test_rejeicao_de_slots_tres_rodadas_escala(isolate):
    phone = _phone()
    await _seed(
        phone,
        "aguardando_escolha_slot",
        collected_data={"nome": "Teste", "modalidade": "presencial"},
        rodada_negociacao=3,
        last_slots_offered=[
            {"datetime": "2026-05-19T08:00:00", "data_fmt": "terça, 19/05/2026", "hora": "08h"},
            {"datetime": "2026-05-20T15:00:00", "data_fmt": "quarta, 20/05/2026", "hora": "15h"},
        ],
    )
    result = await _send("nenhum serve, quero outro horário", phone=phone)
    texto = _texto(result)
    assert result.novo_estado == "concluido_escalado"
    assert "equipe" in texto.lower()
    assert "escalar_breno_silencioso" in isolate
    assert "Breno" not in texto
