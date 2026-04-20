"""
Testes do Agente 3 — Dietbox Worker (todos com mock HTTP, sem chamada real).
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

BRT = timezone(timedelta(hours=-3))


# ── consultar_slots_disponiveis ───────────────────────────────────────────────

def test_slots_exclui_ocupados():
    """Slots que já constam na agenda não devem aparecer como disponíveis."""
    from app.agents.dietbox_worker import consultar_slots_disponiveis

    from datetime import date
    amanha = date.today() + timedelta(days=1)
    # Ocupa o primeiro horário do próximo dia útil
    dia_semana = amanha.weekday()
    from app.agents.dietbox_worker import HORARIOS_POR_DIA
    horarios = HORARIOS_POR_DIA.get(dia_semana, [])
    if not horarios:
        pytest.skip("Próximo dia é fim de semana")

    primeiro_horario = horarios[0]
    ocupado_dt = f"{amanha.isoformat()}T{primeiro_horario}"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Data": [{"inicio": f"{ocupado_dt}:00-03:00", "desmarcada": False}]
    }

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp), \
         patch("app.agents.dietbox_worker._carregar_locais"), \
         patch("app.agents.dietbox_worker._ID_LOCAL_PRESENCIAL", "LOCAL-001"):

        slots = consultar_slots_disponiveis(modalidade="presencial", dias_a_frente=3)

    # O slot ocupado não deve aparecer
    datetimes = [s["datetime"] for s in slots]
    # O horário ocupado (em BRT, que é UTC-3) não deve estar na lista
    assert not any(ocupado_dt in dt for dt in datetimes)


def test_slots_sem_sabado_domingo():
    """Sábado (5) e domingo (6) nunca devem ter slots."""
    from app.agents.dietbox_worker import HORARIOS_POR_DIA
    assert HORARIOS_POR_DIA[5] == []
    assert HORARIOS_POR_DIA[6] == []


def test_slots_sexta_sem_noite():
    """Sexta-feira não deve ter 18h e 19h."""
    from app.agents.dietbox_worker import HORARIOS_POR_DIA
    sexta = HORARIOS_POR_DIA[4]
    assert "18:00" not in sexta
    assert "19:00" not in sexta
    assert "08:00" in sexta


# ── buscar_paciente_por_telefone ──────────────────────────────────────────────

def test_busca_paciente_encontrado():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Data": [{"Id": 42, "Name": "Maria Silva", "Email": "maria@email.com",
                  "MobilePhone": "31999990000"}]
    }

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import buscar_paciente_por_telefone
        result = buscar_paciente_por_telefone("5531999990000")

    assert result is not None
    assert result["id"] == 42
    assert result["nome"] == "Maria Silva"


def test_busca_paciente_nao_encontrado():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": []}

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import buscar_paciente_por_telefone
        result = buscar_paciente_por_telefone("5531000000000")

    assert result is None


# ── cadastrar_paciente ────────────────────────────────────────────────────────

def test_cadastrar_paciente_retorna_id():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": {"Id": 99}}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("app.agents.dietbox_worker._carregar_locais"), \
         patch("app.agents.dietbox_worker._ID_LOCAL_PRESENCIAL", "LOCAL-001"), \
         patch("requests.post", return_value=mock_resp):
        from app.agents.dietbox_worker import cadastrar_paciente
        id_pac = cadastrar_paciente({
            "nome": "João Teste",
            "data_nascimento": "1990-05-15",
            "telefone": "5531988887777",
            "email": "joao@email.com",
        })

    assert id_pac == 99


def test_cadastrar_paciente_sem_id_levanta_erro():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": {}}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("app.agents.dietbox_worker._carregar_locais"), \
         patch("app.agents.dietbox_worker._ID_LOCAL_PRESENCIAL", "LOCAL-001"), \
         patch("requests.post", return_value=mock_resp):
        from app.agents.dietbox_worker import cadastrar_paciente
        with pytest.raises(ValueError):
            cadastrar_paciente({"nome": "Teste", "telefone": "5531900000000"})


# ── agendar_consulta ──────────────────────────────────────────────────────────

def test_agendar_consulta_retorna_id():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": {"id": "UUID-AGENDA-001"}}
    mock_resp.raise_for_status = MagicMock()

    dt = datetime(2026, 4, 10, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("app.agents.dietbox_worker.id_local_para_modalidade", return_value="LOCAL-001"), \
         patch("app.agents.dietbox_worker._buscar_id_servico", return_value="SVC-001"), \
         patch("requests.post", return_value=mock_resp):
        from app.agents.dietbox_worker import agendar_consulta
        id_agenda = agendar_consulta(
            id_paciente=42,
            dt_inicio=dt,
            modalidade="presencial",
            plano="ouro",
        )

    assert id_agenda == "UUID-AGENDA-001"


# ── lancar_financeiro ─────────────────────────────────────────────────────────

def test_lancar_financeiro_retorna_id():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": {"id": "TRANS-001"}}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.post", return_value=mock_resp):
        from app.agents.dietbox_worker import lancar_financeiro
        id_trans = lancar_financeiro(
            id_paciente=42,
            id_agenda="UUID-AGENDA-001",
            valor=345.0,
            forma_pagamento="pix",
        )

    assert id_trans == "TRANS-001"


# ── processar_agendamento (fluxo completo) ────────────────────────────────────

def test_processar_agendamento_paciente_novo():
    """Paciente não encontrado → cadastra → agenda → lança financeiro."""
    dt = datetime(2026, 4, 10, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker.buscar_paciente_por_telefone", return_value=None), \
         patch("app.agents.dietbox_worker.cadastrar_paciente", return_value=99), \
         patch("app.agents.dietbox_worker.agendar_consulta", return_value="AGENDA-001"), \
         patch("app.agents.dietbox_worker.lancar_financeiro", return_value="TRANS-001"):
        from app.agents.dietbox_worker import processar_agendamento
        result = processar_agendamento(
            dados_paciente={"nome": "Maria", "telefone": "5531999990000", "email": "m@m.com"},
            dt_consulta=dt,
            modalidade="presencial",
            plano="ouro",
            valor_sinal=345.0,
            forma_pagamento="pix",
        )

    assert result["sucesso"] is True
    assert result["id_paciente"] == 99
    assert result["id_agenda"] == "AGENDA-001"


def test_processar_agendamento_paciente_existente():
    """Paciente já existe → não cadastra, só agenda."""
    dt = datetime(2026, 4, 10, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker.buscar_paciente_por_telefone",
               return_value={"id": 42, "nome": "Maria", "email": "m@m.com", "telefone": "5531999990000"}), \
         patch("app.agents.dietbox_worker.cadastrar_paciente") as mock_cad, \
         patch("app.agents.dietbox_worker.agendar_consulta", return_value="AGENDA-002"), \
         patch("app.agents.dietbox_worker.lancar_financeiro", return_value="TRANS-002"):
        from app.agents.dietbox_worker import processar_agendamento
        result = processar_agendamento(
            dados_paciente={"nome": "Maria", "telefone": "5531999990000"},
            dt_consulta=dt,
            modalidade="online",
            plano="premium",
            valor_sinal=600.0,
            forma_pagamento="cartao",
        )

    mock_cad.assert_not_called()
    assert result["sucesso"] is True
    assert result["id_paciente"] == 42


def test_processar_agendamento_erro_retorna_falha():
    dt = datetime(2026, 4, 10, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker.buscar_paciente_por_telefone",
               side_effect=Exception("API indisponível")):
        from app.agents.dietbox_worker import processar_agendamento
        result = processar_agendamento(
            dados_paciente={"nome": "Teste", "telefone": "5531900000000"},
            dt_consulta=dt, modalidade="presencial", plano="ouro",
            valor_sinal=345.0, forma_pagamento="pix",
        )

    assert result["sucesso"] is False
    assert "erro" in result


# ── consultar_agendamento_ativo ───────────────────────────────────────────────

def test_consultar_agendamento_ativo_retorna_dict():
    """consultar_agendamento_ativo com 1 agenda futura válida retorna dict com chaves esperadas."""
    from datetime import date, timedelta
    amanha = date.today() + timedelta(days=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Data": [
            {
                "id": "AGENDA-ABC",
                "inicio": f"{amanha.isoformat()}T09:00:00",
                "fim": f"{amanha.isoformat()}T10:00:00",
                "idServico": "SVC-001",
                "desmarcada": False,
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import consultar_agendamento_ativo
        result = consultar_agendamento_ativo(id_paciente=123)

    assert result is not None
    assert result["id"] == "AGENDA-ABC"
    assert "inicio" in result
    assert "fim" in result


def test_consultar_agendamento_ativo_lista_vazia_retorna_none():
    """consultar_agendamento_ativo quando Dietbox retorna lista vazia → None."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import consultar_agendamento_ativo
        result = consultar_agendamento_ativo(id_paciente=123)

    assert result is None


def test_consultar_agendamento_ativo_todas_desmarcadas_retorna_none():
    """Quando todas as agendas têm desmarcada=True → retorna None."""
    from datetime import date, timedelta
    amanha = date.today() + timedelta(days=1)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Data": [
            {
                "id": "AGENDA-XYZ",
                "inicio": f"{amanha.isoformat()}T09:00:00",
                "fim": f"{amanha.isoformat()}T10:00:00",
                "desmarcada": True,
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import consultar_agendamento_ativo
        result = consultar_agendamento_ativo(id_paciente=123)

    assert result is None


# ── verificar_lancamento_financeiro ───────────────────────────────────────────

def test_verificar_lancamento_financeiro_com_lancamento_retorna_true():
    """Quando Dietbox retorna lançamento com pago=True → retorna True."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Data": [{"id": "TRANS-001", "pago": True, "valor": 345.0}]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import verificar_lancamento_financeiro
        result = verificar_lancamento_financeiro(id_agenda="AGENDA-ABC")

    assert result is True


def test_verificar_lancamento_financeiro_lista_vazia_retorna_false():
    """Quando Dietbox retorna lista vazia → retorna False."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", return_value=mock_resp):
        from app.agents.dietbox_worker import verificar_lancamento_financeiro
        result = verificar_lancamento_financeiro(id_agenda="AGENDA-ABC")

    assert result is False


def test_verificar_lancamento_financeiro_excecao_retorna_false():
    """Quando requests.get lança exceção HTTP → retorna False, nunca propaga."""
    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.get", side_effect=Exception("timeout")):
        from app.agents.dietbox_worker import verificar_lancamento_financeiro
        result = verificar_lancamento_financeiro(id_agenda="AGENDA-ABC")

    assert result is False


# ── alterar_agendamento ───────────────────────────────────────────────────────

def test_alterar_agendamento_sucesso_retorna_true():
    """alterar_agendamento com mock status 200 → retorna True."""
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"Data": {"id": "ID-123"}}
    mock_resp.raise_for_status = MagicMock()

    novo_dt = datetime(2026, 4, 14, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.put", return_value=mock_resp):
        from app.agents.dietbox_worker import alterar_agendamento
        result = alterar_agendamento("ID-123", novo_dt, "Remarcado do dia 10/04 para 14/04")

    assert result is True


def test_alterar_agendamento_http_error_retorna_false():
    """alterar_agendamento quando requests.patch levanta HTTPError → retorna False, não propaga."""
    import requests as _req
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))

    novo_dt = datetime(2026, 4, 14, 9, 0, tzinfo=BRT)

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = _req.HTTPError("400 Bad Request")

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.patch", return_value=mock_resp):
        from app.agents.dietbox_worker import alterar_agendamento
        result = alterar_agendamento("ID-123", novo_dt, "Remarcado")

    assert result is False


def test_alterar_agendamento_timeout_retorna_false():
    """alterar_agendamento quando requests.patch levanta Timeout → retorna False."""
    import requests as _req
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))

    novo_dt = datetime(2026, 4, 14, 9, 0, tzinfo=BRT)

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.patch", side_effect=_req.Timeout("timeout")):
        from app.agents.dietbox_worker import alterar_agendamento
        result = alterar_agendamento("ID-123", novo_dt, "Remarcado")

    assert result is False


def test_alterar_agendamento_payload_correto():
    """alterar_agendamento envia payload com Start, End e Observacao corretos via PUT."""
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))

    novo_dt = datetime(2026, 4, 14, 9, 0, tzinfo=BRT)
    observacao = "Remarcado do dia 10/04 para 14/04"

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.put", return_value=mock_resp) as mock_put:
        from app.agents.dietbox_worker import alterar_agendamento
        alterar_agendamento("ID-123", novo_dt, observacao)

    call_kwargs = mock_put.call_args
    payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert "Start" in payload
    assert "End" in payload
    assert "Observacao" in payload
    assert payload["Observacao"] == observacao


def test_alterar_agendamento_url_correta():
    """alterar_agendamento usa URL DIETBOX_API/agenda/{id_agenda} com PUT."""
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))

    novo_dt = datetime(2026, 4, 14, 9, 0, tzinfo=BRT)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.put", return_value=mock_resp) as mock_put:
        from app.agents.dietbox_worker import alterar_agendamento, DIETBOX_API
        alterar_agendamento("ID-123", novo_dt, "Remarcado")

    url_chamada = mock_put.call_args[0][0]
    assert url_chamada == f"{DIETBOX_API}/agenda/ID-123"


def test_cancelar_agendamento_sucesso_retorna_true():
    """cancelar_agendamento com mock status 200 → retorna True."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.delete", return_value=mock_resp):
        from app.agents.dietbox_worker import cancelar_agendamento
        result = cancelar_agendamento("ID-999", "Cancelado pela paciente")

    assert result is True


def test_cancelar_agendamento_url_correta():
    """cancelar_agendamento usa DELETE em DIETBOX_API/agenda/{id_agenda}."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("app.agents.dietbox_worker._headers", return_value={}), \
         patch("requests.delete", return_value=mock_resp) as mock_delete:
        from app.agents.dietbox_worker import cancelar_agendamento, DIETBOX_API
        cancelar_agendamento("ID-999", "Cancelado pela paciente")

    url_chamada = mock_delete.call_args[0][0]
    assert url_chamada == f"{DIETBOX_API}/agenda/ID-999"
