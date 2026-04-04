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

TOKEN_CACHE_PATH = Path(__file__).parent.parent.parent / "dietbox_token_cache.json"


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
    """Faz login no Dietbox via Playwright (Azure AD B2C) e retorna access token."""
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
    global _LOCAIS_ONLINE, _ID_LOCAL_PRESENCIAL, _ID_LOCAL_ONLINE
    if _LOCAIS_ONLINE is not None:
        return
    try:
        resp = requests.get(f"{DIETBOX_API}/local-atendimento", headers=_headers(), timeout=15)
        locais = resp.json().get("Data") or (resp.json() if resp.status_code == 200 else [])
        _LOCAIS_ONLINE = set()
        for loc in (locais if isinstance(locais, list) else []):
            lid = str(loc.get("id", "")).upper()
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
    dias_a_frente: int = 14,
) -> list[dict]:
    """
    Retorna lista de slots livres nos próximos dias_a_frente dias.
    Cada slot: {"datetime": "2026-04-10T09:00:00", "data_fmt": "sexta, 10/04", "hora": "09h"}
    """
    id_local = id_local_para_modalidade(modalidade)
    hoje = date.today()
    amanha = hoje + timedelta(days=1)  # mínimo 1 dia útil de antecedência
    fim = hoje + timedelta(days=dias_a_frente)

    # Busca agenda ocupada no período
    start_str = f"{amanha.isoformat()}T00:00:00"
    end_str = f"{fim.isoformat()}T23:59:59"

    try:
        resp = requests.get(
            f"{DIETBOX_API}/agenda",
            headers=_headers(),
            params={"Start": start_str, "End": end_str, "IdLocalAtendimento": id_local},
            timeout=20,
        )
        resp.raise_for_status()
        ocupados_raw = resp.json().get("Data", [])
    except Exception as e:
        logger.error(f"Erro ao buscar agenda: {e}")
        ocupados_raw = []

    # Constrói set de datetimes ocupados
    ocupados: set[str] = set()
    for item in ocupados_raw:
        if item.get("desmarcada"):
            continue
        inicio = item.get("inicio", "")
        if inicio:
            try:
                dt = datetime.fromisoformat(inicio).astimezone(BRT)
                ocupados.add(dt.strftime("%Y-%m-%dT%H:%M"))
            except Exception:
                pass

    # Gera slots livres
    DIAS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    slots: list[dict] = []
    current = amanha
    while current <= fim and len(slots) < 9:  # máx 9 opções
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
    """
    # Normaliza: remove não-dígitos, garante prefixo 55
    digitos = "".join(filter(str.isdigit, telefone))
    if digitos.startswith("55") and len(digitos) > 11:
        numero_busca = digitos[2:]  # remove prefixo 55 para busca
    else:
        numero_busca = digitos

    try:
        resp = requests.get(
            f"{DIETBOX_API}/patients",
            headers=_headers(),
            params={"Search": numero_busca, "Take": 5},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("Data") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("Items") or items.get("items") or []

        for p in items:
            # Verifica se o telefone bate
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
        logger.error(f"Erro ao buscar paciente por telefone: {e}")
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

    telefone = "".join(filter(str.isdigit, dados.get("telefone", "")))

    payload = {
        "Name": dados["nome"],
        "Birthdate": dados.get("data_nascimento"),
        "MobilePhone": telefone,
        "Email": dados.get("email", ""),
        "IsMale": dados.get("sexo", "F").upper() == "M",
        "Occupation": dados.get("profissao"),
        "ZipCode": dados.get("cep"),
        "Observation": dados.get("instagram", ""),
        "IsActive": True,
        "ServiceLocationId": id_local,
    }
    # Remove campos None
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

    payload = {
        "Type": "Consulta",
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
    }
    payload = {k: v for k, v in payload.items() if v is not None}

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
        "data": datetime.now(BRT).strftime("%Y-%m-%dT%H:%M:%S"),
        "descricao": descricao,
        "idPatient": id_paciente,
        "idAgenda": id_agenda,
        "tipo": "Receita",
        "pago": pago,
        "valor": valor,
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
