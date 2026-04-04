# scripts/mine_conversations.py
import json
import logging
import os
import time
from pathlib import Path

import anthropic
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
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def get_results(self) -> list[dict]:
        return list(self._data.values())


def main():
    required_vars = ["EVOLUTION_API_URL", "EVOLUTION_API_KEY", "ANTHROPIC_API_KEY"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Variáveis de ambiente ausentes: {', '.join(missing)}. Verifique scripts/.env")
        raise SystemExit(1)

    base_dir = Path(__file__).parent.parent
    checkpoint_path = Path(__file__).parent / "mining_progress.json"
    output_dir = base_dir / "knowledge_base"

    evolution = EvolutionClient(
        base_url=os.environ["EVOLUTION_API_URL"],
        api_key=os.environ["EVOLUTION_API_KEY"],
        instance=os.environ.get("EVOLUTION_INSTANCE", "thay"),
    )
    pseudonymizer = Pseudonymizer()

    class _HaikuAdapter:
        """Adapta o cliente Anthropic à interface esperada pelo ConversationAnalyzer."""
        def __init__(self, client):
            self._client = client

        def generate_content(self, prompt: str):
            msg = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            class _Resp:
                text = msg.content[0].text
            return _Resp()

    haiku_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    analyzer = ConversationAnalyzer(model=_HaikuAdapter(haiku_client))

    checkpoint = CheckpointManager(checkpoint_path)

    logger.info("Buscando chats da Evolution API...")
    chats = evolution.fetch_chats(limit=800)
    logger.info(f"Total de chats para processar: {len(chats)}")

    already_done = sum(1 for c in chats if checkpoint.is_done(c["id"]))
    logger.info(f"Já processados (checkpoint): {already_done}")

    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5

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
                consecutive_errors = 0  # reset on success
                continue

            pseudonymized = pseudonymizer.pseudonymize(chat["remoteJid"], messages)
            result = analyzer.analyze(pseudonymized)
            checkpoint.mark_done(chat["id"], result)

            # Rate limit Anthropic API: ~50 req/min → 1.2s entre requests
            consecutive_errors = 0  # reset on success
            time.sleep(1.2)

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                # Rate limit — aguarda e continua sem contar como erro consecutivo
                import re
                wait = 60
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", err_str, re.IGNORECASE)
                if m:
                    wait = int(float(m.group(1))) + 5
                logger.warning(f"Rate limit atingido. Aguardando {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"Erro no chat {chat['id']}: {e}")
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(f"Abortando: {MAX_CONSECUTIVE_ERRORS} erros consecutivos. Verifique credenciais.")
                    raise SystemExit(1)
                time.sleep(2)

    logger.info("Consolidando knowledge base...")
    results = [r for r in checkpoint.get_results() if not r.get("_skipped")]
    consolidator = Consolidator(output_dir=output_dir)
    consolidator.consolidate(results)

    logger.info(f"Knowledge base gerada em: {output_dir}")
    logger.info(f"Total de conversas analisadas: {len(results)}")


if __name__ == "__main__":
    main()
