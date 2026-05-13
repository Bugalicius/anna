"""Analisa o export de conversas reais e gera relatório de casos críticos."""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode("ascii")


def _texto_msg(msg: dict[str, Any]) -> str:
    return str(
        msg.get("text")
        or (msg.get("message") or {}).get("conversation")
        or (msg.get("message") or {}).get("extendedTextMessage", {}).get("text")
        or ""
    ).strip()


def _paciente_msgs(conv: dict[str, Any]) -> list[str]:
    return [_texto_msg(m) for m in conv.get("messages") or [] if not m.get("fromMe") and _texto_msg(m)]


def _ana_msgs(conv: dict[str, Any]) -> list[str]:
    return [_texto_msg(m) for m in conv.get("messages") or [] if m.get("fromMe") and _texto_msg(m)]


PALAVRAS_AGRESSAO = [
    "merda", "porra", "caralho", "tomar no", "cu", "buceta", "burra",
    "incompetente", "lixo", "vagabundo", "vagabunda", "procon", "processar",
    "denunciar", "enrolado", "enrolando",
]
TERMOS_EMOCIONAIS = [
    "depressao", "ansiedade", "panico", "crise", "chorando", "luto",
    "morreu", "falecimento", "compulsao",
]
TERMOS_MANIPULACAO = [
    "amigo da thay", "amiga da thay", "amigo da thaynara", "ja paguei",
    "sem pagar", "desconto", "metade", "depois pago", "comprovante falso",
]
TERMOS_TECNICOS = ["audio", "áudio", "foto", "imagem", "video", "vídeo", "documento", "pdf"]
TERMOS_NEGOCIO = [
    "ozempic", "remedio", "remédio", "lipo", "dentista", "estetica", "estética",
    "bronze", "reembolso", "transferir", "cachorro", "grupo",
]


@dataclass
class ConversaCritica:
    conversa_id: str
    tipo: str
    score_complexidade: int
    problemas: list[str]
    mensagens_paciente: int
    mensagens_total: int
    exemplo_paciente: str
    resposta_ana_referencia: str
    resposta_v2_esperada: str


def classificar_tipo(texto_norm: str) -> str:
    if any(t in texto_norm for t in ("cancelar", "desmarcar", "cancelamento")):
        return "cancelamento"
    if any(t in texto_norm for t in ("remarcar", "reagendar", "mudar horario", "trocar horario")):
        return "remarcacao"
    if any(t in texto_norm for t in ("confirmar presenca", "confirmo", "vou estar")):
        return "confirmacao"
    if any(t in texto_norm for t in ("valor", "quanto custa", "como funciona", "informacao")):
        return "duvida"
    if any(t in texto_norm for t in ("agendar", "consulta", "horario", "marcar")):
        return "agendamento"
    return "outro"


def identificar_problemas(textos: list[str]) -> list[str]:
    joined = " ".join(textos)
    n = _norm(joined)
    problemas: list[str] = []
    if any(t in n for t in PALAVRAS_AGRESSAO):
        problemas.append("agressao_ameaca")
    if any(t in n for t in TERMOS_EMOCIONAIS):
        problemas.append("emocional_clinico")
    if any(t in n for t in TERMOS_MANIPULACAO):
        problemas.append("manipulacao_negociacao")
    if any(t in n for t in TERMOS_TECNICOS) or any(len(t) <= 2 for t in textos):
        problemas.append("midia_ou_mensagem_curta")
    if any(t in n for t in TERMOS_NEGOCIO):
        problemas.append("negocio_incomum")
    if any(t in n for t in ("gravida", "gestante", "gestacao", "gravidez")):
        problemas.append("gestante")
    if re.search(r"\b(?:filh[ao]|tenho|paciente tem)\s+(?:de\s+)?(?:1[0-5]|\d)\s+anos\b", n):
        problemas.append("menor_16")
    if len(textos) >= 12:
        problemas.append("conversa_longa")
    if not problemas:
        problemas.append("complexidade_baixa")
    return problemas


def resposta_v2_esperada(problemas: list[str]) -> str:
    if "agressao_ameaca" in problemas:
        return "Resposta curta e profissional; na reincidência escala silenciosamente para a equipe."
    if "gestante" in problemas:
        return "Recusa atendimento de gestante ou escala silenciosamente se houver dúvida clínica."
    if "menor_16" in problemas:
        return "Recusa atendimento por idade mínima de 16 anos, sem discutir exceções."
    if "emocional_clinico" in problemas:
        return "Acolhe brevemente, não dá orientação clínica e escala quando necessário."
    if "manipulacao_negociacao" in problemas:
        return "Mantém regra de pagamento/sinal/agenda sem conceder exceção fora dos YAMLs."
    if "negocio_incomum" in problemas:
        return "Responde administrativo curto ou redireciona sem inventar serviço."
    return "Segue fluxo normal v2 conforme estado e YAML."


def analisar(conversas: list[dict[str, Any]], top: int) -> tuple[dict[str, Any], list[ConversaCritica]]:
    tipos = Counter()
    problemas_counter = Counter()
    tons = Counter()
    resultados = Counter()
    criticas: list[ConversaCritica] = []

    for conv in conversas:
        paciente = _paciente_msgs(conv)
        ana = _ana_msgs(conv)
        texto_norm = _norm(" ".join(paciente))
        tipo = classificar_tipo(texto_norm)
        problemas = identificar_problemas(paciente)
        tipos[tipo] += 1
        problemas_counter.update(problemas)
        if "agressao_ameaca" in problemas:
            tons["agressivo"] += 1
        elif "emocional_clinico" in problemas:
            tons["emocional"] += 1
        elif len(paciente) >= 8:
            tons["confuso_longo"] += 1
        else:
            tons["neutro"] += 1
        if any("confirmad" in _norm(m) or "agendad" in _norm(m) for m in ana):
            resultados["converteu_ou_confirmou"] += 1
        elif any("cancel" in _norm(m) for m in paciente + ana):
            resultados["cancelou_ou_tentou_cancelar"] += 1
        else:
            resultados["sem_resultado_claro"] += 1

        score = len(paciente) + 8 * sum(p != "complexidade_baixa" for p in problemas)
        if score >= 10:
            conv_id = str((conv.get("chat") or {}).get("id") or conv.get("remoteJid") or "sem_id")
            criticas.append(
                ConversaCritica(
                    conversa_id=conv_id,
                    tipo=tipo,
                    score_complexidade=score,
                    problemas=problemas,
                    mensagens_paciente=len(paciente),
                    mensagens_total=len(conv.get("messages") or []),
                    exemplo_paciente=(paciente[0] if paciente else "")[:240],
                    resposta_ana_referencia=(ana[-1] if ana else "")[:240],
                    resposta_v2_esperada=resposta_v2_esperada(problemas),
                )
            )

    criticas.sort(key=lambda c: c.score_complexidade, reverse=True)
    stats = {
        "total_conversas": len(conversas),
        "total_mensagens": sum(len(c.get("messages") or []) for c in conversas),
        "tipos": dict(tipos),
        "problemas": dict(problemas_counter),
        "tons": dict(tons),
        "resultados": dict(resultados),
    }
    return stats, criticas[:top]


def escrever_markdown(path: Path, stats: dict[str, Any], criticas: list[ConversaCritica]) -> None:
    linhas = [
        "# Conversas Problemáticas",
        "",
        "## Estatísticas",
        f"- Total de conversas: {stats['total_conversas']}",
        f"- Total de mensagens: {stats['total_mensagens']}",
        f"- Tipos: {stats['tipos']}",
        f"- Problemas: {stats['problemas']}",
        f"- Tons: {stats['tons']}",
        f"- Resultados: {stats['resultados']}",
        "",
        "## Como o agente lida com agressão",
        "- Primeira agressão: resposta curta, profissional e sem discussão.",
        "- Segunda agressão consecutiva: escalação silenciosa para a equipe e resposta neutra ao paciente.",
        "- O paciente nunca recebe nome ou número interno do Breno.",
        "",
        "## Top Conversas Críticas",
    ]
    for idx, item in enumerate(criticas, start=1):
        linhas.extend(
            [
                "",
                f"### {idx}. {item.conversa_id}",
                f"- Tipo: {item.tipo}",
                f"- Score de complexidade: {item.score_complexidade}",
                f"- Problemas: {', '.join(item.problemas)}",
                f"- Mensagens: {item.mensagens_paciente} paciente / {item.mensagens_total} total",
                f"- Exemplo paciente: {item.exemplo_paciente}",
                f"- Ana real respondeu: {item.resposta_ana_referencia}",
                f"- V2 esperado: {item.resposta_v2_esperada}",
            ]
        )
    path.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/conversas_export.json"))
    parser.add_argument("--output-md", type=Path, default=Path("CONVERSAS_PROBLEMATICAS.md"))
    parser.add_argument("--output-json", type=Path, default=Path("conversas_problematicas.json"))
    parser.add_argument("--top", type=int, default=50)
    args = parser.parse_args()

    input_path = args.input
    if not input_path.exists() and Path("conversas_export.json").exists():
        input_path = Path("conversas_export.json")
    data = json.loads(input_path.read_text(encoding="utf-8"))
    conversas = data.get("conversations") if isinstance(data, dict) else data
    stats, criticas = analisar(conversas or [], args.top)
    escrever_markdown(args.output_md, stats, criticas)
    args.output_json.write_text(
        json.dumps({"stats": stats, "criticas": [asdict(c) for c in criticas]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"Relatório: {args.output_md}")


if __name__ == "__main__":
    main()

