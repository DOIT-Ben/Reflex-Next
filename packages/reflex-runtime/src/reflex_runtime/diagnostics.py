"""Bounded, fail-open structured diagnostics for the Runtime sidecar."""

from __future__ import annotations

import json
import math
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit, urlunsplit

from reflex_core.safety import redact_sensitive

_REDACTED: Final = "[REDACTED]"
_DEFAULT_MAX_FILE_BYTES: Final = 1_000_000
_DEFAULT_MAX_FILES: Final = 3
_DEFAULT_MAX_TOTAL_BYTES: Final = 3_000_000
_HARD_MAX_FILE_BYTES: Final = 10_000_000
_HARD_MAX_FILES: Final = 10
_HARD_MAX_TOTAL_BYTES: Final = 50_000_000
_MAX_STRING_CHARS: Final = 2_048
_MAX_EVENT_CHARS: Final = 128
_EVENT_PATTERN: Final = re.compile(r"[a-z][a-z0-9_.-]{0,127}")

_ALLOWED_FIELDS: Final = frozenset(
    {
        "level",
        "component",
        "code",
        "request_id",
        "provider_id",
        "model",
        "phase",
        "status",
        "error_type",
        "duration_ms",
        "chunk_count",
        "cancel_latency_ms",
        "url",
        "message",
    }
)
_URL_PATTERN: Final = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_SENSITIVE_ASSIGNMENT_PATTERN: Final = re.compile(
    r"(?i)((?<![A-Za-z0-9])(?:api[_-]?key|access[_-]?key|client[_-]?secret|"
    r"token|secret|key|authorization)\s*[:=]\s*)"
    r"(?:(?:bearer|basic)\s+)?[^\s,;]+"
)


class DiagnosticWriter:
    """Write allowlisted JSONL diagnostics without affecting the main flow.

    Diagnostics are disabled unless ``enabled=True`` is supplied. Runtime
    integration remains an explicit responsibility of a later phase.
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        enabled: bool = False,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        max_files: int = _DEFAULT_MAX_FILES,
        max_total_bytes: int = _DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self._validate_limits(max_file_bytes, max_files, max_total_bytes)
        self._directory = Path(directory)
        self._active_path = self._directory / "runtime-diagnostics.jsonl"
        self._enabled = enabled is True
        self._max_file_bytes = max_file_bytes
        self._max_files = max_files
        self._max_total_bytes = max_total_bytes
        self._lock = threading.RLock()
        self._closed = False
        self._available = False

        if self._enabled:
            with self._lock:
                self._available = self._prepare_storage_locked()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        with self._lock:
            return self._available and not self._closed

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def emit(self, event: str, **fields: object) -> bool:
        """Append one safe record, returning ``False`` on disable or failure."""

        with self._lock:
            if not self._enabled or self._closed or not self._available:
                return False
            try:
                record = self._build_record(event, fields)
                if record is None:
                    return False
                payload = (
                    json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8")
                if len(payload) > self._max_file_bytes:
                    return False

                current_size = self._file_size(self._active_path)
                if current_size and current_size + len(payload) > self._max_file_bytes:
                    self._rotate_locked()
                if not self._prune_total_locked(len(payload)):
                    return False

                created = not self._active_path.exists()
                with self._active_path.open("ab") as stream:
                    if stream.write(payload) != len(payload):
                        raise OSError("diagnostic write was incomplete")
                if created:
                    self._restrict_permissions(self._active_path)
                return True
            except (OSError, UnicodeError, ValueError, TypeError):
                self._available = False
                return False

    def close(self) -> None:
        """Stop future writes. The operation is idempotent and never raises."""

        with self._lock:
            self._closed = True
            self._available = False

    def __enter__(self) -> DiagnosticWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _validate_limits(
        max_file_bytes: int, max_files: int, max_total_bytes: int
    ) -> None:
        limits = (
            ("max_file_bytes", max_file_bytes, _HARD_MAX_FILE_BYTES),
            ("max_files", max_files, _HARD_MAX_FILES),
            ("max_total_bytes", max_total_bytes, _HARD_MAX_TOTAL_BYTES),
        )
        for name, value, maximum in limits:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 1 or value > maximum:
                raise ValueError(f"{name} is outside the supported range")
        if max_total_bytes < max_file_bytes:
            raise ValueError("max_total_bytes must cover at least one file")

    def _prepare_storage_locked(self) -> bool:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            if self._active_path.exists() and (
                self._file_size(self._active_path) > self._max_file_bytes
                or not self._is_valid_jsonl(self._active_path)
            ):
                self._rotate_locked()
            return self._prune_total_locked(0)
        except (OSError, UnicodeError, ValueError, TypeError):
            return False

    def _build_record(
        self, event: object, fields: dict[str, object]
    ) -> dict[str, object] | None:
        if not isinstance(event, str):
            return None
        safe_event = self._safe_string(event, _MAX_EVENT_CHARS).strip()
        if _EVENT_PATTERN.fullmatch(safe_event) is None:
            return None

        record: dict[str, object] = {
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "event": safe_event,
        }
        for name in _ALLOWED_FIELDS:
            if name not in fields:
                continue
            value = fields[name]
            if name == "url":
                if isinstance(value, str):
                    record[name] = self._safe_url(value)
                continue
            if isinstance(value, str):
                record[name] = self._safe_string(value)
            elif isinstance(value, bool):
                record[name] = value
            elif isinstance(value, int):
                record[name] = value
            elif isinstance(value, float) and math.isfinite(value):
                record[name] = value
        return record

    @staticmethod
    def _safe_string(value: str, limit: int = _MAX_STRING_CHARS) -> str:
        redacted = _SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", value)
        redacted = redact_sensitive(redacted)
        redacted = _URL_PATTERN.sub(
            lambda match: DiagnosticWriter._safe_url(match.group(0)), redacted
        )
        return redacted[:limit]

    @staticmethod
    def _safe_url(value: str) -> str:
        try:
            parsed = urlsplit(value)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
                return _REDACTED
            authority = parsed.netloc.rsplit("@", 1)[-1]
            path = redact_sensitive(parsed.path)[:_MAX_STRING_CHARS]
            return urlunsplit((parsed.scheme.lower(), authority, path, "", ""))
        except (TypeError, ValueError, UnicodeError):
            return _REDACTED

    def _rotate_locked(self) -> None:
        oldest = self._backup_path(self._max_files - 1)
        if oldest is not None:
            oldest.unlink(missing_ok=True)
        for index in range(self._max_files - 2, 0, -1):
            source = self._backup_path(index)
            target = self._backup_path(index + 1)
            if source is not None and target is not None and source.exists():
                source.replace(target)
        first_backup = self._backup_path(1)
        if self._active_path.exists():
            if first_backup is None:
                self._active_path.unlink()
            else:
                self._active_path.replace(first_backup)

    def _prune_total_locked(self, incoming_bytes: int) -> bool:
        paths = [self._active_path]
        paths.extend(
            path
            for index in range(1, self._max_files)
            if (path := self._backup_path(index)) is not None
        )
        total = sum(self._file_size(path) for path in paths)
        for index in range(self._max_files - 1, 0, -1):
            if total + incoming_bytes <= self._max_total_bytes:
                break
            path = self._backup_path(index)
            if path is not None and path.exists():
                size = self._file_size(path)
                path.unlink()
                total -= size
        return total + incoming_bytes <= self._max_total_bytes

    def _backup_path(self, index: int) -> Path | None:
        if index < 1 or index >= self._max_files:
            return None
        return self._directory / f"runtime-diagnostics.{index}.jsonl"

    @staticmethod
    def _file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except FileNotFoundError:
            return 0

    @staticmethod
    def _is_valid_jsonl(path: Path) -> bool:
        try:
            content = path.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.strip() and not isinstance(json.loads(line), dict):
                    return False
            return True
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return False

    @staticmethod
    def _restrict_permissions(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            # ACL handling belongs to the host; a chmod failure must not break
            # diagnostics after the file was written successfully.
            pass


__all__ = ["DiagnosticWriter"]
