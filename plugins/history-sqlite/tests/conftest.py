from __future__ import annotations

from copy import deepcopy

import pytest

from reflex_core import CancellationToken
from reflex_history_sqlite import plugin


@pytest.fixture
def history_plugin():
    return plugin()


@pytest.fixture
def cancellation():
    return CancellationToken()


@pytest.fixture
def history_services(tmp_path):
    return {
        "history": {
            "database_path": tmp_path / "private" / "history.sqlite3",
            "keys": {"v1": "11" * 32},
            "history_enabled": True,
            "privacy_mode": False,
            "history_redaction": "secrets",
        }
    }


@pytest.fixture
def make_snapshot():
    def factory(**changes):
        snapshot = {
            "id": "history-001",
            "created_at": "2026-07-11T10:00:00.000Z",
            "input": "Original prompt",
            "output": "Optimized result",
            "mode": "content",
            "style": "concise",
            "scene": "coding",
            "provider": "minimax",
            "model": "MiniMax-M2.1",
            "elapsed_ms": 123,
            "status": "completed",
            "tags": ["work"],
        }
        snapshot.update(changes)
        return snapshot

    return factory


@pytest.fixture
def clone_services():
    def clone(services, **changes):
        copied = deepcopy(services)
        copied["history"].update(changes)
        return copied

    return clone
