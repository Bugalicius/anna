# tests/test_mine_conversations.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from scripts.mine_conversations import CheckpointManager

def test_checkpoint_saves_and_loads(tmp_path):
    cp = CheckpointManager(tmp_path / "progress.json")
    cp.mark_done("chat_001", {"intent": "preco"})
    cp.mark_done("chat_002", {"intent": "agendar"})

    # Simula nova instância (novo run)
    cp2 = CheckpointManager(tmp_path / "progress.json")
    assert cp2.is_done("chat_001")
    assert cp2.is_done("chat_002")
    assert not cp2.is_done("chat_003")

def test_checkpoint_returns_accumulated_results(tmp_path):
    cp = CheckpointManager(tmp_path / "progress.json")
    cp.mark_done("chat_001", {"intent": "preco", "outcome": "nao_fechou"})
    cp.mark_done("chat_002", {"intent": "agendar", "outcome": "fechou"})

    cp2 = CheckpointManager(tmp_path / "progress.json")
    results = cp2.get_results()
    assert len(results) == 2
