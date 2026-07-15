"""Verify a history database written by the previous Runtime with the current Runtime."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import history_upgrade_smoke as upgrade
import provider_smoke
from reflex_history_sqlite.repository import (
    INDEX_DEFINITIONS,
    INDEX_LAYOUT_KEY,
    INDEX_LAYOUT_VERSION,
    LEGACY_INDEX_DEFINITIONS,
)


ERROR_CODE_PATTERN = upgrade.ERROR_CODE_PATTERN
FIXTURE_KEY_HEX = upgrade.FIXTURE_KEY_HEX
OUTPUT_FIELDS = (
    "operation",
    "classification",
    "legacy_schema",
    "current_schema",
    "backup_schema",
    "legacy_layout",
    "current_layout",
    "legacy_detail_read",
    "legacy_list_read",
    "new_record_saved",
    "migration_backup_preserved",
    "error_code",
)


class CrossVersionFailure(Exception):
    def __init__(self, code: str) -> None:
        normalized = code if ERROR_CODE_PATTERN.fullmatch(code) else "cross_version_failed"
        self.code = normalized
        super().__init__(normalized)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise CrossVersionFailure("invalid_arguments")


def _record(
    classification: str,
    *,
    legacy_schema: int | None = None,
    current_schema: int | None = None,
    backup_schema: int | None = None,
    legacy_layout: str | None = None,
    current_layout: int | None = None,
    legacy_detail_read: bool = False,
    legacy_list_read: bool = False,
    new_record_saved: bool = False,
    migration_backup_preserved: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    value = {
        "operation": "cross_version_history_upgrade",
        "classification": classification,
        "legacy_schema": legacy_schema,
        "current_schema": current_schema,
        "backup_schema": backup_schema,
        "legacy_layout": legacy_layout,
        "current_layout": current_layout,
        "legacy_detail_read": legacy_detail_read,
        "legacy_list_read": legacy_list_read,
        "new_record_saved": new_record_saved,
        "migration_backup_preserved": migration_backup_preserved,
        "error_code": (
            error_code if error_code and ERROR_CODE_PATTERN.fullmatch(error_code) else None
        ),
    }
    return {field: value[field] for field in OUTPUT_FIELDS}


def _emit(record: dict[str, Any], *, work_root: Path | None = None) -> None:
    if work_root is not None:
        record = {**record, "work_root": str(work_root)}
    print(json.dumps(record, ensure_ascii=True, separators=(",", ":")), flush=True)


def _configure_fixture_runtime(
    runtime: provider_smoke.RuntimeProcess,
    database: Path,
    prefix: str,
    timeout: float,
) -> None:
    commands = (
        (
            f"{prefix}-path",
            "configure_history_path",
            {"database_path": str(database.resolve())},
        ),
        (
            f"{prefix}-keys",
            "configure_history_keys",
            {
                "keys": {"v1": FIXTURE_KEY_HEX},
                "active_version": "v1",
                "pending_version": None,
            },
        ),
        (
            f"{prefix}-policy",
            "configure_history_policy",
            {
                "history_enabled": True,
                "privacy_mode": False,
                "history_redaction": "none",
            },
        ),
    )
    for request_id, command_type, payload in commands:
        runtime.send(request_id, command_type, payload)
        try:
            upgrade._wait_status(runtime, request_id, timeout)
        except upgrade.UpgradeSmokeFailure as error:
            raise CrossVersionFailure(error.code) from error


def _schema_snapshot(database: Path) -> dict[str, Any]:
    if not database.is_file():
        raise CrossVersionFailure("history_database_missing")
    connection = sqlite3.connect(database)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        indexes = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'history_records' "
                "AND sql IS NOT NULL ORDER BY name"
            )
        )
        metadata = dict(connection.execute("SELECT key, value FROM schema_meta"))
        record_count = connection.execute(
            "SELECT count(*) FROM history_records"
        ).fetchone()[0]
    except sqlite3.Error as error:
        raise CrossVersionFailure("history_schema_unreadable") from error
    finally:
        connection.close()
    return {
        "version": version,
        "indexes": indexes,
        "metadata": metadata,
        "record_count": record_count,
    }


def _assert_legacy_snapshot(snapshot: dict[str, Any]) -> None:
    expected = dict(LEGACY_INDEX_DEFINITIONS)
    if snapshot["version"] != 1 or snapshot["indexes"] != expected:
        raise CrossVersionFailure("legacy_runtime_schema_unexpected")
    if snapshot["metadata"].get("schema_version") != "1":
        raise CrossVersionFailure("legacy_runtime_metadata_unexpected")
    if INDEX_LAYOUT_KEY in snapshot["metadata"]:
        raise CrossVersionFailure("legacy_runtime_layout_already_current")
    if snapshot["record_count"] != 1:
        raise CrossVersionFailure("legacy_record_missing")


def _assert_current_snapshot(snapshot: dict[str, Any]) -> None:
    expected = dict(INDEX_DEFINITIONS)
    if snapshot["version"] != 1 or snapshot["indexes"] != expected:
        raise CrossVersionFailure("current_runtime_schema_unexpected")
    if snapshot["metadata"].get(INDEX_LAYOUT_KEY) != str(INDEX_LAYOUT_VERSION):
        raise CrossVersionFailure("current_runtime_layout_unexpected")
    if snapshot["record_count"] != 2:
        raise CrossVersionFailure("cross_version_records_missing")


def _assert_backup(backup: Path, legacy_snapshot: dict[str, Any]) -> int:
    if not backup.is_file():
        raise CrossVersionFailure("migration_backup_missing")
    snapshot = _schema_snapshot(backup)
    if snapshot != legacy_snapshot:
        raise CrossVersionFailure("migration_backup_not_legacy_snapshot")
    return int(snapshot["version"])


def _run(
    legacy_runtime_path: Path,
    current_runtime_path: Path,
    timeout: float,
    root: Path,
) -> dict[str, Any]:
    if not legacy_runtime_path.is_file() or not current_runtime_path.is_file():
        raise CrossVersionFailure("runtime_unavailable")

    database = root / "profile" / "data" / "history" / "history.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)

    legacy = provider_smoke.RuntimeProcess(
        [str(legacy_runtime_path)], cwd=ROOT, development_fixture=True
    )
    try:
        _configure_fixture_runtime(legacy, database, "legacy", timeout)
        try:
            legacy_id = upgrade._run_optimization(legacy, "mock", "mock-stream", timeout)
        except upgrade.UpgradeSmokeFailure as error:
            raise CrossVersionFailure(error.code) from error
    finally:
        legacy.close()

    legacy_snapshot = _schema_snapshot(database)
    _assert_legacy_snapshot(legacy_snapshot)

    current = provider_smoke.RuntimeProcess(
        [str(current_runtime_path)], cwd=ROOT, development_fixture=True
    )
    try:
        _configure_fixture_runtime(current, database, "current", timeout)
        try:
            detail = upgrade._plugin_call(
                current,
                "cross-version-detail",
                "detail",
                {"id": legacy_id},
                timeout,
            )
            listed_before = upgrade._plugin_call(
                current,
                "cross-version-list-before",
                "list",
                {"page_size": 50, "sort": "created_at", "direction": "desc"},
                timeout,
            )
            new_id = upgrade._run_optimization(
                current, "mock", "mock-stream", timeout
            )
            listed_after = upgrade._plugin_call(
                current,
                "cross-version-list-after",
                "list",
                {"page_size": 50, "sort": "created_at", "direction": "desc"},
                timeout,
            )
        except upgrade.UpgradeSmokeFailure as error:
            raise CrossVersionFailure(error.code) from error
    finally:
        current.close()

    detail_record = detail.get("record") if isinstance(detail, dict) else None
    before_items = listed_before.get("items") if isinstance(listed_before, dict) else None
    after_items = listed_after.get("items") if isinstance(listed_after, dict) else None
    if not isinstance(detail_record, dict) or detail_record.get("id") != legacy_id:
        raise CrossVersionFailure("legacy_detail_missing")
    if not isinstance(before_items, list) or not any(
        isinstance(item, dict) and item.get("id") == legacy_id for item in before_items
    ):
        raise CrossVersionFailure("legacy_list_missing")
    if not isinstance(after_items, list) or not {
        legacy_id,
        new_id,
    }.issubset(
        {item.get("id") for item in after_items if isinstance(item, dict)}
    ):
        raise CrossVersionFailure("cross_version_list_missing")

    current_snapshot = _schema_snapshot(database)
    _assert_current_snapshot(current_snapshot)
    backup = database.with_name(f"{database.name}.migration-v{legacy_snapshot['version']}.bak")
    backup_schema = _assert_backup(backup, legacy_snapshot)

    return _record(
        "success",
        legacy_schema=int(legacy_snapshot["version"]),
        current_schema=int(current_snapshot["version"]),
        backup_schema=backup_schema,
        legacy_layout="legacy",
        current_layout=int(current_snapshot["metadata"][INDEX_LAYOUT_KEY]),
        legacy_detail_read=True,
        legacy_list_read=True,
        new_record_saved=True,
        migration_backup_preserved=True,
    )


def _parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(
        description="Run the previous-to-current packaged history migration gate."
    )
    parser.add_argument("--legacy-runtime", required=True)
    parser.add_argument(
        "--current-runtime",
        default=str(
            ROOT
            / "apps"
            / "tauri-host"
            / "src-tauri"
            / "resources"
            / "runtime"
            / "reflex-runtime.exe"
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--keep-work-root", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    root: Path | None = None
    keep = False
    try:
        args = _parser().parse_args(argv)
        keep = bool(args.keep_work_root)
        if not 5.0 <= args.timeout_seconds <= 120.0:
            raise CrossVersionFailure("invalid_arguments")
        root = Path(tempfile.mkdtemp(prefix="reflex-cross-version-history-"))
        record = _run(
            Path(args.legacy_runtime).resolve(),
            Path(args.current_runtime).resolve(),
            args.timeout_seconds,
            root,
        )
        _emit(record, work_root=root if keep else None)
        return 0
    except CrossVersionFailure as error:
        _emit(_record("tool_error", error_code=error.code), work_root=root if keep else None)
        return 2
    except Exception:
        _emit(
            _record("tool_error", error_code="unexpected_failure"),
            work_root=root if keep else None,
        )
        return 2
    finally:
        if root is not None and not keep:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
