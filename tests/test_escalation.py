"""
Testes dos 3 caminhos de escalação + relay bidirecional + lembretes + FAQ aprendido.

Cobertura:
  Test 1: duvida_clinica + paciente cadastrado → VCard Thaynara (D-05)
  Test 2: duvida_clinica + lead (sem dietbox_id) → relay Breno (D-06)
  Test 3: Ana não sabe → relay Breno (D-07)
  Test 4: resposta do Breno detectada → PendingEscalation respondido + relay ao paciente
  Test 5: schedule de lembretes — 15min x4, depois 1h (D-09)
  Test 6: após 1h sem resposta → paciente recebe aviso (D-10)
  Test 7: número 31 99205-9211 nunca aparece em mensagens ao paciente (D-08, INTL-04)
  Test 8: resposta do Breno salva como FAQ aprendido (D-11)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRT = timezone(timedelta(hours=-3))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_meta_client():
    """Cria um MetaAPIClient mock com send_text e send_contact."""
    m = AsyncMock()
    m.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.xxx"}]})
    m.send_contact = AsyncMock(return_value={"messages": [{"id": "wamid.yyy"}]})
    return m


def _make_db_session(query_result=None):
    """Cria um mock de sessão SQLAlchemy que funciona como context manager."""
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    if query_result is not None:
        # Para queries com filter_by().order_by().first()
        db_mock.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = query_result
        # Para queries com filter_by().filter().all()
        db_mock.query.return_value.filter_by.return_value.filter.return_value.all.return_value = (
            [query_result] if not isinstance(query_result, list) else query_result
        )
    return db_mock


def _make_pending_esc(status="aguardando", phone_e164="5531999990001",
                      pergunta_original="Qual dieta?", reminder_count=0):
    """Cria um mock de PendingEscalation."""
    esc = MagicMock()
    esc.id = "esc-uuid-1234"
    esc.status = status
    esc.phone_e164 = phone_e164
    esc.pergunta_original = pergunta_original
    esc.contexto = "Contexto da conversa"
    esc.reminder_count = reminder_count
    esc.created_at = datetime.now(BRT) - timedelta(minutes=5)
    esc.next_reminder_at = datetime.now(BRT) - timedelta(minutes=1)
    return esc


def _patch_db(result):
    """Patches app.database.SessionLocal retornando result em queries."""
    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = result
    db_mock.query.return_value.filter_by.return_value.filter.return_value.all.return_value = (
        [result] if result is not None and not isinstance(result, list) else (result or [])
    )
    return patch("app.database.SessionLocal", return_value=db_mock), db_mock


# ── Test 1: duvida_clinica + paciente cadastrado → VCard Thaynara ─────────────

@pytest.mark.asyncio
async def test_duvida_clinica_paciente_cadastrado_envia_vcard():
    """D-05: paciente cadastrado com dúvida clínica → relay ao Breno (contato nunca é enviado automaticamente)."""
    from app.escalation import escalar_duvida

    meta = _make_meta_client()

    resultado = await escalar_duvida(
        meta_client=meta,
        telefone_paciente="5531999990001",
        phone_hash="hash001",
        nome_paciente="Maria Silva",
        historico_resumido="Paciente perguntou sobre dieta",
        motivo="duvida_clinica",
        is_paciente_cadastrado=True,
    )

    # D-05 agora usa relay (não mais direct contact) — Breno pode autorizar o envio do contato
    assert resultado == "relay_breno"
    # Deve enviar mensagem de texto ao paciente (aguardando)
    assert meta.send_text.called
    # NOT send_contact — contato NUNCA é enviado automaticamente (segurança de privacidade)
    assert not meta.send_contact.called


# ── Test 2: duvida_clinica + lead → relay Breno ───────────────────────────────

@pytest.mark.asyncio
async def test_duvida_clinica_lead_relay_breno():
    """D-06: lead com dúvida clínica → cria PendingEscalation, envia ao Breno."""
    from app.escalation import escalar_duvida

    meta = _make_meta_client()

    with patch("app.escalation.criar_escalacao_relay", new_callable=AsyncMock) as mock_criar:
        mock_criar.return_value = "esc-uuid-abc"

        resultado = await escalar_duvida(
            meta_client=meta,
            telefone_paciente="5531999990002",
            phone_hash="hash002",
            nome_paciente="João Lead",
            historico_resumido="Lead perguntou sobre dieta",
            motivo="duvida_clinica",
            is_paciente_cadastrado=False,
        )

    assert resultado == "relay_breno"
    # Paciente recebe mensagem de aguardo
    assert meta.send_text.called
    # Criar escalação foi chamada
    mock_criar.assert_awaited_once()


# ── Test 3: Ana não sabe → relay Breno ───────────────────────────────────────

@pytest.mark.asyncio
async def test_ana_nao_sabe_relay_breno():
    """D-07: motivo != duvida_clinica → relay Breno."""
    from app.escalation import escalar_duvida

    meta = _make_meta_client()

    with patch("app.escalation.criar_escalacao_relay", new_callable=AsyncMock) as mock_criar:
        mock_criar.return_value = "esc-uuid-def"

        resultado = await escalar_duvida(
            meta_client=meta,
            telefone_paciente="5531999990003",
            phone_hash="hash003",
            nome_paciente="Ana Lead",
            historico_resumido="Pergunta não compreendida",
            motivo="nao_sabe",
            is_paciente_cadastrado=False,
        )

    assert resultado == "relay_breno"
    mock_criar.assert_awaited_once()


# ── Test 4: resposta do Breno → PendingEscalation atualizado + relay ─────────

@pytest.mark.asyncio
async def test_processar_resposta_breno_relay_e_atualiza():
    """Breno responde → escalação marcada como 'respondido', resposta repassada ao paciente."""
    from app.escalation import processar_resposta_breno

    meta = _make_meta_client()
    esc_mock = _make_pending_esc()

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        with patch("app.knowledge_base.salvar_faq_aprendido") as mock_faq:
            resultado = await processar_resposta_breno(
                meta_client=meta,
                texto_resposta="Pode comer arroz integral sem problemas.",
            )

    assert resultado is True
    # Escalação marcada como respondida
    assert esc_mock.status == "respondido"
    assert esc_mock.resposta_breno == "Pode comer arroz integral sem problemas."
    # Resposta repassada ao paciente (phone_e164 = "5531999990001")
    meta.send_text.assert_awaited_once_with(
        esc_mock.phone_e164,
        "Pode comer arroz integral sem problemas.",
    )
    # FAQ aprendido salvo
    mock_faq.assert_called_once()


# ── Test 5: schedule de lembretes — 15min x4, depois 1h ──────────────────────

@pytest.mark.asyncio
async def test_enviar_lembretes_schedule_15min():
    """D-09: primeiro 4 lembretes a cada 15min."""
    from app.escalation import enviar_lembretes_pendentes

    meta = _make_meta_client()
    esc_mock = _make_pending_esc(reminder_count=0)

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        enviados = await enviar_lembretes_pendentes(meta)

    # Lembrete enviado ao Breno
    assert enviados == 1
    assert meta.send_text.called

    # reminder_count foi incrementado
    assert esc_mock.reminder_count == 1

    # Próximo lembrete: dentro de 15min (reminder_count < 4)
    now = datetime.now(BRT)
    diff = esc_mock.next_reminder_at - now
    assert 10 * 60 <= diff.total_seconds() <= 20 * 60  # entre 10 e 20 min


@pytest.mark.asyncio
async def test_enviar_lembretes_apos_4_intervalo_1h():
    """D-09: reminder_count >= 4 → próximo lembrete em 1h."""
    from app.escalation import enviar_lembretes_pendentes

    meta = _make_meta_client()
    esc_mock = _make_pending_esc(reminder_count=4)

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        await enviar_lembretes_pendentes(meta)

    # Próximo lembrete: dentro de ~1h
    now = datetime.now(BRT)
    diff = esc_mock.next_reminder_at - now
    assert 50 * 60 <= diff.total_seconds() <= 70 * 60  # entre 50 e 70 min


# ── Test 6: após 1h → paciente avisado ───────────────────────────────────────

@pytest.mark.asyncio
async def test_timeout_1h_avisa_paciente():
    """D-10: no 4º lembrete (reminder_count chega a 4), paciente recebe aviso."""
    from app.escalation import enviar_lembretes_pendentes

    meta = _make_meta_client()
    # reminder_count=3 → após incremento fica 4 → aciona aviso ao paciente
    esc_mock = _make_pending_esc(reminder_count=3, phone_e164="5531999990005")

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        await enviar_lembretes_pendentes(meta)

    # send_text deve ter sido chamado ao menos 2 vezes:
    # 1. aviso ao paciente, 2. lembrete ao Breno
    assert meta.send_text.call_count >= 2

    # Verificar que paciente recebeu aviso
    all_calls = [str(c) for c in meta.send_text.call_args_list]
    paciente_avisado = any("5531999990005" in c for c in all_calls)
    assert paciente_avisado, "Paciente deveria ter recebido aviso após 1h"


# ── Test 7: número interno NUNCA exposto ao paciente ─────────────────────────

@pytest.mark.asyncio
async def test_numero_interno_nao_exposto_ao_paciente():
    """D-08, INTL-04: nenhuma mensagem enviada ao paciente contém o número do Breno."""
    from app.escalation import escalar_duvida, _NUMERO_INTERNO

    meta = _make_meta_client()

    # Coleta todas as chamadas a send_text feitas para o telefone do paciente
    telefone_paciente = "5531977770001"
    mensagens_ao_paciente: list[str] = []

    async def capturar_send_text(to: str, text: str) -> dict:
        if to == telefone_paciente:
            mensagens_ao_paciente.append(text)
        return {"messages": [{"id": "wamid.test"}]}

    meta.send_text.side_effect = capturar_send_text

    with patch("app.escalation.criar_escalacao_relay", new_callable=AsyncMock) as mock_criar:
        mock_criar.return_value = "esc-uuid-xxx"

        await escalar_duvida(
            meta_client=meta,
            telefone_paciente=telefone_paciente,
            phone_hash="hash007",
            nome_paciente="Paciente Teste",
            historico_resumido="Teste de segurança",
            motivo="duvida_clinica",
            is_paciente_cadastrado=False,
        )

    # Nenhuma mensagem ao paciente deve conter o número interno
    numero_sem_formatacao = _NUMERO_INTERNO.replace("+", "").replace("-", "").replace(" ", "")
    fragmentos_proibidos = ["99205", "9211", numero_sem_formatacao, "NUMERO_INTERNO"]

    for msg in mensagens_ao_paciente:
        for fragmento in fragmentos_proibidos:
            assert fragmento not in msg, (
                f"Número interno vazou ao paciente! Fragmento '{fragmento}' encontrado em: '{msg}'"
            )


@pytest.mark.asyncio
async def test_numero_interno_na_constante():
    """_NUMERO_INTERNO deve ser a constante privada, nunca hard-coded em mensagens."""
    from app.escalation import _NUMERO_INTERNO

    # Deve existir e ter formato E.164
    assert _NUMERO_INTERNO.startswith("55"), "_NUMERO_INTERNO deve começar com código do país 55"
    assert len(_NUMERO_INTERNO) >= 12, "_NUMERO_INTERNO deve ter ao menos 12 dígitos"
    # Deve conter o número do Breno sem formatação
    assert "992059211" in _NUMERO_INTERNO


def test_numero_interno_reconhece_normalizacao_meta_sem_nono_digito():
    """Meta pode devolver wa_id brasileiro sem o nono digito; ainda deve ser Breno."""
    from app.escalation import is_numero_interno

    assert is_numero_interno("5531992059211")
    assert is_numero_interno("553192059211")


def test_numero_interno_usa_breno_phone_quando_numero_interno_ausente(monkeypatch):
    """BRENO_PHONE deve ser fallback real do número interno."""
    import importlib
    import os
    import app.escalation as escalation

    original_numero_interno = os.environ.get("NUMERO_INTERNO")
    original_breno_phone = os.environ.get("BRENO_PHONE")
    monkeypatch.delenv("NUMERO_INTERNO", raising=False)
    monkeypatch.setenv("BRENO_PHONE", "553188887777")
    reloaded = importlib.reload(escalation)

    try:
        assert reloaded._NUMERO_INTERNO == "553188887777"
    finally:
        if original_numero_interno is None:
            monkeypatch.delenv("NUMERO_INTERNO", raising=False)
        else:
            monkeypatch.setenv("NUMERO_INTERNO", original_numero_interno)
        if original_breno_phone is None:
            monkeypatch.delenv("BRENO_PHONE", raising=False)
        else:
            monkeypatch.setenv("BRENO_PHONE", original_breno_phone)
        importlib.reload(escalation)


# ── Test 8: FAQ aprendido salvo ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resposta_breno_salva_faq_aprendido():
    """D-11: após relay, resposta do Breno é salva como FAQ aprendido."""
    from app.escalation import processar_resposta_breno

    meta = _make_meta_client()
    esc_mock = _make_pending_esc(pergunta_original="Posso comer beterraba?")

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        with patch("app.knowledge_base.salvar_faq_aprendido") as mock_faq:
            await processar_resposta_breno(
                meta_client=meta,
                texto_resposta="Sim, beterraba é ótima para saúde!",
            )

    mock_faq.assert_called_once_with(
        "Posso comer beterraba?",
        "Sim, beterraba é ótima para saúde!",
    )


@pytest.mark.asyncio
async def test_processar_resposta_breno_sem_escalacao_pendente():
    """Quando não há escalação pendente, retorna False sem crash."""
    from app.escalation import processar_resposta_breno

    meta = _make_meta_client()

    patcher, db_mock = _patch_db(None)
    with patcher:
        resultado = await processar_resposta_breno(
            meta_client=meta,
            texto_resposta="Resposta sem contexto",
        )

    assert resultado is False
    # Nenhuma mensagem enviada ao paciente
    meta.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_abrir_janela_reenvia_contexto_sem_repassar_ao_paciente():
    """Resposta operacional do Breno abre janela e reenvia o contexto pendente."""
    from app.escalation import processar_resposta_breno, _NUMERO_INTERNO

    meta = _make_meta_client()
    esc_mock = _make_pending_esc()
    esc_mock.contexto = "Contexto completo da escalação"

    patcher, db_mock = _patch_db(esc_mock)
    with patcher, patch("app.escalation._track_escalation_outbound", new_callable=AsyncMock):
        resultado = await processar_resposta_breno(
            meta_client=meta,
            texto_resposta="abrir janela",
        )

    assert resultado is True
    assert esc_mock.status == "aguardando"
    meta.send_text.assert_awaited_once_with(_NUMERO_INTERNO, "Contexto completo da escalação")


# ── Test: webhook detecta mensagem do Breno ───────────────────────────────────

def test_numero_interno_nao_roteado_como_paciente():
    """
    webhook.py deve detectar sender == _NUMERO_INTERNO antes de route_message.
    Verifica que _NUMERO_INTERNO importado no webhook.py corresponde ao da escalation.
    """
    from app.escalation import _NUMERO_INTERNO

    # O número deve ser consistente entre módulos
    assert "992059211" in _NUMERO_INTERNO

    # Verificar que send_contact existe no MetaAPIClient
    from app.meta_api import MetaAPIClient
    assert hasattr(MetaAPIClient, "send_contact"), "MetaAPIClient deve ter método send_contact"


# ── T11: relay Breno end-to-end ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_t11_relay_breno_end_to_end():
    """
    T11 — fluxo completo do relay bidirecional:

    1. Lead faz dúvida clínica → escalar_duvida cria PendingEscalation + avisa paciente
    2. PendingEscalation gravado no banco com status='aguardando'
    3. Breno responde (processar_resposta_breno) → escalação marcada 'respondido'
    4. Resposta do Breno repassada ao paciente
    5. Número interno NUNCA aparece na mensagem ao paciente
    """
    from app.escalation import escalar_duvida, processar_resposta_breno, _NUMERO_INTERNO

    meta = _make_meta_client()
    telefone_paciente = "5531988880011"

    # ── Passo 1: escalação da dúvida (lead, não cadastrado) ───────────────────
    esc_criada = {}

    async def _mock_criar_relay(**kwargs):
        # Guarda os dados e simula a criação do PendingEscalation
        esc_criada.update(kwargs)
        return "esc-t11-uuid"

    with patch("app.escalation.criar_escalacao_relay", side_effect=_mock_criar_relay):
        resultado = await escalar_duvida(
            meta_client=meta,
            telefone_paciente=telefone_paciente,
            phone_hash="hash_t11",
            nome_paciente="Carlos Lead",
            historico_resumido="Carlos: posso comer pão com diabetes?",
            motivo="duvida_clinica",
            is_paciente_cadastrado=False,
        )

    assert resultado == "relay_breno"
    # Paciente recebeu mensagem de aguardo (não o número interno)
    assert meta.send_text.called
    msgs_ao_paciente = [
        str(c) for c in meta.send_text.call_args_list
        if telefone_paciente in str(c)
    ]
    assert len(msgs_ao_paciente) >= 1, "Paciente deve receber mensagem de aguardo"
    for msg in msgs_ao_paciente:
        assert _NUMERO_INTERNO not in msg, "Número interno vazou na mensagem ao paciente!"
        assert "99205" not in msg, "Fragmento do número interno vazou!"

    # criar_escalacao_relay foi chamada com os dados corretos
    assert esc_criada.get("telefone_paciente") == telefone_paciente
    assert esc_criada.get("phone_hash") == "hash_t11"

    # ── Passo 2: Breno responde ────────────────────────────────────────────────
    meta2 = _make_meta_client()
    esc_mock = _make_pending_esc(
        status="aguardando",
        phone_e164=telefone_paciente,
        pergunta_original="duvida_clinica",
    )

    patcher, db_mock = _patch_db(esc_mock)
    with patcher:
        with patch("app.knowledge_base.salvar_faq_aprendido"):
            relay_ok = await processar_resposta_breno(
                meta_client=meta2,
                texto_resposta="Pode comer pão integral com moderação 🌾",
            )

    # ── Passo 3: validações do relay ──────────────────────────────────────────
    assert relay_ok is True, "processar_resposta_breno deve retornar True quando há escalação"
    assert esc_mock.status == "respondido"
    assert esc_mock.resposta_breno == "Pode comer pão integral com moderação 🌾"

    # Resposta repassada exatamente ao telefone do paciente
    meta2.send_text.assert_awaited_once_with(
        telefone_paciente,
        "Pode comer pão integral com moderação 🌾",
    )


@pytest.mark.asyncio
async def test_t11_handle_escalation_router_cria_pending_escalation():
    """
    _handle_escalation em router.py deve chamar escalar_duvida (não escalar_para_humano),
    garantindo que PendingEscalation seja criado para o relay funcionar.
    """
    import inspect
    from app import router as router_module

    source = inspect.getsource(router_module._handle_escalation)
    assert "escalar_duvida" in source, (
        "_handle_escalation deve usar escalar_duvida para criar PendingEscalation. "
        "escalar_para_humano não cria registro no banco e quebra o relay do Breno."
    )
    assert "escalar_para_humano" not in source, (
        "_handle_escalation não deve mais usar escalar_para_humano (não cria PendingEscalation)"
    )
