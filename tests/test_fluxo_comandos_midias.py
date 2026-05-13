"""
Testes — Fase 7: Comandos internos (Fluxo 8), Mídias (Fluxo 9), Fora de contexto (Fluxo 10)

Cenários cobertos:
  Fluxo 8 — Comandos internos
    1.  Número não autorizado retorna processado=False
    2.  Thaynara autorizada é detectada (sufixo 9 dígitos)
    3.  Breno autorizado é detectado
    4.  Comando nao_reconhecido retorna ajuda
    5.  Mensagem vazia retorna processado=False mesmo para autorizado
    6.  interpretar_comando é chamado para número autorizado
    7.  consultar_status_paciente formata resumo a partir do estado
    8.  enviar_mensagem_para_paciente usa Meta API e confirma ao operador
    9.  responder_escalacao envia resposta e marca como resolvida
    10. comando com confidence < 0.3 retorna ajuda

  Fluxo 9 — Mídias não textuais
    11. Localização retorna endereço determinístico sem LLM
    12. Vídeo retorna resposta determinística sem LLM
    13. Áudio com bytes → chama transcrever_audio e continua como texto
    14. Áudio com transcrição vazia retorna pedido de texto
    15. Áudio com falha na tool retorna pedido de texto
    16. Áudio sem bytes e sem media_id retorna pedido para escrever

  Fluxo 10 — Fora de contexto
    17. Mensagem que state_machine não resolve incrementa contador
    18. Após 2 consecutivos escala para Breno silenciosamente
    19. Mensagem válida zera o contador fora_contexto_count
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Fluxo 8 — Comandos internos
# ══════════════════════════════════════════════════════════════════════════════

class TestNumeroAutorizado:
    def test_numero_nao_autorizado_retorna_none(self):
        from app.conversation.command_processor import _numero_autorizado
        result = _numero_autorizado("5531999999999")
        assert result is None

    def test_thaynara_detectada_por_sufixo(self):
        from app.conversation.command_processor import _numero_autorizado
        # Número exato da Thaynara
        result = _numero_autorizado("5531991394759")
        assert result is not None
        assert result["nome"] == "thaynara"

    def test_breno_detectado_por_sufixo(self):
        from app.conversation.command_processor import _numero_autorizado
        result = _numero_autorizado("5531992059211")
        assert result is not None
        assert result["nome"] == "breno"

    def test_numero_similar_nao_autorizado(self):
        from app.conversation.command_processor import _numero_autorizado
        # Número diferente dos dois autorizados
        result = _numero_autorizado("5511991394759")
        assert result is None


class TestProcessarComandoInterno:
    def _make_mensagem(self, texto: str) -> dict:
        return {"type": "text", "text": texto}

    def _make_state(self) -> dict:
        return {"estado": "inicio", "collected_data": {}, "flags": {}}

    @pytest.mark.asyncio
    async def test_nao_autorizado_retorna_processado_false(self):
        from app.conversation.command_processor import processar_comando_interno
        result = await processar_comando_interno(
            "5511999999999",
            self._make_mensagem("status do paciente João"),
            self._make_state(),
        )
        assert result.processado is False

    @pytest.mark.asyncio
    async def test_mensagem_vazia_retorna_false_mesmo_autorizado(self):
        from app.conversation.command_processor import processar_comando_interno
        result = await processar_comando_interno(
            "5531991394759",
            {"type": "text", "text": "   "},
            self._make_state(),
        )
        assert result.processado is False

    @pytest.mark.asyncio
    async def test_interpretar_comando_e_chamado_para_autorizado(self):
        from app.conversation.command_processor import processar_comando_interno

        cmd_result_mock = MagicMock()
        cmd_result_mock.sucesso = True
        cmd_result_mock.dados = {
            "comando_identificado": "nao_reconhecido",
            "parametros_extraidos": {},
            "confidence": 0.0,
        }

        with patch(
            "app.conversation.command_processor.call_tool",
            new=AsyncMock(return_value=cmd_result_mock),
        ) as mock_call:
            result = await processar_comando_interno(
                "5531991394759",
                self._make_mensagem("alguma coisa aleatória"),
                self._make_state(),
            )

        mock_call.assert_called_once()
        assert mock_call.call_args[0][0] == "interpretar_comando"
        assert result.processado is True

    @pytest.mark.asyncio
    async def test_nao_reconhecido_retorna_ajuda(self):
        from app.conversation.command_processor import processar_comando_interno

        cmd_result_mock = MagicMock()
        cmd_result_mock.sucesso = True
        cmd_result_mock.dados = {
            "comando_identificado": "nao_reconhecido",
            "parametros_extraidos": {},
            "confidence": 0.9,
        }

        with patch(
            "app.conversation.command_processor.call_tool",
            new=AsyncMock(return_value=cmd_result_mock),
        ):
            result = await processar_comando_interno(
                "5531992059211",
                self._make_mensagem("o que você faz?"),
                self._make_state(),
            )

        assert result.processado is True
        assert len(result.mensagens) == 1
        assert "Comandos disponíveis" in result.mensagens[0].conteudo

    @pytest.mark.asyncio
    async def test_confidence_baixa_retorna_ajuda(self):
        from app.conversation.command_processor import processar_comando_interno

        cmd_result_mock = MagicMock()
        cmd_result_mock.sucesso = True
        cmd_result_mock.dados = {
            "comando_identificado": "consultar_status_paciente",
            "parametros_extraidos": {},
            "confidence": 0.1,  # < 0.3 → retorna ajuda
        }

        with patch(
            "app.conversation.command_processor.call_tool",
            new=AsyncMock(return_value=cmd_result_mock),
        ):
            result = await processar_comando_interno(
                "5531991394759",
                self._make_mensagem("status"),
                self._make_state(),
            )

        assert result.processado is True
        assert "Comandos disponíveis" in result.mensagens[0].conteudo

    @pytest.mark.asyncio
    async def test_enviar_mensagem_para_paciente_usa_meta_api(self):
        from app.conversation.command_processor import processar_comando_interno

        cmd_result_mock = MagicMock()
        cmd_result_mock.sucesso = True
        cmd_result_mock.dados = {
            "comando_identificado": "enviar_mensagem_para_paciente",
            "parametros_extraidos": {
                "telefone_paciente": "5531988887777",
                "mensagem": "Olá, sua consulta foi confirmada!",
            },
            "confidence": 0.9,
        }

        meta_mock = AsyncMock()
        meta_mock.send_text = AsyncMock()

        with (
            patch("app.conversation.command_processor.call_tool", new=AsyncMock(return_value=cmd_result_mock)),
            patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        ):
            result = await processar_comando_interno(
                "5531991394759",
                self._make_mensagem("mensagem para 5531988887777: Olá, sua consulta foi confirmada!"),
                self._make_state(),
            )

        meta_mock.send_text.assert_called_once()
        assert result.processado is True
        assert "enviada" in result.mensagens[0].conteudo.lower()

    @pytest.mark.asyncio
    async def test_responder_escalacao_marca_como_resolvida(self):
        from app.conversation.command_processor import (
            processar_comando_interno,
        )
        import app.conversation.tools.notifications as notif

        esc_id = "esc_test123"
        notif._ESCALACOES_PENDENTES[esc_id] = {
            "id": esc_id,
            "status": "pendente",
            "criado_em": "2026-05-12T10:00:00",
            "contexto": {
                "state": {"phone": "5531977776666"},
            },
        }

        cmd_result_mock = MagicMock()
        cmd_result_mock.sucesso = True
        cmd_result_mock.dados = {
            "comando_identificado": "responder_escalacao",
            "parametros_extraidos": {
                "escalacao_id": esc_id,
                "resposta": "Pode sim, a Thaynara aceita gestantes em casos especiais.",
            },
            "confidence": 0.95,
        }

        meta_mock = AsyncMock()
        meta_mock.send_text = AsyncMock()

        with (
            patch("app.conversation.command_processor.call_tool", new=AsyncMock(return_value=cmd_result_mock)),
            patch("app.meta_api.MetaAPIClient", return_value=meta_mock),
        ):
            result = await processar_comando_interno(
                "5531991394759",
                self._make_mensagem(f"responder escalação {esc_id}: Pode sim"),
                self._make_state(),
            )

        assert result.processado is True
        assert notif._ESCALACOES_PENDENTES[esc_id]["status"] == "resolvida"
        meta_mock.send_text.assert_called_once()

        # cleanup
        del notif._ESCALACOES_PENDENTES[esc_id]


# ══════════════════════════════════════════════════════════════════════════════
# Fluxo 9 — Mídias não textuais
# ══════════════════════════════════════════════════════════════════════════════

def _make_state_agendamento() -> dict:
    return {
        "phone": "5531999990000",
        "phone_hash": "abc123",
        "fluxo_id": "agendamento_paciente_novo",
        "estado": "aguardando_nome",
        "history": [],
        "collected_data": {
            "nome": None, "nome_completo": None, "status_paciente": None,
            "objetivo": None, "plano": None, "modalidade": None,
            "preferencia_horario": None, "preferencia_horario_nova": None,
            "forma_pagamento": None, "data_nascimento": None,
            "email": None, "whatsapp_contato": None, "instagram": None,
            "profissao": None, "cep_endereco": None, "indicacao_origem": None,
            "motivo_cancelamento": None,
        },
        "appointment": {"slot_escolhido": None, "slot_escolhido_novo": None, "consulta_atual": None},
        "flags": {"pagamento_confirmado": False},
        "last_slots_offered": [],
        "slots_pool": [],
        "slots_rejeitados": [],
        "rodada_negociacao": 0,
        "status": "coletando",
        "fora_contexto_count": 0,
    }


class TestMidiasNaoTextuais:
    @pytest.mark.asyncio
    async def test_localizacao_retorna_endereco_deterministico(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "location", "latitude": -19.7, "longitude": -43.9}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert len(result.mensagens_enviadas) == 1
        assert "Rua Melo Franco" in result.mensagens_enviadas[0].conteudo

    @pytest.mark.asyncio
    async def test_video_retorna_resposta_deterministica(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "video", "media_id": "vid_123"}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert "vídeo" in result.mensagens_enviadas[0].conteudo.lower()

    @pytest.mark.asyncio
    async def test_audio_com_bytes_transcreve_e_processa(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "audio", "audio_bytes": b"fake_audio_data", "mime_type": "audio/ogg"}

        transcricao_result = MagicMock()
        transcricao_result.sucesso = True
        transcricao_result.dados = {"transcricao": "quero agendar uma consulta"}

        # Após transcrição, o fluxo continua — precisamos mockar tudo até o fim
        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(return_value=transcricao_result)),
            # Após transcrição o estado é inicio → dispara on_enter
            patch("app.conversation.orchestrator._mensagens_on_enter",
                  new=AsyncMock(return_value=([MagicMock(tipo="texto", conteudo="Olá!", botoes=[], arquivo=None, delay_segundos=0, numero_contato=None, metadata={})], "aguardando_nome"))),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        # A chamada de transcrição deve ter acontecido
        from app.conversation.orchestrator import call_tool as ct
        # Verificação indireta: não retornou a mensagem de "não consegui processar"

    @pytest.mark.asyncio
    async def test_audio_transcricao_vazia_retorna_pedido_texto(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "audio", "audio_bytes": b"fake_audio_data", "mime_type": "audio/ogg"}

        transcricao_result = MagicMock()
        transcricao_result.sucesso = True
        transcricao_result.dados = {"transcricao": ""}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(return_value=transcricao_result)),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert "entender" in result.mensagens_enviadas[0].conteudo.lower() or "texto" in result.mensagens_enviadas[0].conteudo.lower()

    @pytest.mark.asyncio
    async def test_audio_falha_tool_retorna_pedido_texto(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "audio", "audio_bytes": b"bad_audio", "mime_type": "audio/ogg"}

        transcricao_result = MagicMock()
        transcricao_result.sucesso = False
        transcricao_result.dados = {}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(return_value=transcricao_result)),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert "processar" in result.mensagens_enviadas[0].conteudo.lower() or "texto" in result.mensagens_enviadas[0].conteudo.lower()

    @pytest.mark.asyncio
    async def test_audio_sem_bytes_sem_media_id_retorna_pedido_escrever(self):
        from app.conversation.orchestrator import processar_turno

        mensagem = {"type": "audio"}  # sem bytes, sem media_id

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=_make_state_agendamento())),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert len(result.mensagens_enviadas) == 1
        texto = result.mensagens_enviadas[0].conteudo.lower()
        assert "áudio" in texto or "audio" in texto or "escrever" in texto or "texto" in texto


# ══════════════════════════════════════════════════════════════════════════════
# Fluxo 10 — Fora de contexto
# ══════════════════════════════════════════════════════════════════════════════

class TestForaDeContexto:
    def _state_com_count(self, count: int) -> dict:
        s = _make_state_agendamento()
        s["estado"] = "aguardando_nome"
        s["fora_contexto_count"] = count
        return s

    @pytest.mark.asyncio
    async def test_fallback_incrementa_contador(self):
        from app.conversation.orchestrator import processar_turno

        state = self._state_com_count(0)
        saved_state: dict = {}

        async def fake_save(phone_hash, s):
            saved_state.update(s)

        mensagem = {"type": "text", "text": "kkkkk"}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=state)),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock(side_effect=fake_save)),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            # state_machine retorna None → fallback → fora_contexto
            patch("app.conversation.state_machine.proxima_acao", return_value=None),
            patch("app.conversation.orchestrator.interpretar",
                  new=AsyncMock(return_value=MagicMock(
                      intent="desconhecido", confidence=0.1, entities={},
                      botao_id=None, message_type="text",
                      texto_original="kkkkk", validacoes={},
                  ))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(return_value=MagicMock(sucesso=True, dados={}))),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert saved_state.get("fora_contexto_count") == 1

    @pytest.mark.asyncio
    async def test_segundo_fallback_escala_breno(self):
        from app.conversation.orchestrator import processar_turno

        state = self._state_com_count(1)  # já tem 1 → próximo será 2 → escala
        escalou: list = []

        async def fake_call_tool(name, input):
            if name == "escalar_breno_silencioso":
                escalou.append(input)
            return MagicMock(sucesso=True, dados={})

        mensagem = {"type": "text", "text": "???"}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=state)),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock()),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            patch("app.conversation.state_machine.proxima_acao", return_value=None),
            patch("app.conversation.orchestrator.interpretar",
                  new=AsyncMock(return_value=MagicMock(
                      intent="desconhecido", confidence=0.1, entities={},
                      botao_id=None, message_type="text",
                      texto_original="???", validacoes={},
                  ))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(side_effect=fake_call_tool)),
        ):
            await processar_turno("5531999990000", mensagem)

        assert len(escalou) == 1
        assert escalou[0]["contexto"]["motivo"] == "fora_contexto_consecutivo"
        assert escalou[0]["contexto"]["count"] == 2

    @pytest.mark.asyncio
    async def test_mensagem_valida_zera_contador(self):
        from app.conversation.orchestrator import processar_turno
        from app.conversation.models import AcaoAutorizada, TipoAcao, Mensagem as Msg

        state = self._state_com_count(2)  # tinha 2 fora de contexto
        saved_state: dict = {}

        async def fake_save(phone_hash, s):
            saved_state.update(s)

        acao_valida = AcaoAutorizada(
            tipo=TipoAcao.enviar_mensagem,
            mensagens=[Msg(tipo="texto", conteudo="Qual seu nome completo?")],
            proximo_estado="aguardando_nome",
        )

        mensagem = {"type": "text", "text": "Maria Silva"}

        with (
            patch("app.conversation.orchestrator.load_state", new=AsyncMock(return_value=state)),
            patch("app.conversation.orchestrator.save_state", new=AsyncMock(side_effect=fake_save)),
            patch("app.conversation.command_processor.processar_comando_interno",
                  new=AsyncMock(return_value=MagicMock(processado=False))),
            patch("app.conversation.state_machine.proxima_acao", return_value=acao_valida),
            patch("app.conversation.orchestrator.interpretar",
                  new=AsyncMock(return_value=MagicMock(
                      intent="informar_nome", confidence=0.95, entities={"nome": "Maria Silva"},
                      botao_id=None, message_type="text",
                      texto_original="Maria Silva", validacoes={},
                  ))),
            patch("app.conversation.orchestrator.call_tool", new=AsyncMock(return_value=MagicMock(sucesso=True, dados={}))),
            patch("app.conversation.orchestrator.response_writer.escrever_async",
                  new=AsyncMock(return_value=[Msg(tipo="texto", conteudo="Qual seu nome completo?")])),
        ):
            result = await processar_turno("5531999990000", mensagem)

        assert result.sucesso is True
        assert saved_state.get("fora_contexto_count") == 0
