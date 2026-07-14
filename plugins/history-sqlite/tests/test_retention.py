from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock

import pytest

from reflex_core import CancellationToken
from reflex_history_sqlite.contract import (
    DEFAULT_RETENTION_CHECK_INTERVAL_SAVES,
    DEFAULT_RETENTION_CLEANUP_BATCH_SIZE,
    DEFAULT_RETENTION_BACKUP_MAX_AGE_DAYS,
    DEFAULT_RETENTION_BACKUP_MAX_COUNT,
    DEFAULT_RETENTION_MAX_AGE_DAYS,
    DEFAULT_RETENTION_MAX_DATABASE_BYTES,
    DEFAULT_RETENTION_MAX_RECORDS,
    HistoryPluginError,
    HistoryServiceSnapshot,
)
from reflex_history_sqlite.repository import HistoryRepository


def _timestamp(*, days_ago: int = 0, sequence: int = 0) -> str:
    value = datetime.now(timezone.utc) - timedelta(days=days_ago, seconds=sequence)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _save(history_plugin, services, make_snapshot, record_id, **changes):
    payload = make_snapshot(
        id=record_id,
        created_at=changes.pop("created_at", _timestamp(sequence=int(record_id[-2:]))),
        **changes,
    )
    return history_plugin.invoke("save", payload, services, CancellationToken())


def _record_ids(services) -> list[str]:
    connection = sqlite3.connect(services["history"]["database_path"])
    try:
        return [
            row[0]
            for row in connection.execute(
                "SELECT id FROM history_records ORDER BY created_at, id"
            )
        ]
    finally:
        connection.close()


def test_retention_defaults_are_safe_and_optional(history_services):
    snapshot = HistoryServiceSnapshot.from_services(history_services)

    assert snapshot.retention.max_records == DEFAULT_RETENTION_MAX_RECORDS == 10_000
    assert snapshot.retention.max_age_days == DEFAULT_RETENTION_MAX_AGE_DAYS == 180
    assert (
        snapshot.retention.max_database_bytes
        == DEFAULT_RETENTION_MAX_DATABASE_BYTES
        == 512 * 1024 * 1024
    )
    assert snapshot.retention.cleanup_batch_size == DEFAULT_RETENTION_CLEANUP_BATCH_SIZE == 500
    assert snapshot.retention.check_interval_saves == DEFAULT_RETENTION_CHECK_INTERVAL_SAVES == 100
    assert snapshot.retention.backup_max_count == DEFAULT_RETENTION_BACKUP_MAX_COUNT == 3
    assert snapshot.retention.backup_max_age_days == DEFAULT_RETENTION_BACKUP_MAX_AGE_DAYS == 30


@pytest.mark.parametrize(
    "retention",
    [
        {"max_records": 0},
        {"max_age_days": True},
        {"max_database_bytes": 1024},
        {"cleanup_batch_size": 501},
        {"check_interval_saves": 0},
        {"backup_max_count": 0},
        {"backup_max_age_days": 0},
        {"unknown": 1},
    ],
)
def test_retention_service_configuration_is_strict(history_services, retention):
    history_services["history"]["retention"] = retention

    with pytest.raises(HistoryPluginError, match="history_service_unavailable"):
        HistoryServiceSnapshot.from_services(history_services)


def test_count_limit_prunes_oldest_record_without_waiting_for_periodic_check(
    history_plugin, history_services, make_snapshot
):
    history_services["history"]["retention"] = {
        "max_records": 3,
        "check_interval_saves": 10_000,
    }
    for index in range(4):
        _save(
            history_plugin,
            history_services,
            make_snapshot,
            f"history-{index:02d}",
            created_at=_timestamp(sequence=100 - index),
        )

    assert _record_ids(history_services) == [
        "history-01",
        "history-02",
        "history-03",
    ]


def test_age_limit_runs_on_configured_low_cost_interval(
    history_plugin, history_services, make_snapshot
):
    history_services["history"]["retention"] = {
        "max_records": 100,
        "max_age_days": 1,
        "check_interval_saves": 2,
    }
    _save(
        history_plugin,
        history_services,
        make_snapshot,
        "history-01",
        created_at=_timestamp(days_ago=2),
    )
    assert _record_ids(history_services) == ["history-01"]

    _save(history_plugin, history_services, make_snapshot, "history-02")

    assert _record_ids(history_services) == ["history-02"]


def test_cleanup_never_exceeds_configured_batch_and_marks_backlog(
    history_plugin, history_services, make_snapshot
):
    history_services["history"]["retention"] = {
        "max_records": 100,
        "check_interval_saves": 10_000,
    }
    for index in range(6):
        _save(history_plugin, history_services, make_snapshot, f"history-{index:02d}")

    history_services["history"]["retention"] = {
        "max_records": 1,
        "cleanup_batch_size": 2,
        "check_interval_saves": 10_000,
    }
    _save(history_plugin, history_services, make_snapshot, "history-06")

    assert len(_record_ids(history_services)) == 5
    connection = sqlite3.connect(history_services["history"]["database_path"])
    try:
        pending = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'retention_pending'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert pending == "1"


def test_database_budget_rejects_single_record_that_cannot_fit(
    history_plugin, history_services, make_snapshot
):
    history_services["history"]["retention"] = {
        "max_database_bytes": 64 * 1024,
        "check_interval_saves": 1,
    }

    with pytest.raises(HistoryPluginError, match="history_storage_limit"):
        _save(
            history_plugin,
            history_services,
            make_snapshot,
            "history-01",
            input="i" * 80_000,
            output="o" * 80_000,
        )

    assert _record_ids(history_services) == []


def test_record_retention_never_deletes_restore_backups(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    backup = repository.create_backup(CancellationToken())
    backup_directory = history_services["history"]["database_path"].parent / "backups"

    history_services["history"]["retention"] = {
        "max_records": 1,
        "check_interval_saves": 1,
    }
    _save(history_plugin, history_services, make_snapshot, "history-02")

    assert (backup_directory / f"{backup['id']}.json").is_file()
    assert (backup_directory / f"{backup['id']}.sqlite3").is_file()


def test_restore_repairs_retention_metadata_before_next_save(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    backup = repository.create_backup(CancellationToken())
    backup_path = (
        history_services["history"]["database_path"].parent
        / "backups"
        / f"{backup['id']}.sqlite3"
    )
    connection = sqlite3.connect(backup_path)
    try:
        connection.execute(
            "DELETE FROM schema_meta WHERE key IN "
            "('retention_record_count', 'retention_save_count', 'retention_pending')"
        )
        connection.commit()
    finally:
        connection.close()

    _save(history_plugin, history_services, make_snapshot, "history-02")
    restored = history_plugin.invoke(
        "restore",
        {"backup_id": backup["id"]},
        history_services,
        CancellationToken(),
    )

    assert restored["restored"] is True
    assert _save(
        history_plugin, history_services, make_snapshot, "history-03"
    ) == {"id": "history-03"}


def test_backup_retention_keeps_only_three_recent_verified_pairs(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )

    backup_ids = [
        repository.create_backup(CancellationToken())["id"] for _ in range(4)
    ]
    backup_directory = history_services["history"]["database_path"].parent / "backups"

    manifests = sorted(backup_directory.glob("backup-*.json"))
    databases = sorted(backup_directory.glob("backup-*.sqlite3"))
    assert len(manifests) == len(databases) == 3
    assert not (backup_directory / f"{backup_ids[0]}.json").exists()


def test_backup_retention_removes_expired_pair_even_below_count_limit(
    history_plugin, history_services, make_snapshot
):
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    expired = repository.create_backup(CancellationToken())
    backup_directory = history_services["history"]["database_path"].parent / "backups"
    manifest_path = backup_directory / f"{expired['id']}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at"] = _timestamp(days_ago=31)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    repository.create_backup(CancellationToken())

    assert not manifest_path.exists()
    assert not (backup_directory / f"{expired['id']}.sqlite3").exists()


def test_backup_pruning_finishes_its_plan_when_cancel_arrives_during_delete(
    history_plugin, history_services, make_snapshot, monkeypatch
):
    history_services["history"]["retention"] = {"backup_max_count": 100}
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    backup_ids = [
        repository.create_backup(CancellationToken())["id"] for _ in range(5)
    ]
    history_services["history"]["retention"] = {"backup_max_count": 3}
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    cancellation = CancellationToken()
    original_unlink = Path.unlink
    cancellation_sent = False

    def cancel_during_first_database_delete(path, *args, **kwargs):
        nonlocal cancellation_sent
        result = original_unlink(path, *args, **kwargs)
        if path.suffix == ".sqlite3" and not cancellation_sent:
            cancellation_sent = True
            cancellation.cancel()
        return result

    monkeypatch.setattr(Path, "unlink", cancel_during_first_database_delete)

    repository._prune_backups(backup_ids[-1], cancellation)

    backup_directory = history_services["history"]["database_path"].parent / "backups"
    assert cancellation_sent is True
    assert len(list(backup_directory.glob("backup-*.json"))) == 3
    assert len(list(backup_directory.glob("backup-*.sqlite3"))) == 3


def test_rotation_checkpoint_backup_is_protected_beyond_backup_count_limit(
    history_plugin, history_services, make_snapshot
):
    history_services["history"]["retention"] = {"backup_max_count": 1}
    _save(history_plugin, history_services, make_snapshot, "history-01")
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    protected = repository.create_backup(CancellationToken())
    database_path = history_services["history"]["database_path"]
    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            "INSERT INTO rotation_checkpoint("
            "id, rotation_id, source_version, target_version, phase, backup_id, "
            "high_water_mark, last_record_id) VALUES (1, ?, 1, 2, 'verified', ?, ?, NULL)",
            ("rotation-test", protected["id"], "history-01"),
        )
        connection.commit()
    finally:
        connection.close()

    superseded = repository.create_backup(CancellationToken())
    latest = repository.create_backup(CancellationToken())
    backup_directory = database_path.parent / "backups"

    assert (backup_directory / f"{protected['id']}.json").is_file()
    assert (backup_directory / f"{latest['id']}.json").is_file()
    assert not (backup_directory / f"{superseded['id']}.json").exists()
