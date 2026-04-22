"""
Agente 3 — Worker Dietbox
Executa operações na API do Dietbox em background:
  - Consultar slots disponíveis
  - Buscar/cadastrar paciente
  - Agendar consulta
  - Lançar financeiro
"""

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

DIETBOX_API = "https://api.dietbox.me/v2"
BRT = timezone(timedelta(hours=-3))

# Horários válidos por dia da semana (0=seg..4=sex, 5=sab, 6=dom)
HORARIOS_POR_DIA = {
    0: ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],  # seg
    1: ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],  # ter
    2: ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],  # qua
    3: ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00", "18:00", "19:00"],  # qui
    4: ["08:00", "09:00", "10:00", "15:00", "16:00", "17:00"],                    # sex (sem noite)
    5: [],  # sab — não atende
    6: [],  # dom — não atende
}

# Cache em memória para IDs de locais online
_LOCAIS_ONLINE: set[str] | None = None
_ID_LOCAL_PRESENCIAL: str | None = None
_ID_LOCAL_ONLINE: str | None = None
_TODOS_IDS_LOCAIS: list[str] = []   # todos os locais conhecidos (para query extra)

TOKEN_CACHE_PATH = Path(__file__).parent.parent.parent / "dietbox_token_cache.json"


def _parse_agenda_datetime(value: str, timezone_name: str | None = None) -> datetime | None:
    """Normaliza datetimes da API para o fuso da agenda."""
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None

    tz = BRT
    if timezone_name:
        try:
            tz = ZoneInfo(timezone_name)
        except Exception:
            tz = BRT

    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


# ── Autenticação ──────────────────────────────────────────────────────────────

def _token_valido() -> dict | None:
    if not TOKEN_CACHE_PATH.exists():
        return None
    try:
        data = json.loads(TOKEN_CACHE_PATH.read_text())
        if time.time() < data.get("expires_at", 0) - 300:
            return data
    except Exception:
        pass
    return None


def _salvar_token(token: str, expires_in: int = 3600) -> None:
    data = {"access_token": token, "expires_at": time.time() + expires_in}
    TOKEN_CACHE_PATH.write_text(json.dumps(data))


def _login_playwright() -> str:
    """Faz login no Dietbox via Playwright (Azure AD B2C) e retorna access token.

    Playwright sync API não funciona dentro do asyncio loop do FastAPI.
    Delegamos para um thread separado com ThreadPoolExecutor.
    """
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_login_playwright_sync)
        return future.result(timeout=90)


def _login_playwright_sync() -> str:
    """Executa o login no Playwright em um thread sem asyncio loop."""
    from playwright.sync_api import sync_playwright

    email = os.environ["DIETBOX_EMAIL"]
    senha = os.environ["DIETBOX_SENHA"]
    token_capturado: dict[str, str | None] = {"value": None}

    logger.info("Fazendo login no Dietbox via Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        def _interceptar(request):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer ") and token_capturado["value"] is None:
                token_capturado["value"] = auth.replace("Bearer ", "")

        page = context.new_page()
        page.on("request", _interceptar)
        page.goto(
            "https://dietbox.me/pt-BR/Account/LoginB2C?role=nutritionist",
            wait_until="networkidle",
            timeout=30000,
        )
        page.fill('input[type="email"], input[name="signInName"], #signInName', email)
        try:
            page.click('button[id="continue"], button[type="submit"]', timeout=3000)
            page.wait_for_timeout(1000)
        except Exception:
            pass
        page.fill('input[type="password"], input[name="password"], #password', senha)
        page.click('button[type="submit"], #next, #signin', timeout=5000)
        page.wait_for_url("https://dietbox.me/**", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        # Fallback: verifica localStorage/sessionStorage
        if not token_capturado["value"]:
            for storage in ["localStorage", "sessionStorage"]:
                items = page.evaluate(f"""
                    () => {{
                        let r = {{}};
                        for (let i = 0; i < {storage}.length; i++) {{
                            let k = {storage}.key(i);
                            r[k] = {storage}.getItem(k);
                        }}
                        return r;
                    }}
                """)
                for value in items.values():
                    if value and len(value) > 100 and "." in value:
                        try:
                            parsed = json.loads(value)
                            t = parsed.get("access_token") or parsed.get("token")
                            if t:
                                token_capturado["value"] = t
                                break
                        except Exception:
                            token_capturado["value"] = value
                            break
                if token_capturado["value"]:
                    break

        browser.close()

    token = token_capturado["value"] or ""
    if token:
        _salvar_token(token)
        logger.info("Login Dietbox realizado com sucesso.")
    else:
        raise RuntimeError("Não foi possível capturar token do Dietbox.")
    return token


def obter_token() -> str:
    cached = _token_valido()
    if cached:
        return cached["access_token"]
    return _login_playwright()


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {obter_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://dietbox.me",
    }


# ── Locais de atendimento ─────────────────────────────────────────────────────

def _carregar_locais() -> None:
    global _LOCAIS_ONLINE, _ID_LOCAL_PRESENCIAL, _ID_LOCAL_ONLINE, _TODOS_IDS_LOCAIS
    if _LOCAIS_ONLINE is not None:
        return
    try:
        resp = requests.get(f"{DIETBOX_API}/local-atendimento", headers=_headers(), timeout=15)
        locais = resp.json().get("Data") or (resp.json() if resp.status_code == 200 else [])
        _LOCAIS_ONLINE = set()
        for loc in (locais if isinstance(locais, list) else []):
            lid = str(loc.get("id", "")).upper()
            if lid and lid not in _TODOS_IDS_LOCAIS:
                _TODOS_IDS_LOCAIS.append(lid)
            if loc.get("videoconferencia"):
                _LOCAIS_ONLINE.add(lid)
                if _ID_LOCAL_ONLINE is None:
                    _ID_LOCAL_ONLINE = lid
            else:
                if _ID_LOCAL_PRESENCIAL is None:
                    _ID_LOCAL_PRESENCIAL = lid
    except Exception as e:
        logger.error(f"Erro ao carregar locais de atendimento: {e}")
        _LOCAIS_ONLINE = set()


def id_local_para_modalidade(modalidade: str) -> str | None:
    """Retorna o idLocalAtendimento para 'presencial' ou 'online'."""
    _carregar_locais()
    if modalidade == "online":
        return _ID_LOCAL_ONLINE or os.environ.get("DIETBOX_ID_LOCAL_ONLINE")
    return _ID_LOCAL_PRESENCIAL or os.environ.get("DIETBOX_ID_LOCAL_PRESENCIAL")


# ── Slots disponíveis ─────────────────────────────────────────────────────────

def consultar_slots_disponiveis(
    modalidade: str = "presencial",
    dias_a_frente: int = 21,
    data_inicio: "date | None" = None,
) -> list[dict]:
    """
    Retorna lista de slots livres.
    data_inicio: data de início da busca (padrão: amanhã).
    Cada slot: {"datetime": "2026-04-10T09:00:00", "data_fmt": "sexta, 10/04", "hora": "9h"}
    """
    id_local = id_local_para_modalidade(modalidade)
    hoje = date.today()
    inicio = data_inicio if data_inicio else hoje + timedelta(days=1)
    fim = hoje + timedelta(days=dias_a_frente)

    # Busca TODA a agenda do período (consultas + bloqueios)
    start_str = f"{inicio.isoformat()}T00:00:00"
    end_str = f"{fim.isoformat()}T23:59:59"

    try:
        resp = requests.get(
            f"{DIETBOX_API}/agenda",
            headers=_headers(),
            params={"Start": start_str, "End": end_str},  # sem filtro de local: pega tudo
            timeout=20,
        )
        resp.raise_for_status()
        ocupados_raw = resp.json().get("Data", [])
    except Exception as e:
        logger.error(f"Erro ao buscar agenda: {e}")
        ocupados_raw = []

    # Query adicional por local: a API às vezes omite agendamentos de locais
    # secundários na query sem filtro. Fazemos uma query por cada local conhecido
    # e unimos os resultados para garantir que todos os slots ocupados sejam capturados.
    _carregar_locais()
    seen_ids: set = {item.get("id") or item.get("Id") for item in ocupados_raw if item.get("id") or item.get("Id")}
    for loc_id in _TODOS_IDS_LOCAIS:
        try:
            r2 = requests.get(
                f"{DIETBOX_API}/agenda",
                headers=_headers(),
                params={"Start": start_str, "End": end_str, "IdLocalAtendimento": loc_id},
                timeout=20,
            )
            r2.raise_for_status()
            for item in r2.json().get("Data", []):
                item_id = item.get("id") or item.get("Id")
                if item_id and item_id not in seen_ids:
                    ocupados_raw.append(item)
                    seen_ids.add(item_id)
        except Exception as e:
            logger.warning("Query agenda por local %s falhou: %s", loc_id, e)

    # Constrói set de datetimes ocupados
    # API retorna horários sem timezone (já em BRT) — nunca converter com astimezone
    ocupados: set[str] = set()
    for item in ocupados_raw:
        if item.get("desmarcada"):
            continue
        timezone_item = item.get("timezone")
        inicio_item = item.get("inicio", "") or item.get("Start", "") or item.get("start", "")
        fim_item = item.get("fim", "") or item.get("End", "") or item.get("end", "")
        dt_inicio = _parse_agenda_datetime(inicio_item, timezone_item)
        if dt_inicio is None:
            continue

        dt_fim = _parse_agenda_datetime(fim_item, timezone_item) or (dt_inicio + timedelta(hours=1))
        current = dt_inicio.replace(second=0, microsecond=0)
        limite = dt_fim.replace(second=0, microsecond=0)

        while current < limite:
            ocupados.add(current.strftime("%Y-%m-%dT%H:%M"))
            current += timedelta(hours=1)

    # Gera slots livres dentro do período
    DIAS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    slots: list[dict] = []
    current = inicio
    while current <= fim:
        dia_semana = current.weekday()
        horarios = HORARIOS_POR_DIA.get(dia_semana, [])
        for h in horarios:
            slot_key = f"{current.isoformat()}T{h}"
            if slot_key not in ocupados:
                hora_fmt = h[:2].lstrip("0") or "0"
                slots.append({
                    "datetime": f"{current.isoformat()}T{h}:00",
                    "data_fmt": f"{DIAS_PT[dia_semana]}, {current.strftime('%d/%m')}",
                    "hora": f"{hora_fmt}h",
                })
        current += timedelta(days=1)

    return slots


# ── Pacientes ─────────────────────────────────────────────────────────────────

def buscar_paciente_por_telefone(telefone: str) -> dict | None:
    """
    Busca paciente pelo número de telefone (formato E.164 ou DDD+número).
    Retorna dict com {id, nome, email, telefone} ou None.

    Estratégia dupla:
    1. Busca direta por nome/telefone nos pacientes (API do Dietbox não indexa phone)
    2. Fallback: percorre agenda (últimos 180 + próximos 180 dias) filtrando phonePatient
    """
    # Normaliza: remove não-dígitos, descarta prefixo 55 para comparação
    digitos = "".join(filter(str.isdigit, telefone))
    if digitos.startswith("55") and len(digitos) > 11:
        numero_busca = digitos[2:]
    else:
        numero_busca = digitos

    # ── Estratégia 1: busca direta nos pacientes ────────────────────────────
    try:
        resp = requests.get(
            f"{DIETBOX_API}/patients",
            headers=_headers(),
            params={"Search": numero_busca, "Take": 10},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("Data") or data.get("data") or []
            if isinstance(items, dict):
                items = items.get("Items") or items.get("items") or []
            for p in items:
                for campo in ("MobilePhone", "mobilePhone", "Phone", "phone"):
                    tel = "".join(filter(str.isdigit, str(p.get(campo, "") or "")))
                    if numero_busca in tel or tel.endswith(numero_busca[-8:]):
                        return {
                            "id": p.get("Id") or p.get("id"),
                            "nome": p.get("Name") or p.get("name") or p.get("nome"),
                            "email": p.get("Email") or p.get("email") or "",
                            "telefone": telefone,
                        }
    except Exception as e:
        logger.warning("Busca direta de paciente falhou: %s", e)

    # ── Estratégia 2: busca via campo phonePatient na agenda ────────────────
    try:
        hoje = date.today()
        start = (hoje - timedelta(days=180)).isoformat()
        end = (hoje + timedelta(days=180)).isoformat()
        resp = requests.get(
            f"{DIETBOX_API}/agenda",
            headers=_headers(),
            params={"start": start, "end": end, "per_page": 5000},
            timeout=30,
        )
        resp.raise_for_status()
        items = resp.json().get("Data") or []
        for a in items:
            phone_ag = "".join(filter(str.isdigit, str(a.get("phonePatient") or "")))
            if not phone_ag:
                continue
            if numero_busca in phone_ag or phone_ag.endswith(numero_busca[-8:]):
                patient = a.get("patient") or {}
                pid = patient.get("id")
                pname = patient.get("name") or a.get("namePatient") or ""
                if pid and int(pid) > 0:
                    return {
                        "id": pid,
                        "nome": pname,
                        "email": a.get("emailPatient") or "",
                        "telefone": telefone,
                    }
    except Exception as e:
        logger.error("Busca por agenda falhou ao localizar paciente: %s", e)

    return None


def cadastrar_paciente(dados: dict) -> int:
    """
    Cadastra novo paciente no Dietbox.
    dados: {nome, data_nascimento (YYYY-MM-DD), telefone, email,
            instagram?, profissao?, cep?, sexo? ('M'|'F')}
    Retorna id_paciente (int).
    """
    _carregar_locais()
    id_local = _ID_LOCAL_PRESENCIAL or os.environ.get("DIETBOX_ID_LOCAL_PRESENCIAL", "")

    # Formata telefone em E.164 (+5531...)
    digitos = "".join(filter(str.isdigit, dados.get("telefone", "")))
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    telefone = "+" + digitos

    # Birthdate é obrigatório no Dietbox; usa placeholder se não informado
    birthdate = dados.get("data_nascimento") or "1990-01-01T00:00:00"

    payload = {
        "Name": dados["nome"],
        "Birthdate": birthdate,
        "MobilePhone": telefone,
        "Email": dados.get("email") or None,
        "IsMale": dados.get("sexo", "F").upper() == "M",
        "Occupation": dados.get("profissao") or None,
        "ZipCode": dados.get("cep") or None,
        "Observation": dados.get("instagram") or None,
        "IsActive": True,
        "ServiceLocationId": id_local,
    }
    # Remove campos None e strings vazias
    payload = {k: v for k, v in payload.items() if v is not None}

    resp = requests.post(
        f"{DIETBOX_API}/patients",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    id_paciente = (
        data.get("Data", {}).get("Id")
        or data.get("data", {}).get("id")
        or data.get("Id")
        or data.get("id")
    )
    if not id_paciente:
        raise ValueError(f"Cadastro do paciente não retornou ID: {data}")
    logger.info(f"Paciente cadastrado: {dados['nome']} (id={id_paciente})")
    return int(id_paciente)


def buscar_dados_paciente(id_paciente: int) -> dict:
    """Retorna dados completos do paciente pelo ID."""
    resp = requests.get(
        f"{DIETBOX_API}/patients/{id_paciente}",
        headers=_headers(),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("Data") or data.get("data") or data


# ── Agendamento ───────────────────────────────────────────────────────────────

def _buscar_id_servico(modalidade: str, plano: str) -> str | None:
    """
    Retorna o idServico do Dietbox correspondente ao plano e modalidade.
    Mapeia por título parcial (case-insensitive).
    """
    id_local = id_local_para_modalidade(modalidade)
    if not id_local:
        return None

    try:
        resp = requests.get(
            f"{DIETBOX_API}/local-atendimento/{id_local}/servicos",
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        servicos = resp.json().get("Data", [])
    except Exception as e:
        logger.error(f"Erro ao buscar serviços Dietbox: {e}")
        return None

    # Mapeamento plano → palavras-chave no título do serviço
    PALAVRAS = {
        "premium": ["premium"],
        "ouro": ["ouro", "gold"],
        "com_retorno": ["retorno"],
        "unica": ["única", "unica", "avulsa"],
        "formulario": ["formulário", "formulario"],
    }
    chaves = PALAVRAS.get(plano.lower().replace(" ", "_"), [plano.lower()])

    for svc in servicos:
        titulo = (svc.get("titulo") or "").lower()
        if any(c in titulo for c in chaves):
            return str(svc.get("id", "")).upper()

    # Fallback: retorna o primeiro serviço disponível
    if servicos:
        logger.warning(f"Serviço não encontrado para plano='{plano}', usando primeiro disponível.")
        return str(servicos[0].get("id", "")).upper()
    return None


def agendar_consulta(
    id_paciente: int,
    dt_inicio: datetime,
    modalidade: str,
    plano: str,
    duracao_minutos: int = 60,
) -> str:
    """
    Agenda uma consulta no Dietbox.
    Retorna o id_agenda (str UUID).
    """
    id_local = id_local_para_modalidade(modalidade)
    id_servico = _buscar_id_servico(modalidade, plano)

    # Converte para UTC se necessário
    if dt_inicio.tzinfo is None:
        dt_inicio = dt_inicio.replace(tzinfo=BRT)
    dt_fim = dt_inicio + timedelta(minutes=duracao_minutos)

    # Estrutura correta: {Agenda: {CreateAppointmentDTO}, Lancamento: null}
    agenda_dto: dict = {
        "Type": 1,  # 1=Consulta (ETipoAgenda enum)
        "Start": dt_inicio.isoformat(),
        "End": dt_fim.isoformat(),
        "Timezone": "America/Sao_Paulo",
        "IdPaciente": id_paciente,
        "IdLocalAtendimento": id_local,
        "IdServico": id_servico,
        "IsOnline": modalidade == "online",
        "IsVideoConference": modalidade == "online",
        "Alert": True,
        "Confirmed": False,
        "AllDay": False,
    }
    agenda_dto = {k: v for k, v in agenda_dto.items() if v is not None}

    payload = {"Agenda": agenda_dto, "Lancamento": None}

    resp = requests.post(
        f"{DIETBOX_API}/agenda",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    id_agenda = (
        data.get("Data", {}).get("id")
        or data.get("Data", {}).get("Id")
        or data.get("id")
        or data.get("Id")
    )
    if not id_agenda:
        raise ValueError(f"Agendamento não retornou ID: {data}")
    logger.info(f"Consulta agendada: paciente={id_paciente}, horario={dt_inicio}, id={id_agenda}")
    return str(id_agenda)


# ── Alterar agendamento ───────────────────────────────────────────────────────

def alterar_agendamento(
    id_agenda: str,
    novo_dt_inicio: datetime,
    observacao: str,
    duracao_minutos: int = 60,
) -> bool:
    """
    Altera a data/hora de um agendamento existente no Dietbox (per D-22).
    Adiciona observacao ao campo Observacao do agendamento (per D-23).
    Retorna True se bem-sucedido, False em qualquer falha (nunca propaga exceção).
    """
    if novo_dt_inicio.tzinfo is None:
        novo_dt_inicio = novo_dt_inicio.replace(tzinfo=BRT)
    novo_dt_fim = novo_dt_inicio + timedelta(minutes=duracao_minutos)

    # Fetch current appointment to preserve required scalar fields
    try:
        get_resp = requests.get(
            f"{DIETBOX_API}/agenda/{id_agenda}", headers=_headers(), timeout=15
        )
        get_resp.raise_for_status()
        current = get_resp.json().get("Data") or get_resp.json()
    except Exception as e:
        logger.error("Falha ao buscar agendamento antes de alterar %s: %s", id_agenda, e)
        return False  # Não prosseguir sem dados atuais

    def _get(*keys):
        for k in keys:
            v = current.get(k)
            if v is not None:
                return v
        return None

    # Payload mínimo — apenas campos escalares necessários.
    # Não espalhar current inteiro para evitar objetos aninhados (servico, paciente,
    # localAtendimento, etc.) que o Dietbox rejeita com 500.
    payload = {
        "inicio": novo_dt_inicio.isoformat(),
        "fim": novo_dt_fim.isoformat(),
        "timezone": _get("timezone", "Timezone") or "America/Sao_Paulo",
        "idPaciente": _get("idPaciente", "IdPaciente"),
        "idLocalAtendimento": _get("idLocalAtendimento", "IdLocalAtendimento"),
        "idServico": _get("idServico", "IdServico"),
        "tipo": _get("tipo", "Type") or 1,
        "isOnline": _get("isOnline", "IsOnline") or False,
        "isVideoConference": _get("isVideoConference", "IsVideoConference") or False,
        "alert": True,
        "allDay": False,
        "descricao": observacao or _get("descricao", "Descricao") or "",
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        resp = requests.put(
            f"{DIETBOX_API}/agenda/{id_agenda}",
            headers=_headers(),
            json=payload,
            timeout=20,
        )
        if not resp.ok:
            logger.error(
                "Falha PUT agendamento %s: status=%s body=%s",
                id_agenda, resp.status_code, resp.text[:500],
            )
            return False
        logger.info(
            "Agendamento alterado: id=%s, novo_inicio=%s",
            id_agenda,
            novo_dt_inicio.isoformat(),
        )
        return True
    except Exception as e:
        logger.error("Falha ao alterar agendamento %s: %s", id_agenda, e)
        return False


def cancelar_agendamento(
    id_agenda: str,
    observacao: str = "Cancelado pelo Agente Ana",
) -> bool:
    """
    Cancela um agendamento existente no Dietbox.

    Retorna True se bem-sucedido, False em qualquer falha.
    """
    try:
        resp = requests.delete(
            f"{DIETBOX_API}/agenda/{id_agenda}",
            headers=_headers(),
            timeout=20,
        )
        resp.raise_for_status()
        logger.info("Agendamento cancelado: id=%s", id_agenda)
        return True
    except Exception as e:
        logger.error("Falha ao cancelar agendamento %s: %s", id_agenda, e)
        return False


# ── Financeiro ────────────────────────────────────────────────────────────────

def lancar_financeiro(
    id_paciente: int,
    id_agenda: str,
    valor: float,
    forma_pagamento: str = "pix",
    pago: bool = False,
) -> str:
    """
    Lança a transação financeira no Dietbox.
    forma_pagamento: 'pix' | 'cartao'
    Retorna o id da transação.
    """
    descricao = f"Pagamento via {'PIX' if forma_pagamento == 'pix' else 'Cartão'} — Agente Ana"

    payload = {
        "data": datetime.now(BRT).isoformat(),
        "descricao": descricao,
        "observacao": "Gerado automaticamente pelo Agente Ana (WhatsApp)",
        "idPatient": id_paciente,
        "idAgenda": id_agenda,
        "tipo": 1,  # 1=Entrada (ETipoLancamento)
        "pago": pago,
        "valor": valor,
        "idCategoria": "89867901-A5B8-4B61-89DA-5A24BAE39952",  # Consultas
        "idConta": "71D0DE53-96C5-4AFA-A144-98039B264031",  # Conta padrão
    }

    resp = requests.post(
        f"{DIETBOX_API}/finance/transactions",
        headers=_headers(),
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    id_transacao = (
        data.get("Data", {}).get("id")
        or data.get("Data", {}).get("Id")
        or data.get("id")
        or ""
    )
    logger.info(f"Financeiro lançado: paciente={id_paciente}, valor={valor}, pago={pago}")
    return str(id_transacao)


# ── Função principal do agente ────────────────────────────────────────────────

def processar_agendamento(
    dados_paciente: dict,
    dt_consulta: datetime,
    modalidade: str,
    plano: str,
    valor_sinal: float,
    forma_pagamento: str,
) -> dict:
    """
    Fluxo completo: cadastra (se novo), agenda e lança financeiro.
    Retorna {id_paciente, id_agenda, id_transacao, sucesso, erro?}
    """
    try:
        # 1. Busca ou cadastra paciente
        existente = buscar_paciente_por_telefone(dados_paciente["telefone"])
        if existente:
            id_paciente = int(existente["id"])
            logger.info(f"Paciente já existente: {existente['nome']} (id={id_paciente})")
        else:
            id_paciente = cadastrar_paciente(dados_paciente)

        # 2. Agenda consulta
        id_agenda = agendar_consulta(
            id_paciente=id_paciente,
            dt_inicio=dt_consulta,
            modalidade=modalidade,
            plano=plano,
        )

        # 3. Lança financeiro
        id_transacao = lancar_financeiro(
            id_paciente=id_paciente,
            id_agenda=id_agenda,
            valor=valor_sinal,
            forma_pagamento=forma_pagamento,
            pago=False,  # aguardando comprovante
        )

        return {
            "sucesso": True,
            "id_paciente": id_paciente,
            "id_agenda": id_agenda,
            "id_transacao": id_transacao,
        }

    except Exception as e:
        logger.error(f"Erro no processamento do agendamento: {e}")
        return {"sucesso": False, "erro": str(e)}


# ── Consulta de agendamento ativo e financeiro ────────────────────────────────

def consultar_agendamento_ativo(id_paciente: int) -> dict | None:
    """
    Busca o próximo agendamento ativo (não desmarcado) do paciente no Dietbox.

    Retorna dict com {id, inicio, fim, id_servico} ou None se não encontrado.
    Nunca propaga exceção para o chamador.
    """
    hoje = date.today()
    fim = hoje + timedelta(days=180)
    start_str = f"{hoje.isoformat()}T00:00:00"
    end_str = f"{fim.isoformat()}T23:59:59"
    try:
        resp = requests.get(
            f"{DIETBOX_API}/agenda",
            headers=_headers(),
            params={
                "IdPaciente": id_paciente,
                "Start": start_str,
                "End": end_str,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("Data") or []
        agora_str = datetime.now().isoformat()
        ativos = [
            i for i in items
            if not i.get("desmarcada") and i.get("inicio", "") >= agora_str[:16]
        ]
        if not ativos:
            return None
        ativos.sort(key=lambda i: i.get("inicio", ""))
        primeiro = ativos[0]
        return {
            "id": str(primeiro.get("id") or primeiro.get("Id") or ""),
            "inicio": str(primeiro.get("inicio", "")),
            "fim": str(primeiro.get("fim", "")),
            "id_servico": str(primeiro.get("idServico") or primeiro.get("id_servico") or "") or None,
        }
    except Exception as e:
        logger.error("Erro ao consultar agendamento ativo (paciente=%s): %s", id_paciente, e)
        return None


def verificar_lancamento_financeiro(id_agenda: str) -> bool:
    """
    Verifica se existe lançamento financeiro para a agenda informada.

    Retorna True se houver qualquer lançamento, False se vazio ou em caso de erro.
    Nunca propaga exceção para o chamador.
    """
    try:
        resp = requests.get(
            f"{DIETBOX_API}/finance/transactions",
            headers=_headers(),
            params={"IdAgenda": id_agenda},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("Data") or data.get("data") or []
        return len(items) > 0
    except Exception as e:
        logger.error("Erro ao verificar lançamento financeiro (agenda=%s): %s", id_agenda, e)
        return False


def confirmar_pagamento(id_transacao: str) -> bool:
    """Marca uma transação como paga no Dietbox."""
    try:
        resp = requests.patch(
            f"{DIETBOX_API}/finance/transactions/{id_transacao}",
            headers=_headers(),
            json={"pago": True},
            timeout=15,
        )
        return resp.status_code in (200, 204)
    except Exception as e:
        logger.error(f"Erro ao confirmar pagamento: {e}")
        return False
