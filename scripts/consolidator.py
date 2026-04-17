# scripts/consolidator.py
import json
from collections import Counter
from pathlib import Path


class Consolidator:
    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def consolidate(self, results: list[dict]) -> None:
        self._write_faq(results)
        self._write_objections(results)
        self._write_remarketing(results)
        self._write_tone_guide(results)
        self._write_system_prompt(results)

    def _write_faq(self, results: list[dict]) -> None:
        all_questions = [q for r in results for q in r.get("questions", [])]
        counter = Counter(all_questions)
        faq = [
            {"question": q, "frequency": count, "suggested_answer": ""}
            for q, count in counter.most_common(30)
        ]
        (self.output_dir / "faq.json").write_text(
            json.dumps(faq, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_objections(self, results: list[dict]) -> None:
        all_objections = [o for r in results for o in r.get("objections", [])]
        counter = Counter(all_objections)
        objections = [
            {"objection": o, "frequency": count, "suggested_response": ""}
            for o, count in counter.most_common(20)
        ]
        (self.output_dir / "objections.json").write_text(
            json.dumps(objections, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_remarketing(self, results: list[dict]) -> None:
        cold_leads = [
            {
                "outcome": r.get("outcome", "em_aberto"),
                "interest_score": r.get("interest_score", 0),
                "intent": r.get("intent", ""),
                "objections": r.get("objections", []),
                "behavioral_signals": r.get("behavioral_signals", []),
            }
            for r in results
            if r.get("outcome") in ["nao_fechou", "em_aberto"]
        ]
        # Agrupar por padrão de sinal comportamental
        profiles: dict[str, dict] = {}
        for lead in cold_leads:
            key = "+".join(sorted(lead["behavioral_signals"])) or "sem_sinal"
            if key not in profiles:
                profiles[key] = {"signals": lead["behavioral_signals"], "count": 0, "avg_interest": 0, "common_objections": []}
            profiles[key]["count"] += 1
            profiles[key]["avg_interest"] += lead["interest_score"]
            profiles[key]["common_objections"].extend(lead["objections"])

        for profile in profiles.values():
            if profile["count"] > 0:
                profile["avg_interest"] = round(profile["avg_interest"] / profile["count"], 1)
            counter = Counter(profile["common_objections"])
            profile["common_objections"] = [o for o, _ in counter.most_common(5)]

        (self.output_dir / "remarketing.json").write_text(
            json.dumps(list(profiles.values()), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _write_tone_guide(self, results: list[dict]) -> None:
        notes = [r.get("language_notes", "") for r in results if r.get("language_notes")]
        conversion_notes = [
            r.get("language_notes", "") for r in results
            if r.get("outcome") == "fechou" and r.get("language_notes")
        ]
        content = "# Guia de Tom e Linguagem — Agente Ana\n\n"
        content += "## Vocabulário e Expressões das Pacientes\n\n"
        for note in dict.fromkeys(notes[:50]):
            if note.strip():
                content += f"- {note}\n"
        content += "\n## Padrões em Conversas que Converteram\n\n"
        for note in dict.fromkeys(conversion_notes[:20]):
            if note.strip():
                content += f"- {note}\n"
        (self.output_dir / "tone_guide.md").write_text(content, encoding="utf-8")

    def _write_system_prompt(self, results: list[dict]) -> None:
        total = len(results)
        converted = sum(1 for r in results if r.get("outcome") == "fechou")
        rate = round(converted / total * 100, 1) if total else 0

        top_questions = Counter(
            q for r in results for q in r.get("questions", [])
        ).most_common(5)
        top_objections = Counter(
            o for r in results for o in r.get("objections", [])
        ).most_common(5)

        prompt = f"""# System Prompt — Agente Ana (Nutricionista Thaynara Teixeira)

## Identidade
Você é Ana, assistente virtual responsável pelos agendamentos da nutricionista Thaynara Teixeira.
Seu objetivo é agendar consultas com empatia, clareza e naturalidade em português brasileiro.

## Dados do Histórico Analisado
- Total de conversas analisadas: {total}
- Taxa de conversão observada: {rate}%

## Perguntas Mais Frequentes das Pacientes
{chr(10).join(f'- {q} (aparece {c}x)' for q, c in top_questions)}

## Principais Objeções Enfrentadas
{chr(10).join(f'- {o} (aparece {c}x)' for o, c in top_objections)}

## Regras de Comportamento
1. Sempre responder em português brasileiro informal e acolhedor
2. Nunca prometer resultados clínicos específicos
3. Encaminhar dúvidas médicas para a Thaynara diretamente
4. Ao detectar resistência, reconhecer a objeção antes de apresentar solução
5. Ao oferecer horários, apresentar no máximo 3 opções
6. Confirmar nome da paciente antes de avançar para pagamento

## Tom
Empático, profissional mas descontraído. Use emojis com moderação (💚 para acolhimento).
"""
        (self.output_dir / "system_prompt.md").write_text(prompt, encoding="utf-8")
