"""
Testes para constantes de mensagens de remarketing (D-02, D-03, D-04)
e logica de envio _enviar_remarketing (D-05, D-06).
"""
from __future__ import annotations

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Task 1: Constantes MSG_FOLLOWUP_* e TEMPLATE_NAMES ───────────────────────

class TestMsgFollowupConstantes:
    """Verifica que os textos aprovados (D-02, D-03, D-04) estao presentes e corretos."""

    def test_msg_followup_24h_contem_eiii_e_acentos(self):
        from app.remarketing import MSG_FOLLOWUP_24H
        # D-02: verificar palavras-chave e caracteres acentuados obrigatorios
        assert "Eiii!" in MSG_FOLLOWUP_24H
        assert "aí" in MSG_FOLLOWUP_24H
        assert "dúvida" in MSG_FOLLOWUP_24H
        assert "à vontade" in MSG_FOLLOWUP_24H
        assert "tô" in MSG_FOLLOWUP_24H
        assert "é só" in MSG_FOLLOWUP_24H

    def test_msg_followup_7d_contem_passando_e_acentos(self):
        from app.remarketing import MSG_FOLLOWUP_7D
        # D-03: verificar palavras-chave e caracteres acentuados obrigatorios
        assert "Passando pra saber" in MSG_FOLLOWUP_7D
        assert "você" in MSG_FOLLOWUP_7D
        assert "Às vezes" in MSG_FOLLOWUP_7D
        assert "relação" in MSG_FOLLOWUP_7D

    def test_msg_followup_30d_contem_ultima_passagem(self):
        from app.remarketing import MSG_FOLLOWUP_30D
        # D-04: verificar palavras-chave e caracteres acentuados obrigatorios
        assert "última passagem por aqui" in MSG_FOLLOWUP_30D
        assert "você" in MSG_FOLLOWUP_30D
        assert "adiar" in MSG_FOLLOWUP_30D

    def test_template_names_mapeamento_correto(self):
        from app.remarketing import TEMPLATE_NAMES
        # D-07: nomes dos templates
        assert TEMPLATE_NAMES[1] == "ana_followup_24h"
        assert TEMPLATE_NAMES[2] == "ana_followup_7d"
        assert TEMPLATE_NAMES[3] == "ana_followup_30d"

    def test_msg_followup_nao_contem_numero_interno(self):
        from app.remarketing import MSG_FOLLOWUP_24H, MSG_FOLLOWUP_7D, MSG_FOLLOWUP_30D
        # Numero 31 99205-9211 NUNCA exposto ao paciente (CLAUDE.md)
        numero = "99205"
        assert numero not in MSG_FOLLOWUP_24H
        assert numero not in MSG_FOLLOWUP_7D
        assert numero not in MSG_FOLLOWUP_30D

    def test_msg_por_posicao_mapeamento(self):
        from app.remarketing import _MSG_POR_POSICAO, MSG_FOLLOWUP_24H, MSG_FOLLOWUP_7D, MSG_FOLLOWUP_30D
        assert _MSG_POR_POSICAO[1] is MSG_FOLLOWUP_24H
        assert _MSG_POR_POSICAO[2] is MSG_FOLLOWUP_7D
        assert _MSG_POR_POSICAO[3] is MSG_FOLLOWUP_30D


# ── Task 2: _enviar_remarketing logica send_text / send_template ──────────────

def _make_entry(position: int) -> MagicMock:
    """Cria um mock de RemarketingQueue com sequence_position definido."""
    entry = MagicMock()
    entry.sequence_position = position
    entry.template_name = {1: "ana_followup_24h", 2: "ana_followup_7d", 3: "ana_followup_30d"}[position]
    return entry


class TestEnviarRemarketingPosition1:
    """Testes para position=1 (24h) — usa send_text."""

    @pytest.mark.asyncio
    async def test_position1_chama_send_text_com_texto_correto(self):
        from app.remarketing import _enviar_remarketing, MSG_FOLLOWUP_24H
        meta = MagicMock()
        meta.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.123"}]})
        entry = _make_entry(1)

        result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is True
        meta.send_text.assert_called_once_with(to="+5531999990000", text=MSG_FOLLOWUP_24H)
        meta.send_template.assert_not_called()

    @pytest.mark.asyncio
    async def test_position1_erro_131026_retorna_false_sem_crash(self):
        from app.remarketing import _enviar_remarketing
        meta = MagicMock()
        meta.send_text = AsyncMock(side_effect=Exception("131026 window closed re-engage"))
        meta.send_template = AsyncMock()
        entry = _make_entry(1)

        result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is False
        # send_template nao deve ser chamado como fallback
        meta.send_template.assert_not_called()

    @pytest.mark.asyncio
    async def test_position1_outro_erro_retorna_false(self):
        from app.remarketing import _enviar_remarketing
        meta = MagicMock()
        meta.send_text = AsyncMock(side_effect=Exception("Connection timeout"))
        meta.send_template = AsyncMock()
        entry = _make_entry(1)

        result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is False


class TestEnviarRemarketingPosition2E3:
    """Testes para positions 2 e 3 (7d e 30d) — usa send_template."""

    @pytest.mark.asyncio
    async def test_position2_com_templates_aprovados_chama_send_template(self):
        from app.remarketing import _enviar_remarketing
        meta = MagicMock()
        meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.456"}]})
        meta.send_text = AsyncMock()
        entry = _make_entry(2)

        with patch.dict(os.environ, {"REMARKETING_TEMPLATES_APPROVED": "true"}):
            # Recarregar o flag TEMPLATES_APPROVED via patch direto no modulo
            with patch("app.remarketing.TEMPLATES_APPROVED", True):
                result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is True
        meta.send_template.assert_called_once_with(to="+5531999990000", template_name="ana_followup_7d")
        meta.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_position2_sem_templates_aprovados_retorna_false(self):
        from app.remarketing import _enviar_remarketing
        meta = MagicMock()
        meta.send_template = AsyncMock()
        meta.send_text = AsyncMock()
        entry = _make_entry(2)

        with patch("app.remarketing.TEMPLATES_APPROVED", False):
            result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is False
        meta.send_template.assert_not_called()
        meta.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_position3_com_templates_aprovados_chama_send_template(self):
        from app.remarketing import _enviar_remarketing
        meta = MagicMock()
        meta.send_template = AsyncMock(return_value={"messages": [{"id": "wamid.789"}]})
        meta.send_text = AsyncMock()
        entry = _make_entry(3)

        with patch("app.remarketing.TEMPLATES_APPROVED", True):
            result = await _enviar_remarketing(meta, "+5531999990000", entry)

        assert result is True
        meta.send_template.assert_called_once_with(to="+5531999990000", template_name="ana_followup_30d")
        meta.send_text.assert_not_called()


class TestDispatchFromDbUsaEnviarRemarketingEStatus:
    """Verifica que _dispatch_from_db usa _enviar_remarketing e atualiza status."""

    def _make_contact(self, phone: str = "+5531999990000", stage: str = "lead") -> MagicMock:
        contact = MagicMock()
        contact.phone_e164 = phone
        contact.phone_hash = "hash_test_1234"
        contact.stage = stage
        contact.remarketing_count = 0
        return contact

    def _make_db(self, contact, entry) -> MagicMock:
        db = MagicMock()
        db.get = MagicMock(return_value=contact)
        db.commit = MagicMock()
        return db

    def _make_redis(self, has_active: bool = False) -> MagicMock:
        redis = MagicMock()
        redis.incr = AsyncMock(return_value=1)
        redis.expire = AsyncMock()
        redis.exists = AsyncMock(return_value=1 if has_active else 0)
        return redis

    @pytest.mark.asyncio
    async def test_dispatch_entry_sucesso_marca_sent(self):
        from app.remarketing import _dispatch_from_db
        entry = _make_entry(1)
        entry.contact_id = "contact-uuid-1"
        entry.counts_toward_limit = True
        entry.status = "pending"
        entry.sent_at = None

        contact = self._make_contact()
        db = self._make_db(contact, entry)
        redis = self._make_redis()

        meta = MagicMock()
        meta.send_text = AsyncMock(return_value={"messages": [{"id": "wamid.ok"}]})
        meta.send_template = AsyncMock()

        with patch("app.remarketing.TEMPLATES_APPROVED", False):
            with patch("app.remarketing._enviar_remarketing", new_callable=AsyncMock, return_value=True) as mock_enviar:
                await _dispatch_from_db([entry], db, redis, meta)
                mock_enviar.assert_called_once()

        assert entry.status == "sent"
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_dispatch_entry_position1_falha_marca_failed(self):
        from app.remarketing import _dispatch_from_db
        entry = _make_entry(1)
        entry.contact_id = "contact-uuid-2"
        entry.counts_toward_limit = True
        entry.status = "pending"
        entry.sent_at = None

        contact = self._make_contact()
        db = self._make_db(contact, entry)
        redis = self._make_redis()

        meta = MagicMock()

        with patch("app.remarketing._enviar_remarketing", new_callable=AsyncMock, return_value=False):
            await _dispatch_from_db([entry], db, redis, meta)

        # position 1 com falha -> status failed
        assert entry.status == "failed"

    @pytest.mark.asyncio
    async def test_dispatch_entry_position2_sem_template_mantem_pending(self):
        from app.remarketing import _dispatch_from_db
        entry = _make_entry(2)
        entry.contact_id = "contact-uuid-3"
        entry.counts_toward_limit = True
        entry.status = "pending"
        entry.sent_at = None

        contact = self._make_contact()
        db = self._make_db(contact, entry)
        redis = self._make_redis()

        meta = MagicMock()

        with patch("app.remarketing.TEMPLATES_APPROVED", False):
            with patch("app.remarketing._enviar_remarketing", new_callable=AsyncMock, return_value=False):
                await _dispatch_from_db([entry], db, redis, meta)

        # position 2 sem template aprovado -> permanece pending (nao muda status)
        assert entry.status == "pending"


class TestTemplatesApprovedFlag:
    """Verifica que TEMPLATES_APPROVED e False por padrao."""

    def test_templates_approved_false_por_padrao(self):
        # Garante que sem a env var, o flag e False
        with patch.dict(os.environ, {}, clear=False):
            # Remover a env var se existir para simular ambiente limpo
            env_backup = os.environ.pop("REMARKETING_TEMPLATES_APPROVED", None)
            try:
                import importlib
                import app.remarketing as rmkt_mod
                importlib.reload(rmkt_mod)
                assert rmkt_mod.TEMPLATES_APPROVED is False
            finally:
                if env_backup is not None:
                    os.environ["REMARKETING_TEMPLATES_APPROVED"] = env_backup
                # Recarregar para restaurar estado original
                import importlib
                import app.remarketing as rmkt_mod
                importlib.reload(rmkt_mod)
