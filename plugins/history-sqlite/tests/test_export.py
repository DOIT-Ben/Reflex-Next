from __future__ import annotations

import base64
import csv
import io
import json

import pytest

import reflex_history_sqlite.export as export_module
from reflex_history_sqlite.contract import HistoryPluginError
from reflex_history_sqlite.repository import HistoryRepository


EXPORT_FIELDS = (
    "id",
    "created_at",
    "input",
    "output",
    "mode",
    "style",
    "scene",
    "provider",
    "model",
    "elapsed_ms",
    "status",
    "rating",
    "tags",
)


def _track_connections(monkeypatch):
    counts = {"opened": 0, "closed": 0, "active": 0}
    original_open = HistoryRepository._open_connection

    class CountedConnection:
        def __init__(self, connection):
            self._connection = connection
            self._closed = False

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def close(self):
            if self._closed:
                return
            self._closed = True
            try:
                self._connection.close()
            finally:
                counts["closed"] += 1
                counts["active"] -= 1

    def counted_open(repository, *, read_only):
        connection = original_open(repository, read_only=read_only)
        counts["opened"] += 1
        counts["active"] += 1
        return CountedConnection(connection)

    monkeypatch.setattr(HistoryRepository, "_open_connection", counted_open)
    return counts


def _save(history_plugin, history_services, cancellation, snapshot):
    return history_plugin.invoke(
        "save", snapshot, history_services, cancellation
    )


def _export_bytes(history_plugin, history_services, cancellation, format_name):
    events = list(
        history_plugin.invoke(
            "export",
            {"format": format_name, "filters": {}},
            history_services,
            cancellation,
        )
    )
    assert events[-1] == {
        "status": "result",
        "data": {"record_count": 1, "format": format_name},
    }
    assert all(set(event) == {"status", "data"} for event in events)
    return b"".join(
        base64.b64decode(event["data"]["bytes"])
        for event in events
        if event["status"] == "chunk"
    )


def test_export_json_csv_and_markdown_are_utf8_safe_and_deterministic(
    history_plugin, history_services, cancellation, make_snapshot
):
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(
            input="中文输入 Bearer fixture-export-secret",
            output="```inner```\n[remote](https://example.invalid/pixel)",
            tags=["中文"],
        ),
    )

    json_bytes = _export_bytes(
        history_plugin, history_services, cancellation, "json"
    )
    records = json.loads(json_bytes.decode("utf-8"))
    assert tuple(records[0]) == EXPORT_FIELDS
    assert records[0]["input"] == "中文输入 Bearer [REDACTED]"
    assert "fixture-export-secret" not in json_bytes.decode("utf-8")

    csv_bytes = _export_bytes(
        history_plugin, history_services, cancellation, "csv"
    )
    rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
    assert tuple(rows[0]) == EXPORT_FIELDS
    assert rows[1][0] == "history-001"

    markdown = _export_bytes(
        history_plugin, history_services, cancellation, "markdown"
    ).decode("utf-8")
    assert "fixture-export-secret" not in markdown
    assert "````text\n```inner```" in markdown
    assert "<script" not in markdown.casefold()
    assert "![](" not in markdown


@pytest.mark.parametrize("formula", ["=1+1", "+SUM(A1:A2)", "-2+3", "@cmd"])
def test_csv_export_escapes_formula_injection_in_every_text_field(
    history_plugin, history_services, cancellation, make_snapshot, formula
):
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(input=formula, output=formula, tags=[formula]),
    )

    rows = list(
        csv.reader(
            io.StringIO(
                _export_bytes(
                    history_plugin, history_services, cancellation, "csv"
                ).decode("utf-8")
            )
        )
    )

    assert rows[1][2].lstrip().startswith("'")
    assert rows[1][3].lstrip().startswith("'")
    assert "'" in rows[1][12]


@pytest.mark.parametrize(
    "payload",
    [
        {"format": "json", "filters": {}, "path": "D:/forbidden.json"},
        {"format": "json", "filters": {}, "handle": 1},
        {"format": "json", "filters": {}, "confirmed": True},
        {"format": "json", "filters": {}, "admin": True},
        {"format": "html", "filters": {}},
    ],
)
def test_export_rejects_host_private_fields_and_unsupported_formats(
    history_plugin, history_services, cancellation, payload
):
    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        history_plugin.invoke("export", payload, history_services, cancellation)


def test_export_cancellation_returns_no_chunks(
    history_plugin, history_services, cancellation
):
    cancellation.cancel()

    with pytest.raises(Exception) as caught:
        list(
            history_plugin.invoke(
                "export",
                {"format": "json", "filters": {}},
                history_services,
                cancellation,
            )
        )

    assert caught.value.__class__.__name__ == "OperationCancelled"


@pytest.mark.parametrize(
    ("limit_name", "limit_value"),
    [
        ("MAX_EXPORT_RECORDS", 1),
        ("MAX_EXPORT_BYTES", 128),
    ],
)
def test_export_enforces_bounded_record_and_byte_limits(
    history_plugin,
    history_services,
    cancellation,
    make_snapshot,
    monkeypatch,
    limit_name,
    limit_value,
):
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(id="history-limit-1", input="x" * 96, output="y" * 96),
    )
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(id="history-limit-2", input="x" * 96, output="y" * 96),
    )
    monkeypatch.setattr(export_module, limit_name, limit_value)
    connections = _track_connections(monkeypatch)

    with pytest.raises(HistoryPluginError, match="history_export_too_large"):
        list(
            history_plugin.invoke(
                "export",
                {"format": "json", "filters": {}},
                history_services,
                cancellation,
            )
        )

    assert connections["opened"] == connections["closed"]
    assert connections["active"] == 0


def test_export_checks_cancellation_between_streamed_chunks(
    history_plugin,
    history_services,
    cancellation,
    make_snapshot,
    monkeypatch,
):
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(input="x" * 256, output="y" * 256),
    )
    monkeypatch.setattr(export_module, "CHUNK_SIZE", 64)
    connections = _track_connections(monkeypatch)
    events = history_plugin.invoke(
        "export",
        {"format": "json", "filters": {}},
        history_services,
        cancellation,
    )

    assert next(events)["status"] == "chunk"
    assert connections["active"] == 0
    cancellation.cancel()
    with pytest.raises(Exception) as caught:
        next(events)
    assert caught.value.__class__.__name__ == "OperationCancelled"
    assert connections["opened"] == connections["closed"]
    assert connections["active"] == 0


def test_repeated_exports_close_every_opened_connection(
    history_plugin,
    history_services,
    cancellation,
    make_snapshot,
    monkeypatch,
):
    _save(
        history_plugin,
        history_services,
        cancellation,
        make_snapshot(),
    )
    connections = _track_connections(monkeypatch)

    for format_name in ("json", "csv", "markdown") * 3:
        assert _export_bytes(
            history_plugin, history_services, cancellation, format_name
        )

    assert connections["opened"] >= 9
    assert connections["opened"] == connections["closed"]
    assert connections["active"] == 0
