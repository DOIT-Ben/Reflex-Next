from __future__ import annotations

import pytest

from reflex_core import OperationCancelled
from reflex_history_sqlite.codec import HistoryCodec
from reflex_history_sqlite.contract import HistoryPluginError
from reflex_history_sqlite import repository as repository_module


def _save(history_plugin, snapshot, services, cancellation):
    return history_plugin.invoke("save", snapshot, services, cancellation)


def _search(history_plugin, services, cancellation, keyword="needle"):
    return history_plugin.invoke(
        "list",
        {
            "page_size": 50,
            "sort": "created_at",
            "direction": "desc",
            "keyword": keyword,
        },
        services,
        cancellation,
    )


def test_keyword_search_has_a_five_second_hard_deadline(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    monkeypatch,
):
    _save(
        history_plugin,
        make_snapshot(input="needle", output="result"),
        history_services,
        cancellation,
    )
    clock = iter((0.0, 0.0, 0.0, 0.0, 5.0))
    monkeypatch.setattr(repository_module, "monotonic", lambda: next(clock))

    with pytest.raises(HistoryPluginError, match="^history_search_timeout$"):
        _search(history_plugin, history_services, cancellation)


def test_keyword_search_checks_cancellation_between_decryptions(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    monkeypatch,
):
    _save(
        history_plugin,
        make_snapshot(input="needle", output="result"),
        history_services,
        cancellation,
    )
    original_decrypt = HistoryCodec.decrypt
    decrypt_calls = 0

    def cancel_after_first_decrypt(codec, *args, **kwargs):
        nonlocal decrypt_calls
        value = original_decrypt(codec, *args, **kwargs)
        decrypt_calls += 1
        cancellation.cancel()
        return value

    monkeypatch.setattr(HistoryCodec, "decrypt", cancel_after_first_decrypt)

    with pytest.raises(OperationCancelled):
        _search(history_plugin, history_services, cancellation)

    assert decrypt_calls == 1
