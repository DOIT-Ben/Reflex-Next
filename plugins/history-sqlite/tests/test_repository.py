from __future__ import annotations

import json
import sqlite3
import threading

import pytest
from cryptography.exceptions import InvalidTag

from reflex_core import OperationCancelled
from reflex_history_sqlite.codec import HistoryCodec
from reflex_history_sqlite.contract import HistoryPluginError
from reflex_history_sqlite.repository import HistoryRepository


def save(history_plugin, snapshot, services, cancellation):
    return history_plugin.invoke("save", snapshot, services, cancellation)


def list_records(history_plugin, services, cancellation, **payload):
    request = {"page_size": 50, "sort": "created_at", "direction": "desc"}
    request.update(payload)
    return history_plugin.invoke("list", request, services, cancellation)


def test_no_key_or_disabled_new_store_does_not_create_directory_or_database(
    history_plugin,
    history_services,
    clone_services,
    make_snapshot,
    cancellation,
):
    database_path = history_services["history"]["database_path"]
    without_key = clone_services(history_services, keys={})
    disabled = clone_services(history_services, history_enabled=False)

    with pytest.raises(HistoryPluginError, match="history_key_unavailable"):
        save(history_plugin, make_snapshot(), without_key, cancellation)
    with pytest.raises(HistoryPluginError, match="history_read_only"):
        save(history_plugin, make_snapshot(), disabled, cancellation)

    assert not database_path.parent.exists()


def test_schema_v1_pragmas_tables_and_indexes_are_created_on_first_save(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(), history_services, cancellation)
    database_path = history_services["history"]["database_path"]

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        index_sql = [
            row[0]
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        ]
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        connection.close()

    assert {
        "history_records",
        "schema_meta",
        "repair_quarantine",
        "rotation_checkpoint",
    }.issubset(tables)
    assert len(index_sql) == 6
    assert all(
        any(column in sql for column in ("created_at", "provider", "scene", "style", "rating", "status"))
        for sql in index_sql
    )
    assert not any("input" in sql or "output" in sql or "fts" in sql.casefold() for sql in index_sql)


def test_legacy_schema_uses_online_backup_before_migration(
    history_plugin, history_services, make_snapshot, cancellation
):
    database_path = history_services["history"]["database_path"]
    database_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_marker(value) VALUES (?)", ("preserved",))
        connection.commit()
    finally:
        connection.close()

    save(history_plugin, make_snapshot(), history_services, cancellation)

    backup_path = database_path.with_name(f"{database_path.name}.migration-v0.bak")
    backup = sqlite3.connect(backup_path)
    try:
        assert backup.execute("SELECT value FROM legacy_marker").fetchone()[0] == "preserved"
        assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        backup.close()
    migrated = sqlite3.connect(database_path)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        migrated.close()


def test_migration_backup_failure_enters_sticky_read_only_recovery_mode(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    monkeypatch,
):
    database_path = history_services["history"]["database_path"]
    database_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        connection.commit()
    finally:
        connection.close()

    original = HistoryRepository._migration_backup
    calls = 0

    def fail_once(repository, connection, version):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HistoryPluginError("history_recovery_required")
        return original(repository, connection, version)

    monkeypatch.setattr(HistoryRepository, "_migration_backup", fail_once)

    for _ in range(2):
        with pytest.raises(HistoryPluginError, match="history_recovery_required") as caught:
            save(history_plugin, make_snapshot(), history_services, cancellation)
        assert str(database_path) not in str(caught.value)
    assert calls == 1
    assert not database_path.with_name(
        f"{database_path.name}.migration-v0.bak"
    ).exists()


def test_save_redacts_before_encryption_and_database_contains_no_plaintext_or_secret(
    history_plugin, history_services, make_snapshot, cancellation
):
    hidden_one = "history-fixture-bearer"
    hidden_two = "history-fixture-api-secret"
    original_input = f"Authorization: Bearer {hidden_one} explain this"
    original_output = f"api_key={hidden_two} finished"

    result = save(
        history_plugin,
        make_snapshot(input=original_input, output=original_output),
        history_services,
        cancellation,
    )
    raw_database = history_services["history"]["database_path"].read_bytes()
    detail = history_plugin.invoke(
        "detail", {"id": result["id"]}, history_services, cancellation
    )["record"]

    assert original_input.encode() not in raw_database
    assert original_output.encode() not in raw_database
    assert hidden_one.encode() not in raw_database
    assert hidden_two.encode() not in raw_database
    assert hidden_one not in detail["input"]
    assert hidden_two not in detail["output"]
    assert "[REDACTED]" in detail["input"]
    assert "[REDACTED]" in detail["output"]


def test_parameterized_save_preserves_table_when_text_contains_sql(
    history_plugin, history_services, make_snapshot, cancellation
):
    hostile = "x'); DROP TABLE history_records; --"

    save(
        history_plugin,
        make_snapshot(input=hostile, output=hostile),
        history_services,
        cancellation,
    )

    assert list_records(history_plugin, history_services, cancellation)["items"][0][
        "id"
    ] == "history-001"
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, cancellation
    )["record"]["input"] == hostile


def test_list_returns_summary_without_decrypting_body(
    history_plugin, history_services, make_snapshot, cancellation, monkeypatch
):
    save(history_plugin, make_snapshot(), history_services, cancellation)

    monkeypatch.setattr(
        HistoryCodec,
        "decrypt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("body decrypted")),
    )
    item = list_records(history_plugin, history_services, cancellation)["items"][0]

    assert set(item) == {
        "id",
        "created_at",
        "mode",
        "style",
        "scene",
        "provider",
        "model",
        "elapsed_ms",
        "status",
        "rating",
        "tags",
    }


def test_detail_decrypts_both_fields_and_bad_ciphertext_returns_fixed_placeholder(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(), history_services, cancellation)
    valid = history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, cancellation
    )["record"]
    assert valid["input"] == "Original prompt"
    assert valid["output"] == "Optimized result"

    database_path = history_services["history"]["database_path"]
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "UPDATE history_records SET input_ciphertext = ? WHERE id = ?",
            (sqlite3.Binary(b"tampered"), "history-001"),
        )
        connection.commit()
    finally:
        connection.close()

    broken = history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, cancellation
    )["record"]
    assert broken["input"] == "[CORRUPTED]"
    assert broken["output"] == "[CORRUPTED]"
    assert broken["status"] == "corrupted"
    assert broken["corrupted"] is True
    assert "tampered" not in json.dumps(broken)


def test_existing_database_remains_readable_when_history_is_disabled(
    history_plugin,
    history_services,
    clone_services,
    make_snapshot,
    cancellation,
):
    save(history_plugin, make_snapshot(), history_services, cancellation)
    read_only = clone_services(history_services, history_enabled=False)

    assert list_records(history_plugin, read_only, cancellation)["items"][0]["id"] == "history-001"
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, read_only, cancellation
    )["record"]["output"] == "Optimized result"


def test_rate_accepts_one_to_five_or_null_and_missing_record_fails(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(), history_services, cancellation)

    for rating in (1, 5, None):
        result = history_plugin.invoke(
            "rate",
            {"id": "history-001", "rating": rating},
            history_services,
            cancellation,
        )
        assert result == {"id": "history-001", "rating": rating}

    with pytest.raises(HistoryPluginError, match="history_not_found"):
        history_plugin.invoke(
            "rate",
            {"id": "missing", "rating": 3},
            history_services,
            cancellation,
        )


def test_stable_authenticated_cursor_has_bounded_page_size(
    history_plugin, history_services, make_snapshot, cancellation
):
    for index in range(5):
        save(
            history_plugin,
            make_snapshot(id=f"history-{index:03d}", elapsed_ms=index),
            history_services,
            cancellation,
        )

    first = list_records(
        history_plugin, history_services, cancellation, page_size=2
    )
    second = list_records(
        history_plugin,
        history_services,
        cancellation,
        page_size=2,
        cursor=first["next_cursor"],
    )
    assert [item["id"] for item in first["items"]] == ["history-004", "history-003"]
    assert [item["id"] for item in second["items"]] == ["history-002", "history-001"]
    assert set(item["id"] for item in first["items"]).isdisjoint(
        item["id"] for item in second["items"]
    )

    tampered = first["next_cursor"][:-1] + (
        "A" if first["next_cursor"][-1] != "A" else "B"
    )
    with pytest.raises(HistoryPluginError, match="history_cursor_invalid"):
        list_records(
            history_plugin,
            history_services,
            cancellation,
            page_size=2,
            cursor=tampered,
        )

    with pytest.raises(HistoryPluginError, match="history_payload_invalid"):
        list_records(history_plugin, history_services, cancellation, page_size=101)


def test_rating_cursor_is_stable_for_ties_and_null_values(
    history_plugin, history_services, make_snapshot, cancellation
):
    for record_id in ("history-a", "history-b", "history-c", "history-d"):
        save(
            history_plugin,
            make_snapshot(id=record_id),
            history_services,
            cancellation,
        )
    for record_id, rating in (("history-a", 1), ("history-b", 1), ("history-c", 2)):
        history_plugin.invoke(
            "rate",
            {"id": record_id, "rating": rating},
            history_services,
            cancellation,
        )

    first = list_records(
        history_plugin,
        history_services,
        cancellation,
        page_size=2,
        sort="rating",
        direction="asc",
    )
    second = list_records(
        history_plugin,
        history_services,
        cancellation,
        page_size=2,
        sort="rating",
        direction="asc",
        cursor=first["next_cursor"],
    )

    assert [item["id"] for item in first["items"]] == ["history-a", "history-b"]
    assert [item["id"] for item in second["items"]] == ["history-c", "history-d"]


def test_filters_sort_and_encrypted_unicode_keyword_search(
    history_plugin, history_services, make_snapshot, cancellation
):
    records = [
        make_snapshot(
            id="history-a",
            created_at="2026-07-10T10:00:00.000Z",
            provider="minimax",
            scene="coding",
            style="concise",
            input="Die Straße ist lang",
            elapsed_ms=10,
        ),
        make_snapshot(
            id="history-b",
            created_at="2026-07-11T10:00:00.000Z",
            provider="other",
            scene="writing",
            style="balanced",
            output="A STRASSE result",
            elapsed_ms=20,
        ),
        make_snapshot(
            id="history-c",
            created_at="2026-07-12T10:00:00.000Z",
            provider="minimax",
            scene="coding",
            style="concise",
            input="unrelated",
            elapsed_ms=30,
        ),
    ]
    for record in records:
        save(history_plugin, record, history_services, cancellation)
    history_plugin.invoke(
        "rate", {"id": "history-a", "rating": 4}, history_services, cancellation
    )
    history_plugin.invoke(
        "rate", {"id": "history-c", "rating": 2}, history_services, cancellation
    )

    filtered = list_records(
        history_plugin,
        history_services,
        cancellation,
        filters={
            "provider": "minimax",
            "scene": "coding",
            "style": "concise",
            "date_from": "2026-07-10T00:00:00.000Z",
            "date_to": "2026-07-11T23:59:59.999Z",
            "rating": 4,
        },
        sort="rating",
        direction="asc",
    )
    searched = list_records(
        history_plugin,
        history_services,
        cancellation,
        keyword="STRASSE",
        page_size=10,
    )

    assert [item["id"] for item in filtered["items"]] == ["history-a"]
    assert [item["id"] for item in searched["items"]] == ["history-b", "history-a"]


def test_keyword_search_never_creates_fts_or_plaintext_temp_storage(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(
        history_plugin,
        make_snapshot(input="Needle body", output="other"),
        history_services,
        cancellation,
    )
    list_records(
        history_plugin,
        history_services,
        cancellation,
        keyword="needle",
    )

    connection = sqlite3.connect(history_services["history"]["database_path"])
    try:
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master")]
        temp_names = [
            row[0] for row in connection.execute("SELECT name FROM sqlite_temp_master")
        ]
    finally:
        connection.close()
    assert not any("fts" in name.casefold() for name in names)
    assert temp_names == []


def test_delete_and_clear_require_existing_records(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(id="history-a"), history_services, cancellation)
    save(history_plugin, make_snapshot(id="history-b"), history_services, cancellation)

    assert history_plugin.invoke(
        "delete", {"id": "history-a"}, history_services, cancellation
    ) == {"deleted": 1}
    assert history_plugin.invoke(
        "clear", {}, history_services, cancellation
    ) == {"deleted": 1}

    with pytest.raises(HistoryPluginError, match="history_not_found"):
        history_plugin.invoke(
            "delete", {"id": "history-a"}, history_services, cancellation
        )
    with pytest.raises(HistoryPluginError, match="history_not_found"):
        history_plugin.invoke("clear", {}, history_services, cancellation)


def test_pre_cancelled_operation_stops_before_database_creation(
    history_plugin, history_services, make_snapshot, cancellation
):
    cancellation.cancel()

    with pytest.raises(OperationCancelled):
        save(history_plugin, make_snapshot(), history_services, cancellation)

    assert not history_services["history"]["database_path"].parent.exists()


def test_cancelled_save_waiting_for_write_lock_rolls_back_without_new_record(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(id="seed"), history_services, cancellation)
    database_path = history_services["history"]["database_path"]
    blocker = sqlite3.connect(database_path)
    blocker.execute("BEGIN IMMEDIATE")
    token = type(cancellation)()
    errors = []

    def worker():
        try:
            save(
                history_plugin,
                make_snapshot(id="cancelled-save"),
                history_services,
                token,
            )
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    threading.Event().wait(0.1)
    assert thread.is_alive()
    token.cancel()
    blocker.rollback()
    blocker.close()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], OperationCancelled)
    connection = sqlite3.connect(database_path)
    try:
        ids = [row[0] for row in connection.execute("SELECT id FROM history_records")]
    finally:
        connection.close()
    assert ids == ["seed"]


def test_cancelled_delete_waiting_for_write_lock_preserves_record(
    history_plugin, history_services, make_snapshot, cancellation
):
    save(history_plugin, make_snapshot(id="keep-me"), history_services, cancellation)
    database_path = history_services["history"]["database_path"]
    blocker = sqlite3.connect(database_path)
    blocker.execute("BEGIN IMMEDIATE")
    token = type(cancellation)()
    errors = []

    def worker():
        try:
            history_plugin.invoke(
                "delete", {"id": "keep-me"}, history_services, token
            )
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=worker)
    thread.start()
    threading.Event().wait(0.1)
    assert thread.is_alive()
    token.cancel()
    blocker.rollback()
    blocker.close()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], OperationCancelled)
    connection = sqlite3.connect(database_path)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM history_records WHERE id = ?", ("keep-me",)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1


@pytest.mark.parametrize(
    ("operation", "payload", "expected"),
    [
        ("rate", {"id": "locked-record", "rating": 4}, {"id": "locked-record", "rating": 4}),
        ("delete", {"id": "locked-record"}, {"deleted": 1}),
    ],
)
def test_transient_write_lock_returns_busy_without_entering_sticky_recovery(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    monkeypatch,
    operation,
    payload,
    expected,
):
    save(
        history_plugin,
        make_snapshot(id="locked-record"),
        history_services,
        cancellation,
    )
    database_path = history_services["history"]["database_path"]
    original_open = HistoryRepository._open_connection

    def open_with_short_busy_timeout(repository, *, read_only):
        connection = original_open(repository, read_only=read_only)
        if not read_only:
            connection.execute("PRAGMA busy_timeout = 50")
        return connection

    monkeypatch.setattr(
        HistoryRepository, "_open_connection", open_with_short_busy_timeout
    )
    blocker = sqlite3.connect(database_path)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(HistoryPluginError) as caught:
            history_plugin.invoke(
                operation, payload, history_services, cancellation
            )
    finally:
        blocker.rollback()
        blocker.close()

    assert caught.value.code == "history_storage_busy"
    assert str(caught.value) == "history_storage_busy"
    assert history_plugin.invoke(
        operation, payload, history_services, cancellation
    ) == expected


def test_storage_errors_expose_only_a_fixed_safe_code(
    history_plugin, history_services, cancellation
):
    database_path = history_services["history"]["database_path"]
    database_path.parent.mkdir(parents=True)
    database_path.write_bytes(b"not a sqlite database")
    private_values = (
        str(database_path),
        history_services["history"]["keys"]["v1"],
        "not a sqlite database",
    )

    with pytest.raises(HistoryPluginError) as caught:
        history_plugin.invoke(
            "list",
            {"page_size": 10, "sort": "created_at", "direction": "desc"},
            history_services,
            cancellation,
        )

    assert caught.value.code == "history_storage_failed"
    rendered = f"{caught.value!s} {caught.value!r}"
    assert all(value not in rendered for value in private_values)


def test_damaged_database_closes_handles_and_enters_sticky_recovery(
    history_plugin, history_services, make_snapshot, cancellation, monkeypatch
):
    database_path = history_services["history"]["database_path"]
    database_path.parent.mkdir(parents=True)
    database_path.write_bytes(b"damaged sqlite")
    original_open = HistoryRepository._open_connection
    open_calls = 0

    def counted_open(repository, *, read_only):
        nonlocal open_calls
        open_calls += 1
        return original_open(repository, read_only=read_only)

    monkeypatch.setattr(HistoryRepository, "_open_connection", counted_open)

    with pytest.raises(HistoryPluginError, match="history_storage_failed"):
        history_plugin.invoke(
            "list",
            {"page_size": 10, "sort": "created_at", "direction": "desc"},
            history_services,
            cancellation,
        )
    assert open_calls == 1

    moved_path = database_path.with_name("damaged.sqlite3")
    database_path.rename(moved_path)
    moved_path.unlink()
    database_path.write_bytes(b"damaged sqlite")

    with pytest.raises(HistoryPluginError, match="history_recovery_required"):
        save(history_plugin, make_snapshot(id="blocked"), history_services, cancellation)
    assert open_calls == 1


def test_plugin_uses_per_call_connections_safely_across_threads(
    history_plugin, history_services, make_snapshot
):
    errors = []

    def worker(index):
        from reflex_core import CancellationToken

        try:
            save(
                history_plugin,
                make_snapshot(id=f"thread-{index}"),
                history_services,
                CancellationToken(),
            )
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert all(not thread.is_alive() for thread in threads)
    from reflex_core import CancellationToken

    assert len(
        list_records(history_plugin, history_services, CancellationToken())["items"]
    ) == 4
