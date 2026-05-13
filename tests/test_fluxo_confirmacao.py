"""
Testes — Fluxo 4: Confirmação de Presença

Cenários cobertos (12):
  1.  job_confirmacao_semanal é async
  2.  job_lembrete_vespera é async
  3.  job_followup_check é async
  4.  job_confirmacao_semanal envia mensagem para cada consulta encontrada
  5.  job_confirmacao_semanal não envia quando não há consultas
  6.  template presencial contém "short e top" e botões corretos
  7.  template online contém instrução de pesagem
  8.  template online dispara envio de contato da Thaynara
  9.  job_lembrete_vespera envia texto simples (sem botões)
  10. botão confirmar_presenca retorna "Confirmado então!" e atualiza estado
  11. _get_botao_id detecta remarcar_consulta corretamente
  12. follow-up 24h envia "{nome}?" para pendentes sem resposta
  13. paciente que já recebeu follow-up não recebe segundo
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

BRT = timezone(timedelta(hours=-3))


# ── 1–3. Coroutines ──────────────────────────────────────────────────────────

def test_job_confirmacao_semanal_e_coroutine():
    from app.conversation.scheduler import job_confirmacao_semanal
    assert asyncio.iscoroutinefunction(job_confirmacao_semanal)


def test_job_lembrete_vespera_e_coroutine():
    from app.conversation.scheduler import job_lembrete_vespera
    assert asyncio.iscoroutinefunction(job_lembrete_vespera)


def test_job_followup_check_e_coroutine():
    from app.conversation.scheduler import job_followup_check
    assert asyncio.iscoroutinefunction(job_followup_check)


# ── 4. Envia para cada consulta ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirmacao_semanal_envia_para_cada_consulta():
    dt = datetime(2026, 5, 18, 9, 0, tzinfo=BRT)
    consultas = [
        {"primeiro_nome": "Maria", "telefone": "5531999990001", "datetime": dt, "tipo": "consulta_presencial"},
        {"primeiro_nome": "Joao", "telefone": "5531999990002", "datetime": dt, "tipo": "consulta_presencial"},
    ]
    mock_client = AsyncMock()
    mock_client.send_interactive_buttons = AsyncMock(return_value={})

    with (
        patch("app.agents.dietbox_worker.buscar_consultas_periodo", return_value=consultas),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
        patch("app.conversation.scheduler._salvar_confirmacao_pendente", AsyncMock()),
    ):
        from app.conversation.scheduler import job_confirmacao_semanal
        await job_confirmacao_semanal()

    assert mock_client.send_interactive_buttons.call_count == 2


# ── 5. Sem consultas — não envia ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confirmacao_semanal_sem_consultas_nao_envia():
    mock_client = AsyncMock()

    with (
        patch("app.agents.dietbox_worker.buscar_consultas_periodo", return_value=[]),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
    ):
        from app.conversation.scheduler import job_confirmacao_semanal
        await job_confirmacao_semanal()

    mock_client.send_interactive_buttons.assert_not_called()


# ── 6. Template presencial: short/top e botões corretos ─────────────────────

def test_template_presencial_contem_short_e_top_e_botoes():
    from app.conversation.scheduler import BOTOES_CONFIRMACAO, _template_presencial

    texto = _template_presencial("Ana", "segunda-feira", "19/05/2026", "09:00")
    assert "short" in texto.lower()
    assert "top" in texto.lower()
    assert "Aura Clinic" in texto

    ids = [b["id"] for b in BOTOES_CONFIRMACAO]
    assert "confirmar_presenca" in ids
    assert "remarcar_consulta" in ids


# ── 7. Template online: instrução de pesagem ─────────────────────────────────

def test_template_online_contem_instrucao_pesagem():
    from app.conversation.scheduler import _template_online

    texto = _template_online("Ana", "consulta", "segunda-feira", "19/05/2026", "09:00")
    assert "Pese-se" in texto or "pese" in texto.lower()
    assert "internet" in texto.lower()


# ── 8. Template online → dispara contato da Thaynara ─────────────────────────

@pytest.mark.asyncio
async def test_template_online_envia_contato_thaynara():
    dt = datetime(2026, 5, 18, 10, 0, tzinfo=BRT)
    consultas = [
        {"primeiro_nome": "Cla", "telefone": "5531999990003", "datetime": dt, "tipo": "consulta_online"},
    ]
    mock_client = AsyncMock()
    mock_client.send_interactive_buttons = AsyncMock(return_value={})
    mock_client.send_contact = AsyncMock(return_value={})

    with (
        patch("app.agents.dietbox_worker.buscar_consultas_periodo", return_value=consultas),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
        patch("app.conversation.scheduler._salvar_confirmacao_pendente", AsyncMock()),
    ):
        from app.conversation.scheduler import job_confirmacao_semanal
        await job_confirmacao_semanal()

    mock_client.send_contact.assert_awaited_once()
    # Verifica que o corpo contém instrução de pesagem
    call_args = mock_client.send_interactive_buttons.call_args
    body = call_args.kwargs.get("body") or call_args.args[1]
    assert "Pese-se" in body or "pese" in body.lower()


# ── 9. Lembrete véspera — texto simples, sem botões ──────────────────────────

@pytest.mark.asyncio
async def test_lembrete_vespera_envia_texto_simples():
    dt = datetime(2026, 5, 19, 8, 0, tzinfo=BRT)
    consultas = [
        {"primeiro_nome": "Bia", "telefone": "5531999990004", "datetime": dt, "tipo": "consulta_presencial"},
    ]
    mock_client = AsyncMock()
    mock_client.send_text = AsyncMock(return_value={})

    with (
        patch("app.agents.dietbox_worker.buscar_consultas_periodo", return_value=consultas),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
    ):
        from app.conversation.scheduler import job_lembrete_vespera
        await job_lembrete_vespera()

    mock_client.send_text.assert_awaited_once()
    mock_client.send_interactive_buttons.assert_not_called()
    call_args = mock_client.send_text.call_args
    text = call_args.kwargs.get("text") or call_args.args[1]
    assert "amanhã" in text
    assert "08:00" in text


# ── 10. Botão confirmar_presenca → "Confirmado então!" ───────────────────────

@pytest.mark.asyncio
async def test_handle_confirmar_presenca_retorna_confirmado():
    from app.conversation.orchestrator import _handle_confirmar_presenca

    state = {"estado": "confirmacao_enviada", "collected_data": {}, "flags": {}}
    mock_result = MagicMock(sucesso=True, dados={"confirmada": True}, erro=None)

    with (
        patch("app.conversation.tools.registry.call_tool", AsyncMock(return_value=mock_result)),
        patch("app.conversation.scheduler.limpar_confirmacao_pendente", AsyncMock()),
    ):
        msgs, novo_estado = await _handle_confirmar_presenca(state, "5531999999999")

    assert novo_estado == "confirmacao_concluida"
    assert any("Confirmado" in m.conteudo for m in msgs)
    assert state["confirmacao"]["status"] == "confirmada"


# ── 11. _get_botao_id detecta remarcar_consulta ───────────────────────────────

def test_get_botao_id_detecta_remarcar_consulta():
    from app.conversation.orchestrator import _get_botao_id

    mensagem = {
        "type": "interactive",
        "interactive": {"button_reply": {"id": "remarcar_consulta", "title": "Preciso remarcar 📅"}},
        "text": "remarcar_consulta",
    }
    assert _get_botao_id(mensagem) == "remarcar_consulta"


def test_get_botao_id_detecta_confirmar_presenca():
    from app.conversation.orchestrator import _get_botao_id

    mensagem = {
        "type": "interactive",
        "interactive": {"button_reply": {"id": "confirmar_presenca", "title": "Confirmar ✅"}},
        "text": "confirmar_presenca",
    }
    assert _get_botao_id(mensagem) == "confirmar_presenca"


# ── 12. Follow-up 24h envia "{nome}?" ────────────────────────────────────────

@pytest.mark.asyncio
async def test_followup_24h_envia_nome_com_interrogacao():
    from app.conversation.scheduler import job_followup_check

    agora = datetime.now(BRT)
    enviada_ha_25h = (agora - timedelta(hours=25)).isoformat()
    dt_consulta_futuro = (agora + timedelta(days=2)).isoformat()

    pendente = {
        "nome": "Carla",
        "telefone": "5531999990005",
        "enviada_em": enviada_ha_25h,
        "dt_consulta": dt_consulta_futuro,
        "followup_enviado": False,
    }

    mock_client = AsyncMock()
    mock_client.send_text = AsyncMock(return_value={})

    with (
        patch("app.conversation.scheduler._buscar_pendentes", AsyncMock(return_value=[pendente])),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
        patch("app.conversation.scheduler._marcar_followup_enviado", AsyncMock()),
        patch("app.conversation.tools.registry.call_tool", AsyncMock()),
    ):
        await job_followup_check()

    mock_client.send_text.assert_awaited_once()
    call_args = mock_client.send_text.call_args
    text = call_args.kwargs.get("text") or call_args.args[1]
    assert "Carla?" in text


# ── 13. Follow-up já enviado — não envia segundo ─────────────────────────────

@pytest.mark.asyncio
async def test_followup_nao_reenviado_se_ja_enviado():
    from app.conversation.scheduler import job_followup_check

    agora = datetime.now(BRT)
    enviada_ha_25h = (agora - timedelta(hours=25)).isoformat()
    dt_consulta_futuro = (agora + timedelta(days=2)).isoformat()

    pendente = {
        "nome": "Davi",
        "telefone": "5531999990006",
        "enviada_em": enviada_ha_25h,
        "dt_consulta": dt_consulta_futuro,
        "followup_enviado": True,  # já enviado
    }

    mock_client = AsyncMock()

    with (
        patch("app.conversation.scheduler._buscar_pendentes", AsyncMock(return_value=[pendente])),
        patch("app.meta_api.MetaAPIClient", return_value=mock_client),
        patch("app.conversation.tools.registry.call_tool", AsyncMock()),
    ):
        await job_followup_check()

    mock_client.send_text.assert_not_called()
