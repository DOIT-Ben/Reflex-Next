"""Manual release-gate smoke for a packaged history migration."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import provider_smoke
from provider_smoke import RuntimeProcess
from reflex_history_sqlite.codec import HistoryCodec, HistoryMetadata
from reflex_history_sqlite.repository import (
    LEGACY_INDEX_DEFINITIONS,
    SCHEMA_SQL,
)


PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9_.-]{1,64}$")
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
FIXTURE_KEY_HEX = "11" * 32
LEGACY_RECORD_ID = "legacy-record"
LEGACY_INPUT = "legacy input fixture"
LEGACY_OUTPUT = "legacy output fixture"
OUTPUT_FIELDS = (
    "operation",
    "provider_id",
    "model_id",
    "classification",
    "legacy_schema",
    "current_schema",
    "backup_schema",
    "legacy_detail_read",
    "new_record_saved",
    "list_read",
    "error_code",
)


class UpgradeSmokeFailure(Exception):
    def __init__(self, code: str) -> None:
        normalized = code if ERROR_CODE_PATTERN.fullmatch(code) else "upgrade_smoke_failed"
        self.code = normalized
        super().__init__(normalized)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise UpgradeSmokeFailure("invalid_arguments")


def _record(
    provider_id: str,
    model_id: str,
    classification: str,
    *,
    legacy_schema: int | None = None,
    current_schema: int | None = None,
    backup_schema: int | None = None,
    legacy_detail_read: bool = False,
    new_record_saved: bool = False,
    list_read: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    value = {
        "operation": "history_upgrade",
        "provider_id": provider_id if PROVIDER_ID_PATTERN.fullmatch(provider_id) else "unknown",
        "model_id": model_id if MODEL_ID_PATTERN.fullmatch(model_id) else "unknown",
        "classification": classification,
        "legacy_schema": legacy_schema,
        "current_schema": current_schema,
        "backup_schema": backup_schema,
        "legacy_detail_read": legacy_detail_read,
        "new_record_saved": new_record_saved,
        "list_read": list_read,
        "error_code": error_code if error_code and ERROR_CODE_PATTERN.fullmatch(error_code) else None,
    }
    return {field: value[field] for field in OUTPUT_FIELDS}


def _emit(record: dict[str, Any], *, work_root: Path | None = None) -> None:
    if work_root is not None:
        record = {**record, "work_root": str(work_root)}
    print(json.dumps(record, ensure_ascii=True, separators=(",", ":")), flush=True)


def _safe_event_code(event: dict[str, Any]) -> str:
    data = event.get("event", {}).get("data")
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) and ERROR_CODE_PATTERN.fullmatch(code) else "runtime_error"


def _create_legacy_database(root: Path) -> tuple[Path, str]:
    database = root / "profile" / "data" / "history" / "history.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    created_at = "2026-01-02T03:04:05Z"
    metadata = HistoryMetadata(
        id=LEGACY_RECORD_ID,
        created_at=created_at,
        mode="content",
        style="balanced",
        scene="general",
        provider="minimax",
        model="MiniMax-M2.7-highspeed",
        elapsed_ms=42,
        status="completed",
    )
    codec = HistoryCodec({1: bytes.fromhex(FIXTURE_KEY_HEX)})
    input_field = codec.encrypt(LEGACY_INPUT, metadata, 1, "input")
    output_field = codec.encrypt(LEGACY_OUTPUT, metadata, 1, "output")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA_SQL)
        for _name, statement in LEGACY_INDEX_DEFINITIONS:
            connection.execute(statement)
        connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO legacy_marker(value) VALUES (?)", ("preserved",))
        connection.execute(
            """INSERT INTO history_records(
                id, created_at, input_nonce, input_ciphertext,
                output_nonce, output_ciphertext, key_version,
                mode, style, scene, provider, model, elapsed_ms,
                status, rating, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                LEGACY_RECORD_ID,
                created_at,
                sqlite3.Binary(input_field.nonce),
                sqlite3.Binary(input_field.ciphertext),
                sqlite3.Binary(output_field.nonce),
                sqlite3.Binary(output_field.ciphertext),
                1,
                "content",
                "balanced",
                "general",
                "minimax",
                "MiniMax-M2.7-highspeed",
                42,
                "completed",
                None,
                '["legacy"]',
            ),
        )
        connection.execute("PRAGMA user_version = 0")
        connection.commit()
    finally:
        connection.close()
    return database, LEGACY_RECORD_ID


def _wait_status(runtime: RuntimeProcess, request_id: str, timeout: float) -> None:
    event = runtime.receive(request_id, timeout)
    body = event.get("event")
    if not isinstance(body, dict):
        raise UpgradeSmokeFailure("invalid_runtime_output")
    if body.get("type") == "error":
        raise UpgradeSmokeFailure(_safe_event_code(event))
    if body.get("type") != "status" or body.get("data", {}).get("phase") != "completed":
        raise UpgradeSmokeFailure("configuration_failed")


def _configure_runtime(
    runtime: RuntimeProcess,
    database: Path,
    provider_id: str,
    model_id: str,
    timeout: float,
) -> None:
    configuration = (
        (
            "upgrade-path",
            "configure_history_path",
            {"database_path": str(database.resolve())},
        ),
        (
            "upgrade-keys",
            "configure_history_keys",
            {"keys": {"v1": FIXTURE_KEY_HEX}, "active_version": "v1", "pending_version": None},
        ),
        (
            "upgrade-policy",
            "configure_history_policy",
            {"history_enabled": True, "privacy_mode": False, "history_redaction": "none"},
        ),
    )
    for request_id, command_type, payload in configuration:
        runtime.send(request_id, command_type, payload)
        _wait_status(runtime, request_id, timeout)

    try:
        secret = provider_smoke._read_windows_credential(provider_id)
    except provider_smoke.SmokeFailure as error:
        raise UpgradeSmokeFailure(error.code) from error
    runtime.send(
        "upgrade-provider",
        "configure_provider",
        {
            "provider_id": provider_id,
            "secret": secret,
            "config": {"model": model_id, "tls_verify": True, "ca_bundle_path": None},
        },
    )
    _wait_status(runtime, "upgrade-provider", timeout)


def _run_optimization(
    runtime: RuntimeProcess,
    provider_id: str,
    model_id: str,
    timeout: float,
) -> str:
    request_id = "upgrade-optimize"
    runtime.send(
        request_id,
        "optimize",
        {
            "text": "Rewrite this sentence clearly: The migration check is ready.",
            "mode": "content",
            "style": "balanced",
            "scene": "general",
            "scene_policy": "manual",
            "provider": provider_id,
            "model": model_id,
            "stream": True,
            "metadata": {"smoke_operation": "history_upgrade"},
        },
    )
    deadline = time.monotonic() + timeout
    history_id: str | None = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise UpgradeSmokeFailure("smoke_timeout")
        event = runtime.receive(request_id, remaining)
        body = event.get("event")
        if not isinstance(body, dict):
            raise UpgradeSmokeFailure("invalid_runtime_output")
        event_type = body.get("type")
        if event_type == "error":
            raise UpgradeSmokeFailure(_safe_event_code(event))
        if event_type == "status" and body.get("data", {}).get("phase") == "cancelled":
            raise UpgradeSmokeFailure("unexpected_cancel")
        if event_type == "metric":
            candidate = body.get("data", {}).get("history_id")
            if isinstance(candidate, str) and candidate:
                history_id = candidate
                break
    if history_id is None:
        raise UpgradeSmokeFailure("history_save_not_observed")
    return history_id


def _plugin_call(
    runtime: RuntimeProcess,
    request_id: str,
    operation: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    runtime.send(
        request_id,
        "plugin_call",
        {"plugin_id": "history-sqlite", "operation": operation, "input": payload},
    )
    while True:
        event = runtime.receive(request_id, timeout)
        if event.get("type") != "plugin_event":
            raise UpgradeSmokeFailure("invalid_runtime_output")
        if event.get("status") == "error":
            code = event.get("code")
            raise UpgradeSmokeFailure(code if isinstance(code, str) else "history_error")
        if event.get("status") == "result":
            data = event.get("data")
            if not isinstance(data, dict):
                raise UpgradeSmokeFailure("invalid_history_result")
            return data


def _verify_database(database: Path, legacy_id: str, new_id: str) -> tuple[int, int]:
    backup = database.with_name(database.name + ".migration-v0.bak")
    if not backup.is_file():
        raise UpgradeSmokeFailure("migration_backup_missing")
    current = sqlite3.connect(database)
    try:
        current_version = current.execute("PRAGMA user_version").fetchone()[0]
        layout = current.execute(
            "SELECT value FROM schema_meta WHERE key = 'index_layout_version'"
        ).fetchone()
        legacy_count = current.execute(
            "SELECT count(*) FROM history_records WHERE id = ?", (legacy_id,)
        ).fetchone()[0]
        new_count = current.execute(
            "SELECT count(*) FROM history_records WHERE id = ?", (new_id,)
        ).fetchone()[0]
    finally:
        current.close()
    old = sqlite3.connect(backup)
    try:
        backup_version = old.execute("PRAGMA user_version").fetchone()[0]
        marker = old.execute("SELECT value FROM legacy_marker").fetchone()[0]
    finally:
        old.close()
    if current_version != 1 or not layout or layout[0] != "3":
        raise UpgradeSmokeFailure("current_schema_not_migrated")
    if legacy_count != 1 or new_count != 1:
        raise UpgradeSmokeFailure("migrated_records_missing")
    if backup_version != 0 or marker != "preserved":
        raise UpgradeSmokeFailure("migration_backup_invalid")
    return current_version, backup_version


def _parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(description="Run the packaged history migration smoke gate.")
    parser.add_argument(
        "--runtime",
        default=str(ROOT / "apps" / "tauri-host" / "src-tauri" / "resources" / "runtime" / "reflex-runtime.exe"),
        help="Path to a packaged Reflex Runtime executable.",
    )
    parser.add_argument("--provider", default="minimax")
    parser.add_argument("--model", default="MiniMax-M2.7-highspeed")
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--keep-work-root", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except UpgradeSmokeFailure as error:
        _emit(_record("unknown", "unknown", "tool_error", error_code=error.code))
        return 2
    if (
        not PROVIDER_ID_PATTERN.fullmatch(args.provider)
        or not MODEL_ID_PATTERN.fullmatch(args.model)
        or not 5.0 <= args.timeout_seconds <= 120.0
    ):
        _emit(_record(args.provider, args.model, "tool_error", error_code="invalid_arguments"))
        return 2
    runtime_path = Path(args.runtime).resolve()
    root = Path(tempfile.mkdtemp(prefix="reflex-history-upgrade-"))
    runtime: RuntimeProcess | None = None
    try:
        if not runtime_path.is_file():
            raise UpgradeSmokeFailure("runtime_unavailable")
        database, legacy_id = _create_legacy_database(root)
        runtime = RuntimeProcess([str(runtime_path)], cwd=ROOT)
        _configure_runtime(runtime, database, args.provider, args.model, args.timeout_seconds)
        new_id = _run_optimization(runtime, args.provider, args.model, args.timeout_seconds)
        detail = _plugin_call(
            runtime,
            "upgrade-detail",
            "detail",
            {"id": legacy_id},
            args.timeout_seconds,
        )
        listed = _plugin_call(
            runtime,
            "upgrade-list",
            "list",
            {"page_size": 50, "sort": "created_at", "direction": "desc"},
            args.timeout_seconds,
        )
        if detail.get("record", {}).get("id") != legacy_id:
            raise UpgradeSmokeFailure("legacy_detail_missing")
        if detail["record"].get("input") != LEGACY_INPUT or detail["record"].get("output") != LEGACY_OUTPUT:
            raise UpgradeSmokeFailure("legacy_detail_invalid")
        items = listed.get("items")
        if not isinstance(items, list) or not any(item.get("id") == legacy_id for item in items):
            raise UpgradeSmokeFailure("legacy_list_missing")
        if not any(item.get("id") == new_id for item in items):
            raise UpgradeSmokeFailure("new_record_missing")
        current_version, backup_version = _verify_database(database, legacy_id, new_id)
        _emit(
            _record(
                args.provider,
                args.model,
                "success",
                legacy_schema=0,
                current_schema=current_version,
                backup_schema=backup_version,
                legacy_detail_read=True,
                new_record_saved=True,
                list_read=True,
            ),
            work_root=root if args.keep_work_root else None,
        )
        return 0
    except UpgradeSmokeFailure as error:
        _emit(
            _record(args.provider, args.model, "tool_error", error_code=error.code),
            work_root=root if args.keep_work_root else None,
        )
        return 2
    except Exception:
        _emit(
            _record(args.provider, args.model, "tool_error", error_code="unexpected_failure"),
            work_root=root if args.keep_work_root else None,
        )
        return 2
    finally:
        if runtime is not None:
            runtime.close()
        if not args.keep_work_root:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
