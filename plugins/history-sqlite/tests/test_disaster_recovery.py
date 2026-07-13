from __future__ import annotations

import json
import os
import sqlite3
import threading

import pytest

from reflex_core import CancellationToken
from reflex_history_sqlite import plugin
from reflex_history_sqlite.contract import HistoryPluginError, HistoryServiceSnapshot
from reflex_history_sqlite.repository import INDEX_DEFINITIONS, HistoryRepository


def _save(history_plugin, services, snapshot):
    return history_plugin.invoke("save", snapshot, services, CancellationToken())


def _database_path(services):
    return services["history"]["database_path"]


def _backup_path(services, backup_id):
    return _database_path(services).parent / "backups" / f"{backup_id}.sqlite3"


def _assert_database_consistent(path, *, record_ids):
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert [
            row[0]
            for row in connection.execute(
                "SELECT id FROM history_records ORDER BY id"
            )
        ] == sorted(record_ids)
        indexes = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'history_records' "
                "AND sql IS NOT NULL"
            )
        )
        assert indexes == dict(INDEX_DEFINITIONS)
        query_plan = " ".join(
            str(column)
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM history_records WHERE provider = ?",
                ("minimax",),
            )
            for column in row
        )
        assert "history_records_provider_idx" in query_plan
    finally:
        connection.close()


def _assert_no_sensitive_maintenance_text(services, *values):
    database_path = _database_path(services)
    for path in database_path.parent.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".tmp"}:
            continue
        rendered = path.read_text(encoding="utf-8", errors="replace")
        assert all(value not in rendered for value in values)


def test_truncated_live_database_restores_from_last_verified_backup(
    history_plugin, history_services, make_snapshot
):
    plaintext = "private history body"
    _save(
        history_plugin,
        history_services,
        make_snapshot(input=plaintext, output="last valid output"),
    )
    backup = history_plugin.invoke(
        "repair", {}, history_services, CancellationToken()
    )
    database_path = _database_path(history_services)
    original = database_path.read_bytes()
    database_path.write_bytes(original[:512])

    restored = history_plugin.invoke(
        "restore",
        {"backup_id": backup["backup_id"]},
        history_services,
        CancellationToken(),
    )

    assert restored == {
        "restored": True,
        "backup_id": backup["backup_id"],
        "pre_restore_backup_id": None,
    }
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]["output"] == "last valid output"
    _assert_database_consistent(database_path, record_ids=["history-001"])
    _assert_no_sensitive_maintenance_text(
        history_services,
        plaintext,
        history_services["history"]["keys"]["v1"],
    )


def test_truncated_backup_is_rejected_without_touching_current_database(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot(output="backup output"))
    backup = history_plugin.invoke(
        "repair", {}, history_services, CancellationToken()
    )
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, CancellationToken()
    )
    _save(history_plugin, history_services, make_snapshot(output="current output"))
    backup_path = _backup_path(history_services, backup["backup_id"])
    backup_path.write_bytes(backup_path.read_bytes()[:512])
    manifests_before = set(backup_path.parent.glob("backup-*.json"))

    with pytest.raises(HistoryPluginError) as caught:
        history_plugin.invoke(
            "restore",
            {"backup_id": backup["backup_id"]},
            history_services,
            CancellationToken(),
        )

    assert caught.value.code == "history_backup_invalid"
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]["output"] == "current output"
    assert set(backup_path.parent.glob("backup-*.json")) == manifests_before
    assert history_services["history"]["keys"]["v1"] not in repr(caught.value)


def test_backup_with_wrong_index_is_rejected_and_current_data_wins(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot(output="backup output"))
    backup = history_plugin.invoke(
        "repair", {}, history_services, CancellationToken()
    )
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, CancellationToken()
    )
    _save(history_plugin, history_services, make_snapshot(output="current output"))
    backup_path = _backup_path(history_services, backup["backup_id"])
    connection = sqlite3.connect(backup_path)
    try:
        connection.execute("DROP INDEX history_records_provider_idx")
        connection.execute(
            "CREATE INDEX history_records_provider_idx ON history_records(model)"
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(HistoryPluginError, match="history_backup_invalid"):
        history_plugin.invoke(
            "restore",
            {"backup_id": backup["backup_id"]},
            history_services,
            CancellationToken(),
        )

    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]["output"] == "current output"
    _assert_database_consistent(
        _database_path(history_services), record_ids=["history-001"]
    )


def test_repeated_restore_is_idempotent_and_keeps_data_and_indexes_consistent(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot(output="selected output"))
    backup = history_plugin.invoke(
        "repair", {}, history_services, CancellationToken()
    )
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, CancellationToken()
    )
    _save(history_plugin, history_services, make_snapshot(output="current output"))

    first = history_plugin.invoke(
        "restore",
        {"backup_id": backup["backup_id"]},
        history_services,
        CancellationToken(),
    )
    backup_manifests = set(
        _database_path(history_services).parent.glob("backups/backup-*.json")
    )
    second = history_plugin.invoke(
        "restore",
        {"backup_id": backup["backup_id"]},
        history_services,
        CancellationToken(),
    )

    assert first["pre_restore_backup_id"] is not None
    assert second == {
        "restored": True,
        "backup_id": backup["backup_id"],
        "pre_restore_backup_id": None,
    }
    assert set(
        _database_path(history_services).parent.glob("backups/backup-*.json")
    ) == backup_manifests
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]["output"] == "selected output"
    _assert_database_consistent(
        _database_path(history_services), record_ids=["history-001"]
    )


@pytest.mark.parametrize("phase", ["old_moved", "replacement_moved"])
def test_interrupted_restore_recovery_is_repeatable_and_preserves_last_valid_database(
    history_plugin, history_services, make_snapshot, phase
):
    _save(history_plugin, history_services, make_snapshot(output="preserved output"))
    database_path = _database_path(history_services)
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services),
        schema_lock=threading.RLock(),
    )
    rollback = database_path.with_name(f".{database_path.name}.rollback-crash")
    replacement = database_path.with_name(
        f".{database_path.name}.restore-crash.tmp"
    )
    repository._copy_database(database_path, replacement, CancellationToken())
    repository._write_replace_state(rollback, replacement)
    os.replace(database_path, rollback)
    if phase == "replacement_moved":
        os.replace(replacement, database_path)

    restarted = plugin()
    for _ in range(2):
        detail = restarted.invoke(
            "detail",
            {"id": "history-001"},
            history_services,
            CancellationToken(),
        )["record"]
        assert detail["output"] == "preserved output"

    assert not rollback.exists()
    assert not replacement.exists()
    assert not repository._replace_state_path().exists()
    _assert_database_consistent(database_path, record_ids=["history-001"])


def test_corrupted_rotation_checkpoint_stops_without_overwriting_readable_data(
    history_plugin, history_services, make_snapshot, monkeypatch
):
    services = history_services
    services["history"]["keys"] = {"v1": "11" * 32, "v2": "22" * 32}
    services["history"]["active_key_version"] = "v1"
    services["history"]["pending_key_version"] = "v2"
    for index in range(2):
        _save(history_plugin, services, make_snapshot(id=f"record-{index}"))

    class SimulatedProcessExit(BaseException):
        pass

    original = HistoryRepository._reencrypt_batch
    calls = 0

    def interrupt_after_commit(repository, *args, **kwargs):
        nonlocal calls
        changed = original(repository, *args, **kwargs)
        calls += 1
        if calls == 1:
            raise SimulatedProcessExit()
        return changed

    monkeypatch.setattr(HistoryRepository, "_reencrypt_batch", interrupt_after_commit)
    with pytest.raises(SimulatedProcessExit):
        history_plugin.invoke(
            "rotate",
            {"action": "prepare", "target_version": "v2", "batch_size": 1},
            services,
            CancellationToken(),
        )
    monkeypatch.setattr(HistoryRepository, "_reencrypt_batch", original)
    connection = sqlite3.connect(_database_path(services))
    try:
        connection.execute(
            "UPDATE rotation_checkpoint SET backup_id = ? WHERE id = 1",
            ("backup-missing",),
        )
        connection.commit()
    finally:
        connection.close()

    restarted = plugin()
    with pytest.raises(HistoryPluginError) as caught:
        restarted.invoke(
            "rotate",
            {"action": "prepare", "target_version": "v2", "batch_size": 1},
            services,
            CancellationToken(),
        )

    assert caught.value.code == "history_recovery_required"
    for index in range(2):
        record = restarted.invoke(
            "detail",
            {"id": f"record-{index}"},
            services,
            CancellationToken(),
        )["record"]
        assert record["corrupted"] is False
    rendered = json.dumps(caught.value.args, ensure_ascii=False) + repr(caught.value)
    assert "Original prompt" not in rendered
    assert all(key not in rendered for key in services["history"]["keys"].values())
