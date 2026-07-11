"""History plugin descriptor and side-effect-free factory."""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from reflex_core import OperationCancelled
from reflex_core.safety import redact_for_history

from .contract import (
    HistoryListRequest,
    HistoryPluginError,
    HistorySaveSnapshot,
    HistoryServiceSnapshot,
    parse_clear_payload,
    parse_backup_id_payload,
    parse_export_payload,
    parse_id_payload,
    parse_rate_payload,
    parse_rotate_payload,
)
from .export import stream_records
from .maintenance import MaintenanceCoordinator
from .repository import HistoryRepository

SQLITE_BUSY_CODES = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
SQLITE_CORRUPTION_CODES = frozenset({sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB})
RECOVERY_ALLOWED_OPERATIONS = frozenset(
    {"list", "detail", "export", "backups", "scan", "repair", "restore"}
)
RECOVERY_MARKER_BODY = b"recovery-required\n"


@dataclass(frozen=True)
class HistoryPluginDescriptor:
    plugin_id: str = "history-sqlite"
    display_name: str = "History"
    version: str = "1"
    kind: str = "storage"
    permissions: tuple[str, ...] = ("storage_read", "storage_write")
    operations: tuple[str, ...] = (
        "save",
        "list",
        "detail",
        "rate",
        "delete",
        "clear",
        "export",
        "scan",
        "repair",
        "backups",
        "restore",
        "rotate",
    )
    public_operations: tuple[str, ...] = (
        "list",
        "detail",
        "rate",
        "backups",
        "scan",
    )


class HistorySqlitePlugin:
    descriptor = HistoryPluginDescriptor()

    def __init__(self) -> None:
        self._schema_lock = RLock()
        self._recovery_paths: set[Path] = set()
        self._maintenance = MaintenanceCoordinator()

    def invoke(
        self,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
    ) -> Any:
        if operation not in self.descriptor.operations:
            raise HistoryPluginError("history_operation_unavailable")
        cancellation.raise_if_cancelled()
        service_snapshot: HistoryServiceSnapshot | None = None
        try:
            service_snapshot = HistoryServiceSnapshot.from_services(services)
            with self._schema_lock:
                in_recovery = (
                    service_snapshot.database_path in self._recovery_paths
                    or _recovery_marker(service_snapshot.database_path).is_file()
                )
                if in_recovery:
                    self._recovery_paths.add(service_snapshot.database_path)
            if in_recovery and operation not in RECOVERY_ALLOWED_OPERATIONS:
                raise HistoryPluginError("history_recovery_required")
            repository = self._repository(service_snapshot)
            if operation == "save":
                if not service_snapshot.keys:
                    raise HistoryPluginError("history_key_unavailable")
                if not service_snapshot.history_enabled or service_snapshot.privacy_mode:
                    raise HistoryPluginError("history_read_only")
                snapshot = HistorySaveSnapshot.from_payload(payload)
                snapshot = HistorySaveSnapshot(
                    **{
                        **snapshot.__dict__,
                        "input": redact_for_history(
                            snapshot.input, service_snapshot.history_redaction
                        ),
                        "output": redact_for_history(
                            snapshot.output, service_snapshot.history_redaction
                        ),
                    }
                )
                with self._maintenance.write():
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    return repository.save(snapshot, cancellation)
            if operation == "list":
                with self._maintenance.read():
                    repository.recover_interrupted_replace()
                    return repository.list(HistoryListRequest.from_payload(payload), cancellation)
            if operation == "detail":
                with self._maintenance.read():
                    repository.recover_interrupted_replace()
                    return repository.detail(parse_id_payload(payload), cancellation)
            if operation == "rate":
                record_id, rating = parse_rate_payload(payload)
                cancellation.raise_if_cancelled()
                with self._maintenance.write():
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    return repository.rate(record_id, rating, cancellation)
            if operation == "delete":
                record_id = parse_id_payload(payload)
                cancellation.raise_if_cancelled()
                with self._maintenance.write():
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    return repository.delete(record_id, cancellation)
            if operation == "clear":
                parse_clear_payload(payload)
                cancellation.raise_if_cancelled()
                with self._maintenance.write():
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    return repository.clear(cancellation)
            if operation == "export":
                format_name, request = parse_export_payload(payload)
                return self._stream_export(
                    repository,
                    request,
                    format_name,
                    service_snapshot.history_redaction,
                    cancellation,
                )
            if operation == "scan":
                if not isinstance(payload, dict) or payload:
                    raise HistoryPluginError("history_payload_invalid")
                with self._maintenance.read():
                    repository.recover_interrupted_replace()
                    return repository.scan(cancellation)
            if operation == "backups":
                if not isinstance(payload, dict) or payload:
                    raise HistoryPluginError("history_payload_invalid")
                with self._maintenance.read():
                    repository.recover_interrupted_replace()
                    return repository.backups(cancellation)
            if operation == "repair":
                if not isinstance(payload, dict) or payload:
                    raise HistoryPluginError("history_payload_invalid")
                self._maintenance.begin(cancellation)
                try:
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    result = repository.repair(cancellation)
                    self._clear_recovery(service_snapshot.database_path)
                    return result
                finally:
                    self._maintenance.end()
            if operation == "restore":
                backup_id = parse_backup_id_payload(payload)
                self._maintenance.begin(cancellation, block_reads=True)
                try:
                    repository.recover_interrupted_replace()
                    if repository.has_rotation_checkpoint():
                        raise HistoryPluginError("history_busy")
                    result = repository.restore(backup_id, cancellation)
                    self._clear_recovery(service_snapshot.database_path)
                    return result
                finally:
                    self._maintenance.end()
            if operation == "rotate":
                action, target_version, batch_size = parse_rotate_payload(payload)
                target_number = int(target_version[1:])
                if action == "resume":
                    self._maintenance.begin(cancellation)
                    try:
                        repository.recover_interrupted_replace()
                        return repository.resume_rotation(target_number)
                    finally:
                        self._maintenance.end()
                if action == "prepare":
                    self._maintenance.begin(cancellation, block_reads=True)
                    try:
                        repository.recover_interrupted_replace()
                        result = repository.prepare_rotation(target_number, batch_size, cancellation)
                    except BaseException:
                        self._maintenance.end()
                        raise
                    self._maintenance.allow_reads()
                    return result
                if action == "finalize":
                    repository.recover_interrupted_replace()
                    result = repository.finalize_rotation(target_number)
                    self._maintenance.end()
                    return result
                self._maintenance.block_reads(cancellation)
                try:
                    repository.recover_interrupted_replace()
                    return repository.rollback_rotation(target_number, cancellation)
                finally:
                    self._maintenance.end()
        except HistoryPluginError as error:
            if error.code == "history_recovery_required" and service_snapshot is not None:
                self._mark_recovery(service_snapshot.database_path)
            raise
        except OperationCancelled:
            raise
        except sqlite3.Error as error:
            base_code = _sqlite_base_error_code(error)
            if base_code in SQLITE_CORRUPTION_CODES and service_snapshot is not None:
                self._mark_recovery(service_snapshot.database_path)
            safe_code = (
                "history_storage_busy"
                if base_code in SQLITE_BUSY_CODES
                else "history_storage_failed"
            )
            raise HistoryPluginError(safe_code) from None
        except Exception as error:
            raise HistoryPluginError("history_operation_failed") from error
        raise HistoryPluginError("history_operation_unavailable")

    def _repository(self, services: HistoryServiceSnapshot) -> HistoryRepository:
        return HistoryRepository(services, schema_lock=self._schema_lock)

    def _stream_export(
        self,
        repository: HistoryRepository,
        request: HistoryListRequest,
        format_name: str,
        redaction: str,
        cancellation: Any,
    ) -> Any:
        with self._maintenance.read():
            repository.recover_interrupted_replace()
            yield from stream_records(
                repository.export_records(request, cancellation),
                format_name,
                redaction,
                cancellation,
            )

    def _mark_recovery(self, database_path: Path) -> None:
        with self._schema_lock:
            self._recovery_paths.add(database_path)
            marker = _recovery_marker(database_path)
            marker.parent.mkdir(parents=True, exist_ok=True)
            temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(RECOVERY_MARKER_BODY)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, marker)
            finally:
                temporary.unlink(missing_ok=True)

    def _clear_recovery(self, database_path: Path) -> None:
        with self._schema_lock:
            _recovery_marker(database_path).unlink(missing_ok=True)
            self._recovery_paths.discard(database_path)


def _sqlite_base_error_code(error: sqlite3.Error) -> int | None:
    code = getattr(error, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None
    return code & 0xFF


def _recovery_marker(database_path: Path) -> Path:
    return database_path.with_name(f".{database_path.name}.recovery-required")


def plugin() -> HistorySqlitePlugin:
    return HistorySqlitePlugin()
