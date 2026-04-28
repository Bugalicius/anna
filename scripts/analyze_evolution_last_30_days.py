from __future__ import annotations

import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "docs" / "reports" / "whatsapp_last_30_days_report.md"
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
POSTGRES_CONTAINER = "evolution_postgres"
POSTGRES_USER = "evolution"
POSTGRES_DB = "evolution"


REMARCACAO_WORDS = [
    "remarc",
    "reagend",
    "desmarc",
    "mudar horario",
    "mudar horário",
    "trocar horario",
    "trocar horário",
    "outro horario",
    "outro horário",
    "novo horario",
    "novo horário",
]

PAYMENT_WORDS = ["pix", "cartao", "cartão", "pagamento", "paguei", "comprovante", "valor"]
SCHEDULING_WORDS = ["agenda", "agendar", "consulta", "horario", "horário", "disponibilidade"]
FRIENDLY_WORDS = [
    "claro",
    "perfeito",
    "sem problema",
    "sem problemas",
    "tranquilo",
    "combinado",
    "vou verificar",
    "ja verifico",
    "já verifico",
    "me chama",
    "te aviso",
]
RIGID_WORDS = [
    "informe",
    "necessario",
    "necessário",
    "politica",
    "política",
    "nao foi possivel",
    "não foi possível",
    "aguarde",
    "opcao invalida",
    "opção inválida",
]
INTERNAL_NAME_WORDS = ["nutricionista", "atendente nutri", "thaynara teixeira"]


@dataclass
class Message:
    dt: datetime
    remote_jid: str
    chat_name: str
    push_name: str
    from_me: bool
    message_type: str
    text: str


def _run_psql(sql: str) -> list[str]:
    cmd = [
        "docker",
        "exec",
        POSTGRES_CONTAINER,
        "psql",
        "-U",
        POSTGRES_USER,
        "-d",
        POSTGRES_DB,
        "-At",
        "-c",
        sql,
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _extract_text(message_type: str, payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict):
        return ""

    candidates = [
        payload.get("conversation"),
        payload.get("extendedTextMessage", {}).get("text"),
        payload.get("imageMessage", {}).get("caption"),
        payload.get("videoMessage", {}).get("caption"),
        payload.get("documentMessage", {}).get("caption"),
        payload.get("documentMessage", {}).get("title"),
        payload.get("documentMessage", {}).get("fileName"),
        payload.get("buttonsResponseMessage", {}).get("selectedDisplayText"),
        payload.get("listResponseMessage", {}).get("title"),
        payload.get("templateButtonReplyMessage", {}).get("selectedDisplayText"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return _clean_text(candidate)

    if message_type == "audioMessage":
        return "[audio]"
    if message_type == "imageMessage":
        return "[imagem]"
    if message_type == "documentMessage":
        return "[documento]"
    if message_type == "stickerMessage":
        return "[figurinha]"
    if message_type == "reactionMessage":
        return "[reacao]"
    return f"[{message_type}]"


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _mask_contact(remote_jid: str, chat_name: str, push_name: str) -> str:
    base = chat_name or push_name or remote_jid.split("@")[0]
    digits = "".join(ch for ch in remote_jid if ch.isdigit())
    suffix = digits[-4:] if digits else "----"
    first = base.split()[0] if base else "Contato"
    return f"{first} (...{suffix})"


def _is_internal(msg: Message) -> bool:
    joined = f"{msg.chat_name} {msg.push_name}".lower()
    return any(word in joined for word in INTERNAL_NAME_WORDS)


def _contains_any(text: str, words: list[str]) -> bool:
    low = text.lower()
    return any(word in low for word in words)


def _fetch_messages(days: int) -> list[Message]:
    since_epoch = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    sql = f"""
    with normalized as (
      select
        m.*,
        case
          when coalesce(m.key->>'remoteJid', '') like '%@s.whatsapp.net' then m.key->>'remoteJid'
          when coalesce(m.key->>'remoteJidAlt', '') like '%@s.whatsapp.net' then m.key->>'remoteJidAlt'
          else coalesce(m.key->>'remoteJid', m.key->>'remoteJidAlt', '')
        end as normalized_remote_jid
      from "Message" m
    )
    select json_build_object(
        'timestamp', m."messageTimestamp",
        'remote_jid', m.normalized_remote_jid,
        'chat_name', coalesce(c.name, ''),
        'push_name', coalesce(m."pushName", ''),
        'from_me', coalesce((m.key->>'fromMe')::boolean, false),
        'message_type', coalesce(m."messageType", ''),
        'message', m.message
    )::text
    from normalized m
    left join "Chat" c
      on c."remoteJid" = m.normalized_remote_jid
    where m."messageTimestamp" >= {since_epoch}
      and m.normalized_remote_jid not like '%@g.us'
      and m.normalized_remote_jid not like '%@broadcast'
    order by m."messageTimestamp" asc;
    """
    rows = _run_psql(sql)
    messages: list[Message] = []
    for row in rows:
        item = json.loads(row)
        text = _extract_text(item["message_type"], item.get("message") or {})
        if not text:
            continue
        messages.append(
            Message(
                dt=datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).astimezone(LOCAL_TZ),
                remote_jid=item["remote_jid"],
                chat_name=item["chat_name"],
                push_name=item["push_name"],
                from_me=bool(item["from_me"]),
                message_type=item["message_type"],
                text=text,
            )
        )
    return messages


def _next_reply(messages: list[Message], index: int) -> Message | None:
    remote = messages[index].remote_jid
    for candidate in messages[index + 1 :]:
        if candidate.remote_jid != remote:
            continue
        if candidate.from_me:
            return candidate
        if (candidate.dt - messages[index].dt).total_seconds() > 60 * 60 * 24 * 3:
            return None
    return None


def _short(text: str, limit: int = 210) -> str:
    text = _clean_text(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _conversation_windows(messages: list[Message], remote_jid: str, around: Message, radius: int = 3) -> list[Message]:
    conv = [m for m in messages if m.remote_jid == remote_jid]
    idx = next((i for i, m in enumerate(conv) if m is around), -1)
    if idx < 0:
        return []
    return conv[max(0, idx - radius) : idx + radius + 1]


def build_report(days: int = 30) -> str:
    messages = _fetch_messages(days)
    by_remote: dict[str, list[Message]] = defaultdict(list)
    for msg in messages:
        by_remote[msg.remote_jid].append(msg)

    inbound = [m for m in messages if not m.from_me]
    outbound = [m for m in messages if m.from_me]
    by_day = Counter(m.dt.date().isoformat() for m in messages)
    active_chats = Counter({jid: len(items) for jid, items in by_remote.items()})
    type_counts = Counter(m.message_type for m in messages)

    internal_messages = [m for m in messages if _is_internal(m)]
    client_messages = [m for m in messages if not _is_internal(m)]

    remarcacao_hits = [
        (idx, m)
        for idx, m in enumerate(messages)
        if not m.from_me and not _is_internal(m) and _contains_any(m.text, REMARCACAO_WORDS)
    ]
    remotes_with_remarcacao = {m.remote_jid for _, m in remarcacao_hits}
    internal_remarcacao = [
        m for m in internal_messages if not m.from_me and _contains_any(m.text, REMARCACAO_WORDS)
    ]

    reply_delays: list[float] = []
    remarcacao_pairs: list[tuple[Message, Message | None, float | None]] = []
    for idx, msg in remarcacao_hits:
        reply = _next_reply(messages, idx)
        delay_min = None
        if reply:
            delay_min = (reply.dt - msg.dt).total_seconds() / 60
            reply_delays.append(delay_min)
        remarcacao_pairs.append((msg, reply, delay_min))

    friendly_count = sum(1 for m in outbound if _contains_any(m.text, FRIENDLY_WORDS))
    rigid_count = sum(1 for m in outbound if _contains_any(m.text, RIGID_WORDS))
    payment_count = sum(1 for m in messages if _contains_any(m.text, PAYMENT_WORDS))
    scheduling_count = sum(1 for m in messages if _contains_any(m.text, SCHEDULING_WORDS))

    unanswered: list[Message] = []
    for jid, conv in by_remote.items():
        last_inbound = next((m for m in reversed(conv) if not m.from_me), None)
        last_outbound = next((m for m in reversed(conv) if m.from_me), None)
        if last_inbound and (not last_outbound or last_inbound.dt > last_outbound.dt):
            unanswered.append(last_inbound)
    unanswered.sort(key=lambda m: m.dt, reverse=True)

    lines: list[str] = [
        "# Relatorio WhatsApp - Ultimos 30 dias",
        "",
        f"- Periodo analisado: ultimos {days} dias ate {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"- Mensagens texto/midia registradas: {len(messages)}",
        f"- Recebidas: {len(inbound)}",
        f"- Enviadas por voce/Ana: {len(outbound)}",
        f"- Conversas individuais: {len(by_remote)}",
        f"- Mensagens em conversas internas detectadas: {len(internal_messages)}",
        f"- Conversas com sinais de remarcacao: {len(remotes_with_remarcacao)}",
        f"- Pedidos/mencoes de remarcacao detectados: {len(remarcacao_hits)}",
        f"- Mencoes internas de remarcacao separadas da analise de clientes: {len(internal_remarcacao)}",
        "",
        "## Volume por dia",
        "",
    ]
    for day, count in sorted(by_day.items()):
        lines.append(f"- {day}: {count}")

    lines.extend(["", "## Tipos de mensagem", ""])
    for msg_type, count in type_counts.most_common(12):
        lines.append(f"- {msg_type}: {count}")

    lines.extend(["", "## Conversas mais ativas", ""])
    for jid, count in active_chats.most_common(15):
        sample = by_remote[jid][-1]
        lines.append(f"- {_mask_contact(jid, sample.chat_name, sample.push_name)}: {count} mensagens")

    lines.extend(["", "## Sinais gerais", ""])
    lines.append(f"- Mensagens com tema de agenda/consulta/horario: {scheduling_count}")
    lines.append(f"- Mensagens com tema de pagamento/comprovante/valor: {payment_count}")
    lines.append(f"- Respostas suas com marcadores acolhedores: {friendly_count}")
    lines.append(f"- Respostas suas com marcadores mais rigidos/operacionais: {rigid_count}")

    if reply_delays:
        sorted_delays = sorted(reply_delays)
        avg = sum(sorted_delays) / len(sorted_delays)
        median = sorted_delays[len(sorted_delays) // 2]
        lines.extend(["", "## Remarcacao - tempos de resposta", ""])
        lines.append(f"- Pedidos com resposta detectada: {len(reply_delays)}")
        lines.append(f"- Tempo medio ate sua primeira resposta: {avg:.1f} min")
        lines.append(f"- Mediana: {median:.1f} min")
        lines.append(f"- Respostas em ate 15 min: {sum(1 for d in sorted_delays if d <= 15)}")

    lines.extend(["", "## Remarcacao - exemplos curtos", ""])
    for msg, reply, delay in remarcacao_pairs[:25]:
        label = _mask_contact(msg.remote_jid, msg.chat_name, msg.push_name)
        delay_txt = f"{delay:.1f} min" if delay is not None else "sem resposta localizada"
        lines.append(f"- {msg.dt:%d/%m %H:%M} | {label} | cliente: {_short(msg.text, 150)}")
        if reply:
            lines.append(f"  resposta ({delay_txt}): {_short(reply.text, 190)}")
        else:
            lines.append(f"  resposta: {delay_txt}")

    lines.extend(["", "## Possiveis pendencias sem resposta posterior", ""])
    for msg in unanswered[:20]:
        label = _mask_contact(msg.remote_jid, msg.chat_name, msg.push_name)
        lines.append(f"- {msg.dt:%d/%m %H:%M} | {label}: {_short(msg.text, 180)}")

    lines.extend(
        [
            "",
            "## Leitura qualitativa",
            "",
            "- O fluxo humano observado nas remarcacoes tende a funcionar melhor quando primeiro acolhe o imprevisto, depois confirma que vai verificar a agenda, e so entao conduz para opcoes objetivas.",
            "- O agente deve evitar abrir com texto burocratico quando a cliente pede para remarcar. A primeira resposta precisa soar como alguem assumindo o caso: 'Claro, consigo ver isso pra voce. Me fala qual periodo fica melhor?'.",
            "- Quando nao houver horario ideal, o tom deve reconhecer a restricao da cliente antes de oferecer alternativa. Isso reduz a sensacao de resposta automatica.",
            "- A Ana deve preservar contexto: se a cliente pediu 'nao consigo nesse horario', a proxima mensagem nao deve repetir a lista padrao inteira; deve dizer que entendeu a troca e procurar outra janela.",
            "- Remarcacao deve ter microconfirmacoes: reconhecer pedido, validar prazo/regra se necessario, oferecer alternativas, confirmar escolha, fechar com data/local e uma frase humana curta.",
            "- Respostas muito curtas como 'Bom dia', 'Boa tarde', 'Siim' ou 'nao tenho' ate soam humanas, mas deixam o atendimento incompleto. O agente precisa manter a naturalidade dessas respostas e acrescentar o proximo passo.",
            "- A resposta mais humana encontrada no padrao foi a que combina permissao e orientacao: 'Podemos remarcar sim, sem problema...' seguida de contexto sobre agenda cheia. Esse estilo deve virar referencia, mas com frases menores.",
            "",
            "## Plano de acao para deixar a Ana mais humana",
            "",
            "1. Criar um modo especifico de remarcacao com mensagens menos formularizadas.",
            "2. Antes de qualquer regra, responder com acolhimento curto: 'Claro', 'sem problema', 'vou tentar te ajudar com isso'.",
            "3. Guardar o motivo/contexto da remarcacao quando a cliente der espontaneamente, sem pedir motivo se nao for necessario.",
            "4. Trocar repeticao de menus por respostas contextuais: se ja havia slots, interpretar rejeicao, preferencia de turno/dia e buscar nova rodada.",
            "5. Para perda de prazo de retorno, explicar com delicadeza: reconhecer que entende, informar a regra, e ja emendar o caminho para nova consulta sem parecer punição.",
            "6. Ajustar mensagens de erro: nunca dizer apenas 'nao foi possivel'; sempre dizer o que a Ana esta fazendo agora ou qual alternativa existe.",
            "7. Incluir variacoes naturais de texto para evitar que todo atendimento pareca template.",
            "8. Usar fechamento de remarcacao com tom de secretaria humana: 'Prontinho, deixei sua consulta remarcada para...'.",
            "",
            "## Padroes de mensagem para implementar",
            "",
            "### Pedido simples de remarcacao",
            "",
            "Cliente: 'Preciso remarcar minha consulta.'",
            "",
            "Ana: 'Claro, sem problema. Vou tentar te ajudar com isso. Voce prefere algum dia ou periodo da semana?'",
            "",
            "### Cliente ja informou motivo",
            "",
            "Cliente: 'Vou precisar remarcar, agarrei no trabalho.'",
            "",
            "Ana: 'Entendi. Sem problema, acontece. Vou olhar a agenda pra voce. Qual periodo fica melhor: manha, tarde ou noite?'",
            "",
            "### Cliente ja pediu data/horario especifico",
            "",
            "Cliente: 'Consegue dia 28/04 as 19h?'",
            "",
            "Ana: 'Vou conferir esse horario pra voce. Se nao tiver exatamente as 19h, posso te mandar os horarios mais proximos?'",
            "",
            "### Nao tem o horario pedido",
            "",
            "Ana: 'Esse horario especifico eu nao tenho mais. O mais proximo que encontrei foi quinta as 18h ou sexta as 9h. Algum desses te ajuda?'",
            "",
            "### Cliente rejeitou opcoes",
            "",
            "Cliente: 'Esses nao consigo.'",
            "",
            "Ana: 'Tudo bem. Vou procurar outra janela. Voce quer que eu priorize o mesmo turno ou pode ser qualquer horario?'",
            "",
            "### Perda de prazo de retorno",
            "",
            "Ana: 'Entendo. Como o prazo do retorno ja passou, nao consigo remarcar como retorno. Mas posso te ajudar a ver uma nova consulta com a Thaynara e tentar achar um horario bom pra voce.'",
            "",
            "### Fechamento",
            "",
            "Ana: 'Prontinho, deixei sua consulta remarcada para quinta, 30/04, as 18h. Qualquer imprevisto, me chama por aqui.'",
            "",
            "## Coisas que o agente deve evitar",
            "",
            "- Responder remarcacao com o menu completo de agendamento.",
            "- Pedir dados cadastrais quando a pessoa ja e paciente e esta so tentando remarcar.",
            "- Dizer apenas 'nao tenho' sem oferecer alternativa.",
            "- Dar regra antes de acolher o pedido.",
            "- Repetir a mesma frase de introducao em toda troca.",
            "- Confirmar remarcacao sem mencionar data, horario e modalidade.",
            "",
            "## Criterios de aceite para as correcoes",
            "",
            "- Em pedido de remarcacao, a primeira resposta deve conter acolhimento + proximo passo.",
            "- Se houver preferencia de dia/turno/hora, ela deve ficar salva no estado.",
            "- Se a cliente rejeitar slots, a Ana deve buscar nova rodada sem reiniciar o fluxo.",
            "- Se nao houver disponibilidade, a Ana deve oferecer alternativa concreta ou avisar que vai verificar com a Thaynara.",
            "- A mensagem final de remarcacao deve parecer escrita por pessoa: curta, contextual e com 'prontinho' ou equivalente.",
            "- Nenhum fluxo de remarcacao deve enviar midia kit, planos ou coleta de nome, salvo quando for realmente perda de retorno/nova consulta.",
            "",
            "## Regras sugeridas para o agente",
            "",
            "- Se detectar remarcacao: nao enviar apresentacao de planos, nao reiniciar atendimento e nao pedir dados cadastrais.",
            "- Se cliente rejeitar horario: reconhecer rejeicao e buscar proxima opcao compativel com a preferencia.",
            "- Se cliente pedir urgencia: priorizar resposta curta e objetiva, sem texto comercial.",
            "- Se cliente demonstrar culpa/imprevisto: responder sem julgamento e reduzir friccao.",
            "- Se precisar aplicar regra de 24h/prazo: explicar em uma frase e oferecer o proximo caminho imediatamente.",
        ]
    )

    return "\n".join(lines)


def main() -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(days=30)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Relatorio gerado em: {REPORT_PATH}")


if __name__ == "__main__":
    main()
