# scripts/mine_conversations.py
import json
import logging
import os
import time
from pathlib import Path

import google.generativeai as genai
from dotenv import load_dotenv

from scripts.evolution_client import EvolutionClient
from scripts.pseudonymizer import Pseudonymizer
from scripts.analyzer import ConversationAnalyzer
from scripts.consolidator import Consolidator

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, path: Path | str):
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        if self._path.exists():
            self._data = json.loads(self._path.read_text(encoding="utf-8"))

    def is_done(self, chat_id: str) -> bool:
        return chat_id in self._data

    def mark_done(self, chat_id: str, result: dict) -> None:
        self._data[chat_id] = result
        self._path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def get_results(self) -> list[dict]:
        return list(self._data.values())


def main():
    base_dir = Path(__file__).parent.parent
    checkpoint_path = Path(__file__).parent / "mining_progress.json"
    output_dir = base_dir / "knowledge_base"

    evolution = EvolutionClient(
        base_url=os.environ["EVOLUTION_API_URL"],
        api_key=os.environ["EVOLUTION_API_KEY"],
        instance=os.environ.get("EVOLUTION_INSTANCE", "thay"),
    )
    pseudonymizer = Pseudonymizer()

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        generation_config=genai.GenerationConfig(response_mime_type="application/json"),
    )
    analyzer = ConversationAnalyzer(model=model)

    checkpoint = CheckpointManager(checkpoint_path)

    logger.info("Buscando chats da Evolution API...")
    chats = evolution.fetch_chats(limit=800)
    logger.info(f"Total de chats para processar: {len(chats)}")

    already_done = sum(1 for c in chats if checkpoint.is_done(c["id"]))
    logger.info(f"Já processados (checkpoint): {already_done}")

    for i, chat in enumerate(chats):
        if checkpoint.is_done(chat["id"]):
            continue

        logger.info(f"[{i+1}/{len(chats)}] Processando {chat['id']}...")

        try:
            messages = evolution.fetch_messages(chat["remoteJid"])
            if len(messages) < 3:
                checkpoint.mark_done(chat["id"], {"intent": "tirar_duvida", "outcome": "em_aberto",
                    "questions": [], "objections": [], "interest_score": 1,
                    "language_notes": "", "behavioral_signals": [], "_skipped": True})
                continue

            pseudonymized = pseudonymizer.pseudonymize(chat["remoteJid"], messages)
            result = analyzer.analyze(pseudonymized)
            checkpoint.mark_done(chat["id"], result)

            # Rate limit gentil para a API do Gemini
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Erro no chat {chat['id']}: {e}")
            time.sleep(2)  # Espera maior em caso de erro

    logger.info("Consolidando knowledge base...")
    results = [r for r in checkpoint.get_results() if not r.get("_skipped")]
    consolidator = Consolidator(output_dir=output_dir)
    consolidator.consolidate(results)

    logger.info(f"Knowledge base gerada em: {output_dir}")
    logger.info(f"Total de conversas analisadas: {len(results)}")


if __name__ == "__main__":
    main()
