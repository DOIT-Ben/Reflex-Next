"""History plugin descriptor and side-effect-free factory."""

from __future__ import annotations

import sqlite3
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
    parse_id_payload,
    parse_rate_payload,
)
from .repository import HistoryRepository

SQLITE_BUSY_CODES = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED})
SQLITE_CORRUPTION_CODES = frozenset({sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB})


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
        if operation in {"export", "scan", "repair", "backups", "restore", "rotate"}:
            raise HistoryPluginError("history_operation_unavailable")
        service_snapshot: HistoryServiceSnapshot | None = None
        try:
            service_snapshot = HistoryServiceSnapshot.from_services(services)
            with self._schema_lock:
                in_recovery = service_snapshot.database_path in self._recovery_paths
            if in_recovery and operation not in {"list", "detail"}:
                raise HistoryPluginError("history_recovery_required")
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
                return self._repository(service_snapshot).save(snapshot, cancellation)
            repository = self._repository(service_snapshot)
            if operation == "list":
                return repository.list(HistoryListRequest.from_payload(payload), cancellation)
            if operation == "detail":
                return repository.detail(parse_id_payload(payload), cancellation)
            if operation == "rate":
                record_id, rating = parse_rate_payload(payload)
                cancellation.raise_if_cancelled()
                return repository.rate(record_id, rating, cancellation)
            if operation == "delete":
                record_id = parse_id_payload(payload)
                cancellation.raise_if_cancelled()
                return repository.delete(record_id, cancellation)
            if operation == "clear":
                parse_clear_payload(payload)
                cancellation.raise_if_cancelled()
                return repository.clear(cancellation)
        except HistoryPluginError as error:
            if error.code == "history_recovery_required" and service_snapshot is not None:
                with self._schema_lock:
                    self._recovery_paths.add(service_snapshot.database_path)
            raise
        except OperationCancelled:
            raise
        except sqlite3.Error as error:
            base_code = _sqlite_base_error_code(error)
            if base_code in SQLITE_CORRUPTION_CODES and service_snapshot is not None:
                with self._schema_lock:
                    self._recovery_paths.add(service_snapshot.database_path)
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


def _sqlite_base_error_code(error: sqlite3.Error) -> int | None:
    code = getattr(error, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None
    return code & 0xFF


def plugin() -> HistorySqlitePlugin:
    return HistorySqlitePlugin()
