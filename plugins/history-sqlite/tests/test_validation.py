from __future__ import annotations

import pytest

from reflex_history_sqlite.contract import HistoryPluginError


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("save", {"unknown": True}),
        ("list", {"page_size": 10, "sort": "created_at", "direction": "desc", "unknown": True}),
        ("detail", {"id": "history-001", "database_path": "forbidden"}),
        ("rate", {"id": "history-001", "rating": 3, "key": "forbidden"}),
        ("delete", {"id": "history-001", "confirmed": True}),
        ("clear", {"confirmed": True}),
    ],
)
def test_operations_reject_unknown_or_private_payload_fields(
    history_plugin, history_services, cancellation, operation, payload
):
    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        history_plugin.invoke(operation, payload, history_services, cancellation)


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "polish"},
        {"style": "verbose"},
        {"status": "done"},
        {"elapsed_ms": -1},
        {"elapsed_ms": True},
        {"tags": "work"},
        {"tags": ["x" * 65]},
        {"input": "x" * 1_000_001},
        {"scene": "x" * 129},
    ],
)
def test_save_strictly_validates_enums_lengths_and_integers(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    changes,
):
    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        history_plugin.invoke(
            "save", make_snapshot(**changes), history_services, cancellation
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"page_size": 0, "sort": "created_at", "direction": "desc"},
        {"page_size": True, "sort": "created_at", "direction": "desc"},
        {"page_size": 10, "sort": "provider", "direction": "desc"},
        {"page_size": 10, "sort": "created_at", "direction": "down"},
        {"page_size": 10, "sort": "created_at", "direction": "desc", "filters": {"unknown": "x"}},
        {"page_size": 10, "sort": "created_at", "direction": "desc", "filters": {"rating": 0}},
        {"page_size": 10, "sort": "created_at", "direction": "desc", "keyword": ""},
        {"page_size": 10, "sort": "created_at", "direction": "desc", "cursor": 1},
    ],
)
def test_list_strictly_validates_filters_sort_cursor_and_page_size(
    history_plugin, history_services, cancellation, payload
):
    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        history_plugin.invoke("list", payload, history_services, cancellation)


@pytest.mark.parametrize("rating", [0, 6, True, "5"])
def test_rate_rejects_values_outside_one_to_five_or_null(
    history_plugin, history_services, cancellation, rating
):
    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        history_plugin.invoke(
            "rate",
            {"id": "history-001", "rating": rating},
            history_services,
            cancellation,
        )


@pytest.mark.parametrize("operation", ["get", "search", "append", "missing"])
def test_unknown_and_legacy_operations_are_rejected_safely(
    history_plugin, history_services, cancellation, operation
):
    with pytest.raises(HistoryPluginError, match="history_operation_unavailable"):
        history_plugin.invoke(operation, {}, history_services, cancellation)


@pytest.mark.parametrize("operation", ["export", "scan", "repair", "backups", "restore", "rotate"])
def test_d5_operations_do_not_pretend_success(
    history_plugin, history_services, cancellation, operation
):
    with pytest.raises(HistoryPluginError, match="history_operation_unavailable"):
        history_plugin.invoke(operation, {}, history_services, cancellation)
