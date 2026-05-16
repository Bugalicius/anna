from __future__ import annotations

import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from dotenv import load_dotenv
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORT_DIR = ROOT / "docs" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _setup_env() -> Path:
    load_dotenv(ROOT / ".env")
    db_path = ROOT / "manual_chat_battery.db"
    if db_path.exists():
        db_path.unlink()
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["REDIS_URL"] = "redis://127.0.0.1:6399/0"
    os.environ["DISABLE_LLM_FOR_TESTS"] = "true"
    os.environ["ENABLE_TEST_CHAT"] = "true"
    os.environ["AUTO_CREATE_TABLES"] = "true"
    os.environ["GEMINI_API_KEY"] = "test-gemini-key"
    return db_path


@dataclass
class Scenario:
    slug: str
    title: str
    turns: list[str]
    profile: str = "novo"
    expected_any: list[str] = field(default_factory=list)
    forbidden_any: list[str] = field(default_factory=list)
    notes: str = ""


def _slot(day: str, date_fmt: str, hour: str, dt: str) -> dict[str, str]:
    return {"datetime": dt, "data_fmt": f"{day}, {date_fmt}", "hora": hour}


SLOTS_PRESENCIAL = [
    _slot("segunda", "27/04", "8h", "2026-04-27T08:00:00"),
    _slot("terça", "28/04", "15h", "2026-04-28T15:00:00"),
    _slot("quarta", "29/04", "19h", "2026-04-29T19:00:00"),
    _slot("quinta", "30/04", "9h", "2026-04-30T09:00:00"),
    _slot("sexta", "01/05", "16h", "2026-05-01T16:00:00"),
]

SLOTS_ONLINE = [
    _slot("segunda", "27/04", "9h", "2026-04-27T09:00:00"),
    _slot("terça", "28/04", "16h", "2026-04-28T16:00:00"),
    _slot("quarta", "29/04", "18h", "2026-04-29T18:00:00"),
    _slot("quinta", "30/04", "10h", "2026-04-30T10:00:00"),
]

RETORNO_SLOTS = [
    _slot("segunda", "04/05", "8h", "2026-05-04T08:00:00"),
    _slot("terça", "05/05", "15h", "2026-05-05T15:00:00"),
    _slot("quarta", "06/05", "18h", "2026-05-06T18:00:00"),
    _slot("quinta", "07/05", "9h", "2026-05-07T09:00:00"),
    _slot("sexta", "08/05", "16h", "2026-05-08T16:00:00"),
]


SCENARIOS: list[Scenario] = [
    Scenario(
        slug="agendamento_pix_completo",
        title="Novo paciente conclui agendamento por PIX",
        turns=[
            "Oi, quero agendar uma consulta",
            "Maria Silva, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro mesmo",
            "presencial",
            "prefiro de manhã",
            "1",
            "pix",
            "[comprovante valor=345]",
            "12/03/1992",
            "maria.silva@gmail.com",
        ],
        expected_any=["consulta foi confirmada", "confirmada com sucesso", "Aura Clinic"],
    ),
    Scenario(
        slug="agendamento_cartao_completo",
        title="Novo paciente conclui agendamento por cartão",
        turns=[
            "quero marcar consulta",
            "João Pedro Souza, sou novo",
            "ganhar massa",
            "consulta com retorno",
            "prefiro o ouro",
            "online",
            "noite",
            "3",
            "cartao",
            "paguei",
            "21/08/1989",
            "joao.souza@gmail.com",
        ],
        expected_any=["videochamada", "confirmada com sucesso", "link para pagamento"],
    ),
    Scenario(
        slug="desistencia_meio_do_agendamento",
        title="Paciente começa agendamento e desiste no meio",
        turns=[
            "Oi quero consulta",
            "Paula Dias, primeira vez",
            "emagrecer",
            "consulta individual",
            "não quero upgrade",
            "presencial",
            "manhã",
            "deixa pra lá, desisti",
        ],
        expected_any=["sem problemas", "mudar de ideia", "é só me chamar"],
    ),
    Scenario(
        slug="troca_modalidade_apos_plano",
        title="Paciente troca modalidade depois de escolher plano",
        turns=[
            "Quero agendar",
            "Fernanda Lima, sou nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "na verdade quero online",
            "tarde",
            "2",
            "pix",
        ],
        expected_any=["online", "pagamento antecipado", "PIX"],
    ),
    Scenario(
        slug="troca_plano_depois_de_escolher",
        title="Paciente escolhe um plano e depois pede outro",
        turns=[
            "Oi",
            "Carla Mendes, primeira consulta",
            "ganhar massa",
            "consulta individual",
            "na verdade quero trocar para ouro",
            "quero manter o ouro mesmo",
            "online",
        ],
        expected_any=["ouro", "consulta", "modalidade"],
    ),
    Scenario(
        slug="troca_forma_pagamento",
        title="Paciente muda de cartão para PIX",
        turns=[
            "Quero marcar consulta",
            "Rafaela Prado, nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "tarde",
            "2",
            "cartao",
            "na verdade quero pix",
        ],
        expected_any=["chave PIX", "sinal", "R$"],
    ),
    Scenario(
        slug="duvida_pagamento_no_meio",
        title="Paciente pergunta sobre pagamento no meio do fluxo",
        turns=[
            "Oi quero agendar",
            "Bianca Rocha, sou nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
            "como funciona o pagamento?",
        ],
        expected_any=["PIX", "cartão", "pagamento"],
    ),
    Scenario(
        slug="duvida_modalidade",
        title="Paciente pergunta diferença entre presencial e online",
        turns=[
            "Quero consulta",
            "Aline Costa, primeira consulta",
            "outro objetivo",
            "quais as modalidades?",
        ],
        expected_any=["presencial", "online", "videochamada"],
    ),
    Scenario(
        slug="duvida_clinica_explicita",
        title="Paciente faz dúvida clínica explícita",
        turns=[
            "Oi",
            "Luciana Nogueira, sou nova",
            "tenho diabetes, posso comer pão?",
        ],
        expected_any=["Thaynara", "equipe", "dúvidas clínicas"],
    ),
    Scenario(
        slug="fora_de_contexto_esporte",
        title="Paciente fala fora de contexto sobre futebol",
        turns=["qual o resultado do brasileirão?"],
        expected_any=["agendamentos", "consultas", "posso te ajudar"],
    ),
    Scenario(
        slug="fala_nada_com_nada",
        title="Paciente manda mensagem sem sentido",
        turns=["abacaxi avião camada cósmica"],
        expected_any=["agendamentos", "consultas", "posso te ajudar"],
    ),
    Scenario(
        slug="retorno_remarcacao_sucesso",
        title="Paciente de retorno consegue remarcar",
        profile="retorno",
        turns=[
            "quero remarcar minha consulta",
            "qualquer horário na próxima semana",
            "2",
        ],
        expected_any=["remarcada com sucesso", "nova data", "modalidade"],
    ),
    Scenario(
        slug="retorno_remarcacao_segunda_rodada",
        title="Paciente rejeita primeira rodada de slots e recebe outra",
        profile="retorno",
        turns=[
            "preciso remarcar",
            "qualquer horário",
            "nenhum desses horários funciona",
        ],
        expected_any=["mais opções", "Qual horário funciona melhor", "Vou buscar"],
    ),
    Scenario(
        slug="retorno_perda_retorno",
        title="Paciente esgota opções de remarcação e cai em perda de retorno",
        profile="retorno_sem_janela",
        turns=[
            "quero remarcar",
            "qualquer horário",
            "nenhum funciona",
            "também não consigo esses",
        ],
        expected_any=["prazo de remarcação", "nova consulta", "planos"],
    ),
    Scenario(
        slug="retorno_cancelamento",
        title="Paciente com consulta agendada quer cancelar",
        profile="retorno",
        turns=[
            "quero cancelar minha consulta",
            "tive um imprevisto",
        ],
        expected_any=["cancelada com sucesso", "retomar", "Thaynara"],
    ),
    Scenario(
        slug="retorno_sem_agenda_vira_novo",
        title="Paciente diz que é retorno mas não tem agenda ativa",
        profile="sem_agenda",
        turns=[
            "quero remarcar",
        ],
        expected_any=["não localizei", "fluxo de agendamento", "o que você está procurando"],
    ),
    Scenario(
        slug="objetivo_ja_na_primeira_mensagem",
        title="Paciente informa objetivo na primeira mensagem",
        turns=[
            "Oi, sou Mariana Alves, primeira consulta, quero emagrecer",
            "consulta individual",
        ],
        expected_any=["mídia kit", "opções", "consulta individual"],
    ),
    Scenario(
        slug="nome_incompleto",
        title="Paciente fornece só primeiro nome",
        turns=[
            "oi",
            "Marcos",
        ],
        expected_any=["nome e sobrenome", "primeira consulta", "já é paciente"],
    ),
    Scenario(
        slug="data_nascimento_invalida",
        title="Paciente informa data de nascimento inválida",
        turns=[
            "Quero agendar",
            "Tatiane Ribeiro, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "manhã",
            "1",
            "pix",
            "[comprovante valor=345]",
            "32/13/1999",
        ],
        expected_any=["data de nascimento", "DD/MM/AAAA", "mandar novamente"],
    ),
    Scenario(
        slug="email_invalido",
        title="Paciente informa e-mail inválido",
        turns=[
            "Quero agendar",
            "Isabela Martins, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
            "tarde",
            "2",
            "pix",
            "[comprovante valor=325]",
            "10/10/1990",
            "isabela arroba gmail",
        ],
        expected_any=["e-mail", "mandar novamente", "cadastro"],
    ),
    Scenario(
        slug="escolha_slot_por_rotulo",
        title="Paciente escolhe slot pelo texto completo",
        turns=[
            "Oi quero consulta",
            "Kelly Freitas, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
            "noite",
            "quarta, 29/04 18h",
        ],
        expected_any=["pagamento antecipado", "Qual opção prefere", "Cartão"],
    ),
    Scenario(
        slug="escolha_slot_por_button_id",
        title="Paciente escolhe slot pelo id do botão",
        turns=[
            "Oi quero agendar",
            "Lara Teles, nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "manhã",
            "slot_2",
        ],
        expected_any=["pagamento antecipado", "Qual opção prefere", "PIX"],
    ),
    Scenario(
        slug="objetivo_por_button_id",
        title="Paciente seleciona objetivo por id de botão",
        turns=[
            "Oi",
            "Bruna Faria, nova",
            "emagrecer",
        ],
        expected_any=["mídia kit", "opções", "Ouro"],
    ),
    Scenario(
        slug="plano_por_button_id",
        title="Paciente seleciona plano por id de lista",
        turns=[
            "Oi",
            "Cecilia Moura, primeira consulta",
            "emagrecer",
            "ouro",
        ],
        expected_any=["manter o Ouro", "Premium", "dica"],
    ),
    Scenario(
        slug="modalidade_por_button_id",
        title="Paciente seleciona modalidade por id de botão",
        turns=[
            "Quero consulta",
            "Patricia Sales, nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
        ],
        expected_any=["horário atende melhor", "Segunda a Sexta", "pagamento"],
    ),
    Scenario(
        slug="formulario_flow",
        title="Paciente pede formulário",
        turns=[
            "Quero o formulário",
            "Nina Castro, primeira consulta",
            "outro objetivo",
            "formulario",
            "paguei",
        ],
        expected_any=["R$ 100", "formulário", "comprovante"],
    ),
    Scenario(
        slug="pagar_no_consultorio",
        title="Paciente quer pagar só na hora da consulta",
        turns=[
            "Quero consulta",
            "Renata Braga, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "manhã",
            "1",
            "quero pagar lá na hora",
        ],
        expected_any=["pagamento antecipado", "política da clínica", "comprovante"],
    ),
    Scenario(
        slug="troca_modalidade_repetida",
        title="Paciente muda modalidade várias vezes",
        turns=[
            "Quero consulta",
            "Amanda Campos, nova",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
            "na verdade presencial",
            "agora melhor online",
        ],
        expected_any=["horário atende melhor", "Segunda a Sexta", "noite"],
    ),
    Scenario(
        slug="abandona_e_retoma",
        title="Paciente abandona assunto e depois retoma com outra intenção",
        turns=[
            "Quero consulta",
            "Gabi Torres, primeira consulta",
            "emagrecer",
            "deixa pra lá",
            "na verdade quero voltar e ver os planos",
        ],
        expected_any=["opções", "mídia kit", "planos"],
    ),
    Scenario(
        slug="comprovante_valor_divergente",
        title="Paciente manda comprovante com valor divergente",
        turns=[
            "Quero agendar",
            "Helena Souza, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "manhã",
            "1",
            "pix",
            "[comprovante valor=100.00]",
        ],
        expected_any=["valor identificado", "sinal", "envie o comprovante novamente"],
    ),
    Scenario(
        slug="sem_slots_disponiveis",
        title="Paciente chega a etapa de slots e não há disponibilidade",
        profile="sem_slots",
        turns=[
            "Quero consulta",
            "Juliana Mota, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "presencial",
            "manhã",
        ],
        expected_any=["não encontrei horários", "verificar opções", "Thaynara"],
    ),
    Scenario(
        slug="mensagem_ambigua_com_duvida",
        title="Paciente mistura dúvida e pedido de agendamento",
        turns=[
            "Oi, queria saber se online funciona e talvez agendar",
            "Vanessa Pires, sou nova",
            "emagrecer",
        ],
        expected_any=["online", "videochamada", "principal objetivo"],
    ),
    Scenario(
        slug="correcao_horario",
        title="Paciente muda preferência de horário depois de ver slots",
        turns=[
            "Quero consulta",
            "Monique Dantas, primeira consulta",
            "emagrecer",
            "ouro",
            "quero manter o ouro",
            "online",
            "manhã",
            "na verdade prefiro noite",
        ],
        expected_any=["não encontrei opções", "separei os 3 horários", "Qual horário funciona melhor"],
    ),
]


class FakeDietbox:
    def __init__(self) -> None:
        self.phone_to_patient: dict[str, dict[str, Any]] = {}
        self.phone_to_agenda: dict[str, dict[str, Any]] = {}
        self.transactions: dict[str, dict[str, Any]] = {}
        self.cancelled: set[str] = set()
        self.no_slots = False

    def reset_for(self, phone: str, profile: str) -> None:
        self.phone_to_patient.pop(phone, None)
        self.phone_to_agenda.pop(phone, None)
        self.no_slots = profile == "sem_slots"

        if profile == "retorno":
            self.phone_to_patient[phone] = {"id": 9001, "nome": "Paciente Retorno", "telefone": phone}
            self.phone_to_agenda[phone] = {
                "id": "AGENDA-RET-001",
                "inicio": "2026-04-25T09:00:00",
                "fim": "2026-04-25T10:00:00",
                "id_servico": "SVC-RET-001",
            }
            self.transactions["TRANS-RET-001"] = {"pago": True}
        elif profile == "retorno_sem_janela":
            self.phone_to_patient[phone] = {"id": 9002, "nome": "Paciente Sem Janela", "telefone": phone}
            self.phone_to_agenda[phone] = {
                "id": "AGENDA-RET-002",
                "inicio": "2026-04-25T11:00:00",
                "fim": "2026-04-25T12:00:00",
                "id_servico": "SVC-RET-002",
            }
            self.transactions["TRANS-RET-002"] = {"pago": True}
        elif profile == "sem_agenda":
            self.phone_to_patient[phone] = {"id": 9003, "nome": "Paciente Sem Agenda", "telefone": phone}

    def consultar_slots_disponiveis(self, modalidade: str = "presencial", dias_a_frente: int = 14, data_inicio=None):
        if self.no_slots:
            return []
        if modalidade == "online":
            return list(SLOTS_ONLINE)
        return list(SLOTS_PRESENCIAL)

    def processar_agendamento(
        self,
        dados_paciente: dict,
        dt_consulta,
        modalidade: str,
        plano: str,
        valor_sinal: float,
        forma_pagamento: str,
    ) -> dict[str, Any]:
        phone = dados_paciente["telefone"]
        patient = self.phone_to_patient.get(phone) or {
            "id": 1000 + len(self.phone_to_patient) + 1,
            "nome": dados_paciente["nome"],
            "telefone": phone,
        }
        self.phone_to_patient[phone] = patient
        agenda_id = f"AGENDA-{patient['id']}"
        trans_id = f"TRANS-{patient['id']}"
        self.phone_to_agenda[phone] = {
            "id": agenda_id,
            "inicio": dt_consulta.isoformat(),
            "fim": dt_consulta.isoformat(),
            "id_servico": f"SVC-{plano.upper()}",
        }
        self.transactions[trans_id] = {"pago": False, "valor": valor_sinal}
        return {
            "sucesso": True,
            "id_paciente": patient["id"],
            "id_agenda": agenda_id,
            "id_transacao": trans_id,
        }

    def buscar_paciente_por_telefone(self, telefone: str) -> dict[str, Any] | None:
        return self.phone_to_patient.get(telefone)

    def consultar_agendamento_ativo(self, id_paciente: int) -> dict[str, Any] | None:
        for patient in self.phone_to_patient.values():
            if patient["id"] == id_paciente:
                return self.phone_to_agenda.get(patient["telefone"])
        return None

    def verificar_lancamento_financeiro(self, id_agenda: str) -> bool:
        return id_agenda.startswith("AGENDA-RET")

    def alterar_agendamento(self, id_agenda: str, novo_dt_inicio, observacao: str) -> bool:
        for phone, agenda in self.phone_to_agenda.items():
            if agenda["id"] == id_agenda:
                agenda["inicio"] = novo_dt_inicio.isoformat()
                agenda["fim"] = novo_dt_inicio.isoformat()
                return True
        return False

    def cancelar_agendamento(self, id_agenda: str, observacao: str = "") -> bool:
        self.cancelled.add(id_agenda)
        return True

    def confirmar_pagamento(self, id_transacao: str) -> bool:
        if id_transacao in self.transactions:
            self.transactions[id_transacao]["pago"] = True
            return True
        return False


def _fake_slots_remarcar(modalidade: str, preferencia: dict | None, fim_janela: str | None, excluir=None, pool=None):
    if pool is not None:
        todos = pool
    elif fim_janela == "2026-05-01":
        todos = list(RETORNO_SLOTS[:3])
    else:
        todos = list(RETORNO_SLOTS)
    excluir_set = set(excluir or [])
    disponiveis = [s for s in todos if s["datetime"] not in excluir_set]
    return {"slots": disponiveis[:3], "slots_pool": todos, "aviso_preferencia": None}


def _fake_detectar_tipo_remarcacao(fake_db: FakeDietbox, phone: str) -> dict[str, Any]:
    patient = fake_db.buscar_paciente_por_telefone(phone)
    if not patient:
        return {"tipo_remarcacao": "nova_consulta", "consulta_atual": None}
    agenda = fake_db.consultar_agendamento_ativo(patient["id"])
    if not agenda:
        return {"tipo_remarcacao": "nova_consulta", "consulta_atual": None}
    if agenda["id"] == "AGENDA-RET-002":
        return {
            "tipo_remarcacao": "retorno",
            "consulta_atual": agenda,
            "fim_janela": "2026-05-01",
        }
    if not fake_db.verificar_lancamento_financeiro(agenda["id"]):
        return {"tipo_remarcacao": "nova_consulta", "consulta_atual": None}
    return {
        "tipo_remarcacao": "retorno",
        "consulta_atual": agenda,
        "fim_janela": "2026-05-08",
    }


def _fake_gerar_link(*args, **kwargs):
    from app.integrations.payment_gateway import LinkPagamento

    return LinkPagamento(
        url="https://pagamento.exemplo/checkout/abc123",
        valor=768.00,
        parcelas=6,
        parcela_valor=128.00,
        sucesso=True,
        erro=None,
    )


def _hash_phone(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:64]


class FakeMeta:
    async def send_text(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-text"}]}

    async def send_template(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-template"}]}

    async def send_interactive_buttons(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-buttons"}]}

    async def send_interactive_list(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-list"}]}

    async def send_contact(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-contact"}]}

    async def send_document(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-document"}]}

    async def send_image(self, *args, **kwargs) -> dict[str, Any]:
        return {"messages": [{"id": "fake-meta-image"}]}


def _evaluate(scenario: Scenario, transcript: list[dict[str, Any]]) -> tuple[str, list[str]]:
    text = "\n".join(
        "\n".join(turn["responses"]) for turn in transcript if turn["responses"]
    ).lower()
    issues: list[str] = []
    for needle in scenario.expected_any:
        if needle.lower() not in text:
            issues.append(f"Esperado conter: {needle}")
    for needle in scenario.forbidden_any:
        if needle.lower() in text:
            issues.append(f"Não deveria conter: {needle}")
    status = "PASS" if not issues else "FAIL"
    return status, issues


def _write_report(results: list[dict[str, Any]], db_path: Path) -> tuple[Path, Path]:
    json_path = REPORT_DIR / "manual_chat_battery_results.json"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    lines: list[str] = [
        "# Bateria Manual - Agente Ana",
        "",
        f"- Total de cenários executados: {len(results)}",
        f"- PASS: {sum(1 for r in results if r['status'] == 'PASS')}",
        f"- FAIL: {sum(1 for r in results if r['status'] == 'FAIL')}",
        f"- Banco temporário: `{db_path.name}`",
        "",
        "## Resumo",
        "",
        "| # | Cenário | Status | Observações |",
        "|---|---|---|---|",
    ]

    for r in results:
        obs = "; ".join(r["issues"]) if r["issues"] else "-"
        lines.append(f"| {r['id']} | {r['title']} | {r['status']} | {obs} |")

    lines.append("")
    lines.append("## Transcrições")
    lines.append("")

    for r in results:
        lines.append(f"### {r['id']}. {r['title']} [{r['status']}]")
        lines.append("")
        if r["issues"]:
            for issue in r["issues"]:
                lines.append(f"- {issue}")
            lines.append("")
        for turn in r["transcript"]:
            lines.append(f"**Paciente:** {turn['message']}")
            if not turn["responses"]:
                lines.append("**Ana:** _(sem resposta)_")
            else:
                for resp in turn["responses"]:
                    lines.append(f"**Ana:** {resp}")
            lines.append("")
        lines.append(f"Estado final: `{json.dumps(r['final_state'], ensure_ascii=False)}`")
        lines.append(f"Contato: `{json.dumps(r['contact'], ensure_ascii=False)}`")
        lines.append("")

    md_path = REPORT_DIR / "manual_chat_battery_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    db_path = _setup_env()

    from app.main import app
    from app.conversation import state as conv_state
    from app.database import SessionLocal
    from app.models import Contact

    fake_db = FakeDietbox()
    results: list[dict[str, Any]] = []

    patches = [
        patch("app.integrations.dietbox.consultar_slots_disponiveis", side_effect=fake_db.consultar_slots_disponiveis),
        patch("app.integrations.dietbox.processar_agendamento", side_effect=fake_db.processar_agendamento),
        patch("app.integrations.dietbox.buscar_paciente_por_telefone", side_effect=fake_db.buscar_paciente_por_telefone),
        patch("app.integrations.dietbox.consultar_agendamento_ativo", side_effect=fake_db.consultar_agendamento_ativo),
        patch("app.integrations.dietbox.verificar_lancamento_financeiro", side_effect=fake_db.verificar_lancamento_financeiro),
        patch("app.integrations.dietbox.alterar_agendamento", side_effect=fake_db.alterar_agendamento),
        patch("app.integrations.dietbox.cancelar_agendamento", side_effect=fake_db.cancelar_agendamento),
        patch("app.integrations.dietbox.confirmar_pagamento", side_effect=fake_db.confirmar_pagamento),
        patch("app.integrations.payment_gateway.gerar_link_pagamento", side_effect=_fake_gerar_link),
    ]

    # patches especiais async
    async def _consultar_slots_remarcar_async(modalidade, preferencia, fim_janela, excluir=None, pool=None):
        return _fake_slots_remarcar(modalidade, preferencia, fim_janela, excluir, pool)

    async def _detectar_tipo_async(telefone):
        return _fake_detectar_tipo_remarcacao(fake_db, telefone)

    async def _no_llm(*args, **kwargs):
        return None

    async def _lock_ok(*args, **kwargs):
        return True

    async def _lock_release(*args, **kwargs):
        return None

    patches.extend([
        patch("app.tools.scheduling.consultar_slots_remarcar", side_effect=_consultar_slots_remarcar_async),
        patch("app.tools.patients.detectar_tipo_remarcacao", side_effect=_detectar_tipo_async),
        patch("app.chatwoot_bridge.is_human_handoff_active", return_value=False),
        patch("app.conversation.alerter_simples.MetaAPIClient", FakeMeta),
        patch("app.conversation.interpreter._interpretar_gemini", side_effect=_no_llm),
        patch("app.llm_client.complete_text_async", side_effect=_no_llm),
        patch("app.conversation.orchestrator._acquire_processing_lock", side_effect=_lock_ok),
        patch("app.conversation.orchestrator._release_processing_lock", side_effect=_lock_release),
    ])

    with ExitStack() as stack:
        for item in patches:
            stack.enter_context(item)
        with TestClient(app) as client:
            conv_state._state_mgr = None
            for idx, scenario in enumerate(SCENARIOS, start=1):
                print(f"[{idx:02d}/{len(SCENARIOS)}] {scenario.slug}", flush=True)
                phone = f"55000000{idx:04d}"
                phone_hash = _hash_phone(phone)
                conv_state._mem_store.clear()
                fake_db.reset_for(phone, scenario.profile)

                client.post("/test/reset", json={"phone": phone})
                transcript: list[dict[str, Any]] = []

                for turn in scenario.turns:
                    resp = client.post("/test/chat", json={"phone": phone, "message": turn})
                    payload = resp.json()
                    transcript.append({"message": turn, "responses": payload["responses"]})

                state = asyncio.run(conv_state.load_state(phone_hash, phone))
                with SessionLocal() as db:
                    contact = db.query(Contact).filter_by(phone_hash=phone_hash).first()
                    contact_info = {
                        "stage": getattr(contact, "stage", None),
                        "collected_name": getattr(contact, "collected_name", None),
                        "first_name": getattr(contact, "first_name", None),
                    }

                status, issues = _evaluate(scenario, transcript)
                results.append(
                    {
                        "id": idx,
                        "slug": scenario.slug,
                        "title": scenario.title,
                        "profile": scenario.profile,
                        "status": status,
                        "issues": issues,
                        "notes": scenario.notes,
                        "transcript": transcript,
                        "final_state": state,
                        "contact": contact_info,
                    }
                )
                _write_report(results, db_path)

    json_path, md_path = _write_report(results, db_path)

    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")


if __name__ == "__main__":
    main()
