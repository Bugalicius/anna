"""
Testes do roteamento — engine + router integration.
Todos os testes usam mock do Claude e do Redis para não fazer chamadas reais.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ── Fixtures para testes de route_message ────────────────────────────────────

def _make_contact(
    first_name: str | None = None,
    collected_name: str | None = None,
    push_name: str | None = None,
    stage: str = "presenting",
):
    contact = MagicMock()
    contact.first_name = first_name
    contact.collected_name = collected_name
    contact.push_name = push_name
    contact.stage = stage
    contact.id = "contact-id-123"
    return contact


def _make_db_mock(contact):
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.query.return_value.filter_by.return_value.first.return_value = contact
    return db


def _make_resultado(msgs: list):
    """Cria mock de ResultadoTurno com lista de mensagens."""
    resultado = MagicMock()
    resultado.mensagens_enviadas = [MagicMock(conteudo=m) for m in msgs]
    resultado.sucesso = True
    resultado.novo_estado = "inicio"
    resultado.erro = None
    return resultado


@pytest.fixture
def state_mgr_mock():
    mgr = MagicMock()
    mgr.load = AsyncMock(return_value=None)
    mgr.save = AsyncMock()
    mgr.delete = AsyncMock()
    return mgr


@pytest.fixture
def meta_mock():
    meta = MagicMock()
    meta.send_text = AsyncMock()
    return meta


# ── Helpers de estado ────────────────────────────────────────────────────────


def _make_state(
    goal: str = "desconhecido",
    status: str = "coletando",
    nome: str | None = None,
    id_agenda: str | None = None,
):
    """Cria um state dict mínimo para mocks de load_state."""
    return {
        "goal": goal,
        "status": status,
        "collected_data": {"nome": nome},
        "appointment": {"id_agenda": id_agenda},
        "history": [],
        "flags": {},
    }


# ── Test 1: engine.handle_message chamado com args corretos ──────────────────

@pytest.mark.asyncio
async def test_engine_chamado_com_args_corretos():
    """route_message deve chamar engine.handle_message(phone_hash, text, phone=phone)."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["oi"])) as mock_engine, \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_engine.assert_called_once_with(
        phone="5511999",
        mensagem={"type": "text", "text": "oi", "from": "5511999", "id": "msg-id-1"},
    )


# ── Test 2: respostas de texto enviadas ao paciente ──────────────────────────

@pytest.mark.asyncio
async def test_respostas_texto_enviadas():
    """Strings retornadas pelo engine são enviadas via meta.send_text."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["msg A", "msg B"])), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    assert meta.send_text.call_count == 2
    textos = [call.args[1] for call in meta.send_text.call_args_list]
    assert textos == ["msg A", "msg B"]


# ── Test 3: sentinel de escalação aciona escalar_duvida ──────────────────────

@pytest.mark.asyncio
async def test_sentinel_escalacao():
    """v2 trata escalação internamente — route_message deve completar sem crash."""
    from app.router import route_message

    contact = _make_contact(stage="presenting")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado([])) as mock_turno, \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "tenho diabetes", "msg-id-1")

    mock_turno.assert_awaited_once()


# ── Test 4: paciente de retorno tem nome pré-populado no state ────────────────

@pytest.mark.asyncio
async def test_paciente_retorno_prepopula_nome():
    """Contato com collected_name deve ter nome pré-populado no state antes do engine."""
    from app.router import route_message

    contact = _make_contact(
        first_name="Marcela", collected_name="Marcela Silva", stage="agendado"
    )
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    state_vazio = _make_state()  # nome=None
    state_gravado: dict = {}

    async def fake_save(phone_hash, state):
        state_gravado.update(state)

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["olá"])), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=state_vazio), \
         patch("app.conversation.state.save_state", side_effect=fake_save):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    # _reconhecer_paciente_retorno deve ter preenchido o nome no state
    assert state_vazio["collected_data"].get("nome") == "Marcela Silva"


# ── Test 5: contato não encontrado retorna sem crash ─────────────────────────

@pytest.mark.asyncio
async def test_contato_nao_encontrado_retorna_sem_crash():
    """Quando contact não existe no banco, route_message retorna silenciosamente."""
    from app.router import route_message

    db_mock = MagicMock()
    db_mock.__enter__ = MagicMock(return_value=db_mock)
    db_mock.__exit__ = MagicMock(return_value=False)
    db_mock.query.return_value.filter_by.return_value.first.return_value = None

    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock) as mock_engine:
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_engine.assert_not_called()
    meta.send_text.assert_not_called()


# ── Test 6: _atualizar_contact persiste nome e stage após engine ──────────────

@pytest.mark.asyncio
async def test_atualizar_contact_persiste_nome_e_stage():
    """Após engine processar, nome e stage do Contact são atualizados no banco."""
    from app.router import route_message

    contact = _make_contact(stage="presenting", collected_name=None)
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    state_concluido = _make_state(
        goal="agendar_consulta", status="concluido",
        nome="Ana Maria", id_agenda="agenda-001",
    )

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["agendado!"])), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=state_concluido), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "ok", "msg-id-1")

    assert contact.collected_name == "Ana Maria"
    assert contact.first_name == "Ana"
    assert contact.stage == "agendado"


@pytest.mark.asyncio
async def test_atualizar_contact_cancelamento_mantem_paciente_reconhecivel():
    from app.router import _atualizar_contact

    contact = _make_contact(stage="agendado", collected_name="Ana Maria")
    db_mock = _make_db_mock(contact)
    state_cancelado = _make_state(goal="cancelar", status="concluido", nome="Ana Maria")

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.conversation.state.load_state", new_callable=AsyncMock, return_value=state_cancelado), \
         patch("app.conversation.state.delete_state", new_callable=AsyncMock) as mock_delete:
        await _atualizar_contact("hash123")

    assert contact.stage == "cancelado"
    mock_delete.assert_awaited_once_with("hash123")


@pytest.mark.asyncio
async def test_enviar_respostas_registra_interativos_no_chatwoot():
    from app.router import _enviar_respostas

    meta = MagicMock()
    meta.send_interactive_buttons = AsyncMock()

    resposta = {
        "_interactive": "button",
        "body": "Escolha uma opção",
        "buttons": [{"id": "a", "title": "A"}],
    }

    with patch("app.chatwoot_bridge.log_bot_message", new_callable=AsyncMock) as mock_log:
        await _enviar_respostas(meta, "5511999", "hash123", [resposta], {})

    meta.send_interactive_buttons.assert_awaited_once()
    mock_log.assert_awaited_once_with("5511999", "Escolha uma opção")


@pytest.mark.asyncio
async def test_enviar_respostas_mensagem_v2_com_quatro_opcoes_usa_lista():
    from app.conversation.models import Mensagem
    from app.router import _enviar_respostas

    meta = MagicMock()
    meta.send_interactive_list = AsyncMock()

    msg = Mensagem(
        tipo="botoes",
        conteudo="Qual seu objetivo?",
        botoes=[
            {"id": "obj_emagrecer", "label": "Emagrecer"},
            {"id": "obj_ganhar_massa", "label": "Ganhar massa"},
            {"id": "obj_lipedema", "label": "Lipedema"},
            {"id": "obj_outro", "label": "Outro objetivo"},
        ],
    )

    with patch("app.router._log_bot_message_safe", new_callable=AsyncMock):
        await _enviar_respostas(meta, "5511999", "hash123", [msg], {})

    meta.send_interactive_list.assert_awaited_once()
    rows = meta.send_interactive_list.await_args.args[3]
    assert [r["title"] for r in rows] == ["Emagrecer", "Ganhar massa", "Lipedema", "Outro objetivo"]


@pytest.mark.asyncio
async def test_bioimpedancia_durante_status_responde_e_retoma_botoes():
    from app.conversation import orchestrator
    from app.conversation.state import delete_state

    phone = "559999000222"
    await delete_state(orchestrator._phone_hash(phone))
    await orchestrator.processar_turno(phone, {"type": "text", "text": "oi", "from": phone, "id": "1"})
    await orchestrator.processar_turno(phone, {"type": "text", "text": "Ana Teste", "from": phone, "id": "2"})

    result = await orchestrator.processar_turno(
        phone,
        {"type": "text", "text": "a thay faz biopendencia?", "from": phone, "id": "3"},
    )

    assert result.novo_estado == "aguardando_status_paciente"
    assert "bioimpedância" in result.mensagens_enviadas[0].conteudo
    assert result.mensagens_enviadas[1].tipo == "botoes"


@pytest.mark.asyncio
async def test_bioimpedancia_e_primeira_consulta_agrupadas_avanca_para_objetivo():
    from app.conversation import orchestrator
    from app.conversation.state import delete_state

    phone = "559999000333"
    await delete_state(orchestrator._phone_hash(phone))
    await orchestrator.processar_turno(phone, {"type": "text", "text": "oi", "from": phone, "id": "1"})
    await orchestrator.processar_turno(phone, {"type": "text", "text": "Ana Teste", "from": phone, "id": "2"})

    result = await orchestrator.processar_turno(
        phone,
        {"type": "text", "text": "a thay faz biopendencia?\nprimeira consulta", "from": phone, "id": "3"},
    )

    assert result.novo_estado == "aguardando_objetivo"
    assert "bioimpedância" in result.mensagens_enviadas[0].conteudo
    assert result.mensagens_enviadas[1].tipo == "botoes"
    assert [b.id for b in result.mensagens_enviadas[1].botoes] == [
        "obj_emagrecer",
        "obj_ganhar_massa",
        "obj_lipedema",
        "obj_outro",
    ]


# ── Test 7: remarketing — contato no stage remarketing cancela fila ───────────

@pytest.mark.asyncio
async def test_remarketing_stage_cancela_fila_pendente():
    """Contato em stage=remarketing deve ter cancel_pending_remarketing chamado."""
    from app.router import route_message

    contact = _make_contact(stage="remarketing")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.router.cancel_pending_remarketing") as mock_cancel, \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["olá"])), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    mock_cancel.assert_called_once()


# ── Test 8: Redis indisponível não trava o sistema ────────────────────────────

@pytest.mark.asyncio
async def test_redis_failure_nao_trava():
    """load_state retornando estado vazio (Redis indisponível) não causa crash."""
    from app.router import route_message

    contact = _make_contact(stage="new")
    db_mock = _make_db_mock(contact)
    meta = MagicMock()
    meta.send_text = AsyncMock()

    with patch("app.router.SessionLocal", return_value=db_mock), \
         patch("app.meta_api.MetaAPIClient", return_value=meta), \
         patch("app.remarketing.cancel_pending_remarketing"), \
         patch("app.router.processar_turno",
               new_callable=AsyncMock, return_value=_make_resultado(["Olá! Bem-vinda!"])), \
         patch("app.conversation.state.load_state",
               new_callable=AsyncMock, return_value=_make_state()), \
         patch("app.conversation.state.save_state", new_callable=AsyncMock):
        # Não deve lançar exceção
        await route_message("5511999", "hash123", "oi", "msg-id-1")

    meta.send_text.assert_called()


@pytest.mark.asyncio
async def test_enviar_midia_refaz_upload_quando_media_id_em_cache_falha():
    """Em caso de 400/erro com media_id em cache, o router deve refazer upload e reenviar."""
    from app.router import _enviar_midia

    meta = MagicMock()
    meta.upload_media = AsyncMock(side_effect=["cached-media-id", "fresh-media-id"])
    meta.send_image = AsyncMock(side_effect=[Exception("400 Bad Request"), None])

    with patch("app.router._get_or_upload_media", new_callable=AsyncMock) as mock_get_media:
        mock_get_media.side_effect = ["cached-media-id", "fresh-media-id"]
        await _enviar_midia(meta, "5511999", {
            "media_type": "image",
            "media_key": "img_preparo_presencial",
            "caption": "Teste",
        })

    assert mock_get_media.await_args_list[0].kwargs.get("force_refresh", False) is False
    assert mock_get_media.await_args_list[1].kwargs.get("force_refresh") is True
    assert meta.send_image.await_count == 2
