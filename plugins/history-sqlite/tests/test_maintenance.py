from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from reflex_core import CancellationToken
from reflex_history_sqlite.contract import HistoryPluginError, HistoryServiceSnapshot
from reflex_history_sqlite.maintenance import MaintenanceCoordinator
from reflex_history_sqlite.repository import HistoryRepository


def _save(plugin, services, snapshot, cancellation=None):
    return plugin.invoke(
        "save", snapshot, services, cancellation or CancellationToken()
    )


def _database_path(services):
    return services["history"]["database_path"]


def test_maintenance_rejects_new_reads_before_database_replacement(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot())
    history_plugin._maintenance.begin(CancellationToken(), block_reads=True)
    try:
        for operation, payload in [
            ("list", {}),
            ("detail", {"id": "history-001"}),
            ("export", {"format": "json", "filters": {}}),
            ("scan", {}),
            ("backups", {}),
        ]:
            with pytest.raises(HistoryPluginError, match="history_busy"):
                result = history_plugin.invoke(
                    operation,
                    payload,
                    history_services,
                    CancellationToken(),
                )
                if operation == "export":
                    next(result)
    finally:
        history_plugin._maintenance.end()


def test_maintenance_waits_for_an_existing_read_before_entering():
    coordinator = MaintenanceCoordinator()
    reader_entered = threading.Event()
    release_reader = threading.Event()
    maintenance_entered = threading.Event()

    def hold_read():
        with coordinator.read():
            reader_entered.set()
            assert release_reader.wait(timeout=2)

    def begin_maintenance():
        coordinator.begin(CancellationToken(), block_reads=True)
        maintenance_entered.set()

    reader = threading.Thread(target=hold_read)
    maintainer = threading.Thread(target=begin_maintenance)
    reader.start()
    assert reader_entered.wait(timeout=1)
    maintainer.start()
    assert not maintenance_entered.wait(timeout=0.1)
    release_reader.set()
    assert maintenance_entered.wait(timeout=1)
    coordinator.end()
    reader.join(timeout=1)
    maintainer.join(timeout=1)
    assert not reader.is_alive()
    assert not maintainer.is_alive()


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("save", {"snapshot": True}),
        ("rate", {"id": "history-001", "rating": 5}),
        ("delete", {"id": "history-001"}),
        ("clear", {}),
        ("repair", {}),
        ("restore", {"backup_id": "backup-1"}),
    ],
)
def test_restore_barrier_blocks_checkpoint_preflight_before_opening_sqlite(
    history_plugin,
    history_services,
    make_snapshot,
    monkeypatch,
    operation,
    payload,
):
    _save(history_plugin, history_services, make_snapshot())
    if operation == "save":
        payload = make_snapshot(id="blocked")
    checkpoint_called = False

    def checkpoint_should_not_run(*_args, **_kwargs):
        nonlocal checkpoint_called
        checkpoint_called = True
        raise AssertionError("checkpoint preflight escaped restore barrier")

    monkeypatch.setattr(
        HistoryRepository,
        "has_rotation_checkpoint",
        checkpoint_should_not_run,
    )
    history_plugin._maintenance.begin(CancellationToken(), block_reads=True)
    try:
        with pytest.raises(HistoryPluginError, match="history_busy"):
            history_plugin.invoke(
                operation,
                payload,
                history_services,
                CancellationToken(),
            )
    finally:
        history_plugin._maintenance.end()
    assert checkpoint_called is False


@pytest.mark.parametrize("phase", ["old_moved", "replacement_moved"])
def test_interrupted_replace_restores_rollback_before_missing_main_can_reinitialize(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    phase,
):
    from reflex_history_sqlite import plugin

    _save(history_plugin, history_services, make_snapshot(output="preserved"))
    database_path = _database_path(history_services)
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services),
        schema_lock=threading.RLock(),
    )
    rollback = database_path.with_name(f".{database_path.name}.rollback-crash")
    replacement = database_path.with_name(f".{database_path.name}.restore-crash.tmp")
    replacement.write_bytes(b"unverified replacement")
    repository._write_replace_state(rollback, replacement)
    database_path.replace(rollback)
    if phase == "replacement_moved":
        replacement.replace(database_path)
        assert database_path.is_file()
    else:
        assert not database_path.exists()

    restarted = plugin()
    detail = restarted.invoke(
        "detail",
        {"id": "history-001"},
        history_services,
        cancellation,
    )["record"]

    assert detail["output"] == "preserved"
    assert database_path.is_file()
    assert not rollback.exists()
    assert not replacement.exists()
    assert not repository._replace_state_path().exists()


def test_scan_and_backup_manifest_verify_schema_keys_counts_and_aead(
    history_plugin, history_services, make_snapshot, cancellation
):
    _save(history_plugin, history_services, make_snapshot())

    scan = history_plugin.invoke("scan", {}, history_services, cancellation)
    created = history_plugin.invoke("repair", {}, history_services, cancellation)
    backups = history_plugin.invoke("backups", {}, history_services, cancellation)

    assert scan == {
        "quick_check": "ok",
        "record_count": 1,
        "verified_records": 1,
        "corrupted_records": 0,
    }
    assert created["backup_id"] == backups["items"][0]["id"]
    manifest = backups["items"][0]
    assert set(manifest) == {
        "id",
        "schema_version",
        "created_at",
        "key_versions",
        "record_count",
        "aead",
    }
    assert manifest["schema_version"] == 1
    assert manifest["key_versions"] == ["v1"]
    assert manifest["record_count"] == 1
    assert manifest["aead"] == {"verified": 1, "corrupted": 0}
    assert "Original prompt" not in json.dumps(manifest)
    assert str(_database_path(history_services)) not in json.dumps(manifest)
    assert history_services["history"]["keys"]["v1"] not in json.dumps(manifest)


def test_repair_creates_verified_backup_before_isolating_bad_record_and_rebuilds_indexes(
    history_plugin, history_services, make_snapshot, cancellation
):
    _save(history_plugin, history_services, make_snapshot(id="good"))
    _save(history_plugin, history_services, make_snapshot(id="bad"))
    path = _database_path(history_services)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE history_records SET output_ciphertext = ? WHERE id = ?",
            (sqlite3.Binary(b"tampered"), "bad"),
        )
        connection.execute("DROP INDEX history_records_provider_idx")
        connection.execute(
            "CREATE INDEX history_records_provider_idx ON history_records(model)"
        )
        connection.commit()
    finally:
        connection.close()

    result = history_plugin.invoke("repair", {}, history_services, cancellation)

    assert result["record_count"] == 2
    assert result["verified_records"] == 1
    assert result["quarantined_records"] == 1
    assert "input" not in result and "output" not in result
    connection = sqlite3.connect(path)
    try:
        assert connection.execute(
            "SELECT id FROM history_records ORDER BY id"
        ).fetchall() == [("good",)]
        assert connection.execute(
            "SELECT id, reason FROM repair_quarantine"
        ).fetchall() == [("bad", "history_record_corrupted")]
        provider_index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='history_records_provider_idx'"
        ).fetchone()[0]
        assert provider_index == (
            "CREATE INDEX history_records_provider_idx ON history_records(provider)"
        )
    finally:
        connection.close()

    backup = history_plugin.invoke("backups", {}, history_services, cancellation)["items"][0]
    assert backup["record_count"] == 2
    assert backup["aead"] == {"verified": 1, "corrupted": 1}


def test_maintenance_freezes_all_writes_and_other_maintenance(
    history_plugin, history_services, make_snapshot, monkeypatch
):
    _save(history_plugin, history_services, make_snapshot())
    entered = threading.Event()
    release = threading.Event()
    original = HistoryRepository._online_backup

    def slow_backup(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HistoryRepository, "_online_backup", slow_backup)
    result = []

    def repair():
        result.append(
            history_plugin.invoke(
                "repair", {}, history_services, CancellationToken()
            )
        )

    worker = threading.Thread(target=repair)
    worker.start()
    assert entered.wait(5)
    try:
        for operation, payload in [
            ("save", make_snapshot(id="blocked")),
            ("rate", {"id": "history-001", "rating": 5}),
            ("delete", {"id": "history-001"}),
            ("clear", {}),
            ("repair", {}),
            ("restore", {"backup_id": "backup-1"}),
            ("rotate", {"action": "prepare", "target_version": "v2"}),
        ]:
            with pytest.raises(HistoryPluginError, match="history_busy"):
                history_plugin.invoke(
                    operation, payload, history_services, CancellationToken()
                )
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert result[0]["verified_records"] == 1


def test_restore_accepts_only_listed_id_and_failure_preserves_original_in_recovery(
    history_plugin, history_services, make_snapshot, cancellation, monkeypatch
):
    _save(history_plugin, history_services, make_snapshot(output="before"))
    repaired = history_plugin.invoke("repair", {}, history_services, cancellation)
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, cancellation
    )

    with pytest.raises(HistoryPluginError, match="history_backup_invalid"):
        history_plugin.invoke(
            "restore",
            {"backup_id": "not-listed"},
            history_services,
            cancellation,
        )

    original_replace = HistoryRepository._replace_database

    def fail_replace(self, *args, **kwargs):
        raise OSError("fixture private path")

    monkeypatch.setattr(HistoryRepository, "_replace_database", fail_replace)
    with pytest.raises(HistoryPluginError, match="history_recovery_required") as caught:
        history_plugin.invoke(
            "restore",
            {"backup_id": repaired["backup_id"]},
            history_services,
            cancellation,
        )
    assert "fixture" not in str(caught.value)
    monkeypatch.setattr(HistoryRepository, "_replace_database", original_replace)

    detail = history_plugin.invoke(
        "list", {}, history_services, CancellationToken()
    )
    assert detail["items"] == []
    with pytest.raises(HistoryPluginError, match="history_recovery_required"):
        _save(history_plugin, history_services, make_snapshot(id="after-failure"))


def test_restore_makes_a_pre_restore_backup_and_recovers_selected_snapshot(
    history_plugin, history_services, make_snapshot, cancellation
):
    _save(history_plugin, history_services, make_snapshot(output="before"))
    first = history_plugin.invoke("repair", {}, history_services, cancellation)
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, cancellation
    )

    restored = history_plugin.invoke(
        "restore",
        {"backup_id": first["backup_id"]},
        history_services,
        cancellation,
    )

    assert restored["restored"] is True
    assert restored["pre_restore_backup_id"] != first["backup_id"]
    detail = history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, cancellation
    )
    assert detail["record"]["output"] == "before"
    assert len(history_plugin.invoke("backups", {}, history_services, cancellation)["items"]) == 2


def test_restore_rejects_listed_backup_when_any_record_fails_aead(
    history_plugin, history_services, make_snapshot, cancellation
):
    _save(history_plugin, history_services, make_snapshot(output="current"))
    backup = history_plugin.invoke("repair", {}, history_services, cancellation)
    backup_path = (
        _database_path(history_services).parent
        / "backups"
        / f"{backup['backup_id']}.sqlite3"
    )
    connection = sqlite3.connect(backup_path)
    try:
        connection.execute(
            "UPDATE history_records SET output_ciphertext = ? WHERE id = ?",
            (sqlite3.Binary(b"tampered"), "history-001"),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(HistoryPluginError, match="history_backup_invalid"):
        history_plugin.invoke(
            "restore",
            {"backup_id": backup["backup_id"]},
            history_services,
            cancellation,
        )

    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, cancellation
    )["record"]["output"] == "current"


@pytest.mark.parametrize("failure", ["verification", "cancellation"])
def test_restore_post_replace_failure_restores_original_database(
    history_plugin,
    history_services,
    make_snapshot,
    cancellation,
    monkeypatch,
    failure,
):
    _save(history_plugin, history_services, make_snapshot(output="backup"))
    backup = history_plugin.invoke("repair", {}, history_services, cancellation)
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, cancellation
    )
    _save(history_plugin, history_services, make_snapshot(output="current"))
    database_path = _database_path(history_services)
    original_verify = HistoryRepository._verify_database

    def fail_after_replace(repository, path, token):
        if path == database_path:
            if failure == "cancellation":
                token.cancel()
                token.raise_if_cancelled()
            raise HistoryPluginError("history_backup_invalid")
        return original_verify(repository, path, token)

    monkeypatch.setattr(HistoryRepository, "_verify_database", fail_after_replace)

    with pytest.raises((HistoryPluginError, Exception)):
        history_plugin.invoke(
            "restore",
            {"backup_id": backup["backup_id"]},
            history_services,
            cancellation,
        )

    detail = history_plugin.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]
    assert detail["output"] == "current"
    assert not list(database_path.parent.glob(f".{database_path.name}.rollback-*"))


def test_restore_is_available_in_recovery_and_clears_persisted_marker(
    history_plugin, history_services, make_snapshot, cancellation
):
    from reflex_history_sqlite import plugin

    _save(history_plugin, history_services, make_snapshot(output="backup"))
    backup = history_plugin.invoke("repair", {}, history_services, cancellation)
    history_plugin.invoke(
        "delete", {"id": "history-001"}, history_services, cancellation
    )
    _save(history_plugin, history_services, make_snapshot(output="current"))
    database_path = _database_path(history_services)
    marker = database_path.with_name(f".{database_path.name}.recovery-required")
    marker.write_bytes(b"recovery-required\n")
    restarted = plugin()

    with pytest.raises(HistoryPluginError, match="history_recovery_required"):
        _save(
            restarted,
            history_services,
            make_snapshot(id="blocked"),
            CancellationToken(),
        )
    assert restarted.invoke(
        "backups", {}, history_services, CancellationToken()
    )["items"]

    result = restarted.invoke(
        "restore",
        {"backup_id": backup["backup_id"]},
        history_services,
        CancellationToken(),
    )

    assert result["restored"] is True
    assert not marker.exists()
    assert restarted.invoke(
        "detail", {"id": "history-001"}, history_services, CancellationToken()
    )["record"]["output"] == "backup"
    assert _save(
        restarted,
        history_services,
        make_snapshot(id="after-restore"),
        CancellationToken(),
    )["id"] == "after-restore"
