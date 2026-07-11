"""SQLite persistence with encrypted bodies and metadata-only indexes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from cryptography.exceptions import InvalidTag

from .codec import EncryptedField, HistoryCodec, HistoryMetadata
from .contract import (
    HistoryListRequest,
    HistoryPluginError,
    HistorySaveSnapshot,
    HistoryServiceSnapshot,
)

SCHEMA_VERSION = 1
CORRUPTED_PLACEHOLDER = "[CORRUPTED]"
SUMMARY_COLUMNS = (
    "id, created_at, mode, style, scene, provider, model, elapsed_ms, "
    "status, rating, tags_json"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS history_records(
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    input_nonce BLOB NOT NULL,
    input_ciphertext BLOB NOT NULL,
    output_nonce BLOB NOT NULL,
    output_ciphertext BLOB NOT NULL,
    key_version INTEGER NOT NULL,
    mode TEXT NOT NULL,
    style TEXT NOT NULL,
    scene TEXT,
    provider TEXT NOT NULL,
    model TEXT,
    elapsed_ms INTEGER,
    status TEXT NOT NULL,
    rating INTEGER,
    tags_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS schema_meta(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repair_quarantine(
    id TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    quarantined_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rotation_checkpoint(
    id INTEGER PRIMARY KEY CHECK(id = 1),
    rotation_id TEXT NOT NULL,
    source_version INTEGER NOT NULL,
    target_version INTEGER NOT NULL,
    phase TEXT NOT NULL,
    backup_id TEXT,
    high_water_mark TEXT,
    last_record_id TEXT
);
CREATE INDEX IF NOT EXISTS history_records_created_at_idx ON history_records(created_at);
CREATE INDEX IF NOT EXISTS history_records_provider_idx ON history_records(provider);
CREATE INDEX IF NOT EXISTS history_records_scene_idx ON history_records(scene);
CREATE INDEX IF NOT EXISTS history_records_style_idx ON history_records(style);
CREATE INDEX IF NOT EXISTS history_records_rating_idx ON history_records(rating);
CREATE INDEX IF NOT EXISTS history_records_status_idx ON history_records(status);
"""


class HistoryRepository:
    def __init__(
        self,
        services: HistoryServiceSnapshot,
        *,
        schema_lock: RLock,
    ) -> None:
        self._services = services
        self._path = services.database_path
        self._keys = services.decoded_keys()
        self._codec = HistoryCodec(self._keys)
        self._active_key_version = max(self._keys)
        self._schema_lock = schema_lock

    @property
    def exists(self) -> bool:
        return self._path.is_file()

    def save(self, snapshot: HistorySaveSnapshot, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        metadata = self._metadata(snapshot)
        input_field = self._codec.encrypt(
            snapshot.input, metadata, self._active_key_version, "input"
        )
        output_field = self._codec.encrypt(
            snapshot.output, metadata, self._active_key_version, "output"
        )
        cancellation.raise_if_cancelled()
        with self._connection(create=True, writable=True) as connection:
            cancellation.raise_if_cancelled()
            try:
                connection.execute(
                    """
                    INSERT INTO history_records(
                        id, created_at, input_nonce, input_ciphertext,
                        output_nonce, output_ciphertext, key_version,
                        mode, style, scene, provider, model, elapsed_ms,
                        status, rating, tags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        snapshot.id,
                        snapshot.created_at,
                        sqlite3.Binary(input_field.nonce),
                        sqlite3.Binary(input_field.ciphertext),
                        sqlite3.Binary(output_field.nonce),
                        sqlite3.Binary(output_field.ciphertext),
                        self._active_key_version,
                        snapshot.mode,
                        snapshot.style,
                        snapshot.scene,
                        snapshot.provider,
                        snapshot.model,
                        snapshot.elapsed_ms,
                        snapshot.status,
                        json.dumps(snapshot.tags, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                cancellation.raise_if_cancelled()
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise HistoryPluginError("history_conflict") from error
            except Exception:
                connection.rollback()
                raise
        return {"id": snapshot.id}

    def list(self, request: HistoryListRequest, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if not self.exists:
            return {"items": [], "next_cursor": None}
        cursor = self._decode_cursor(request)
        if request.keyword is None:
            rows = self._select_rows(request, cursor, request.page_size + 1)
            cancellation.raise_if_cancelled()
            return self._page(rows, request)
        return self._search(request, cursor, cancellation)

    def detail(self, record_id: str, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        with self._connection(create=False, writable=False) as connection:
            row = connection.execute(
                """
                SELECT id, created_at, input_nonce, input_ciphertext,
                       output_nonce, output_ciphertext, key_version,
                       mode, style, scene, provider, model, elapsed_ms,
                       status, rating, tags_json
                FROM history_records WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            raise HistoryPluginError("history_not_found")
        return {"record": self._detail_row(row)}

    def rate(
        self, record_id: str, rating: int | None, cancellation: Any
    ) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        with self._connection(create=False, writable=True) as connection:
            cancellation.raise_if_cancelled()
            try:
                cursor = connection.execute(
                    "UPDATE history_records SET rating = ? WHERE id = ?",
                    (rating, record_id),
                )
                if cursor.rowcount != 1:
                    raise HistoryPluginError("history_not_found")
                cancellation.raise_if_cancelled()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"id": record_id, "rating": rating}

    def delete(self, record_id: str, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        with self._connection(create=False, writable=True) as connection:
            cancellation.raise_if_cancelled()
            try:
                cursor = connection.execute(
                    "DELETE FROM history_records WHERE id = ?", (record_id,)
                )
                if cursor.rowcount != 1:
                    raise HistoryPluginError("history_not_found")
                cancellation.raise_if_cancelled()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"deleted": 1}

    def clear(self, cancellation: Any) -> dict[str, Any]:
        cancellation.raise_if_cancelled()
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        with self._connection(create=False, writable=True) as connection:
            cancellation.raise_if_cancelled()
            try:
                cursor = connection.execute("DELETE FROM history_records")
                if cursor.rowcount < 1:
                    raise HistoryPluginError("history_not_found")
                cancellation.raise_if_cancelled()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return {"deleted": cursor.rowcount}

    def _search(
        self,
        request: HistoryListRequest,
        cursor: dict[str, Any] | None,
        cancellation: Any,
    ) -> dict[str, Any]:
        matches: list[sqlite3.Row] = []
        scan_cursor = cursor
        needle = request.keyword.casefold()
        while len(matches) <= request.page_size:
            cancellation.raise_if_cancelled()
            rows = self._select_rows(request, scan_cursor, 100)
            if not rows:
                break
            for row in rows:
                cancellation.raise_if_cancelled()
                try:
                    metadata = self._metadata_from_summary(row)
                    input_text = self._codec.decrypt(
                        EncryptedField(row["input_nonce"], row["input_ciphertext"]),
                        metadata,
                        row["key_version"],
                        "input",
                    )
                    output_text = self._codec.decrypt(
                        EncryptedField(row["output_nonce"], row["output_ciphertext"]),
                        metadata,
                        row["key_version"],
                        "output",
                    )
                except (InvalidTag, ValueError):
                    continue
                if needle in input_text.casefold() or needle in output_text.casefold():
                    matches.append(row)
                    if len(matches) > request.page_size:
                        break
            scan_cursor = self._cursor_values(rows[-1], request)
            if len(rows) < 100:
                break
        return self._page(matches, request)

    def _select_rows(
        self,
        request: HistoryListRequest,
        cursor: dict[str, Any] | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        clauses: list[str] = []
        parameters: list[Any] = []
        mapping = {
            "provider": "provider = ?",
            "scene": "scene = ?",
            "style": "style = ?",
            "date_from": "created_at >= ?",
            "date_to": "created_at <= ?",
            "rating": "rating = ?",
        }
        for name, value in request.filters.items():
            clauses.append(mapping[name])
            parameters.append(value)
        if cursor is not None:
            cursor_clause, cursor_parameters = self._cursor_clause(request, cursor)
            clauses.append(cursor_clause)
            parameters.extend(cursor_parameters)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "ASC" if request.direction == "asc" else "DESC"
        if request.sort == "created_at":
            order = f"created_at {direction}, id {direction}"
        else:
            order = f"rating IS NULL ASC, rating {direction}, id {direction}"
        parameters.append(limit)
        with self._connection(create=False, writable=False) as connection:
            return connection.execute(
                f"""
                SELECT {SUMMARY_COLUMNS}, input_nonce, input_ciphertext,
                       output_nonce, output_ciphertext, key_version
                FROM history_records{where}
                ORDER BY {order} LIMIT ?
                """,
                parameters,
            ).fetchall()

    def _cursor_clause(
        self, request: HistoryListRequest, cursor: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        operator = ">" if request.direction == "asc" else "<"
        value = cursor["value"]
        record_id = cursor["id"]
        if request.sort == "created_at":
            return (
                f"(created_at {operator} ? OR (created_at = ? AND id {operator} ?))",
                [value, value, record_id],
            )
        if value is None:
            return f"(rating IS NULL AND id {operator} ?)", [record_id]
        return (
            f"(rating {operator} ? OR (rating = ? AND id {operator} ?) OR rating IS NULL)",
            [value, value, record_id],
        )

    def _page(
        self, rows: list[sqlite3.Row], request: HistoryListRequest
    ) -> dict[str, Any]:
        has_more = len(rows) > request.page_size
        selected = rows[: request.page_size]
        cursor = (
            self._encode_cursor(self._cursor_values(selected[-1], request), request)
            if has_more and selected
            else None
        )
        return {
            "items": [self._summary(row) for row in selected],
            "next_cursor": cursor,
        }

    def _cursor_values(
        self, row: sqlite3.Row, request: HistoryListRequest
    ) -> dict[str, Any]:
        return {"value": row[request.sort], "id": row["id"]}

    def _encode_cursor(
        self, values: dict[str, Any], request: HistoryListRequest
    ) -> str:
        payload = {
            "v": 1,
            "sort": request.sort,
            "direction": request.direction,
            "value": values["value"],
            "id": values["id"],
            "filters": self._query_hash(dict(request.filters)),
            "keyword": self._query_hash(request.keyword),
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._cursor_key(), body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode("ascii")

    def _decode_cursor(self, request: HistoryListRequest) -> dict[str, Any] | None:
        if request.cursor is None:
            return None
        try:
            encoded = request.cursor.encode("ascii")
            raw = base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))
            body, signature = raw[:-32], raw[-32:]
            if len(signature) != 32 or not hmac.compare_digest(
                signature, hmac.new(self._cursor_key(), body, hashlib.sha256).digest()
            ):
                raise ValueError
            payload = json.loads(body)
            expected = {
                "v",
                "sort",
                "direction",
                "value",
                "id",
                "filters",
                "keyword",
            }
            if (
                not isinstance(payload, dict)
                or set(payload) != expected
                or payload["v"] != 1
                or payload["sort"] != request.sort
                or payload["direction"] != request.direction
                or payload["filters"] != self._query_hash(dict(request.filters))
                or payload["keyword"] != self._query_hash(request.keyword)
                or not isinstance(payload["id"], str)
                or (
                    request.sort == "created_at"
                    and not isinstance(payload["value"], str)
                )
                or (
                    request.sort == "rating"
                    and payload["value"] is not None
                    and not isinstance(payload["value"], int)
                )
            ):
                raise ValueError
            return {"value": payload["value"], "id": payload["id"]}
        except (UnicodeEncodeError, ValueError, json.JSONDecodeError, TypeError):
            raise HistoryPluginError("history_cursor_invalid") from None

    def _cursor_key(self) -> bytes:
        return hmac.new(
            self._keys[self._active_key_version],
            b"reflex-history-cursor-v1",
            hashlib.sha256,
        ).digest()

    @staticmethod
    def _query_hash(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()

    @contextmanager
    def _connection(
        self, *, create: bool, writable: bool
    ) -> Iterator[sqlite3.Connection]:
        if create:
            with self._schema_lock:
                if not self.exists:
                    self._path.parent.mkdir(parents=True, exist_ok=True)
                connection = self._open_connection(read_only=False)
                try:
                    self._ensure_schema(connection)
                except Exception:
                    connection.close()
                    raise
        else:
            if not self.exists:
                raise HistoryPluginError("history_not_found")
            connection = self._open_connection(read_only=not writable)
        try:
            yield connection
        finally:
            connection.close()

    def _open_connection(self, *, read_only: bool) -> sqlite3.Connection:
        if read_only:
            connection = sqlite3.connect(
                f"file:{self._path.as_posix()}?mode=ro",
                uri=True,
                timeout=5,
            )
        else:
            connection = sqlite3.connect(self._path, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            if not read_only:
                connection.execute("PRAGMA journal_mode = WAL")
            return connection
        except Exception:
            connection.close()
            raise

    def _ensure_schema(self, connection: sqlite3.Connection) -> None:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise HistoryPluginError("history_recovery_required")
        has_tables = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
        ).fetchone()
        if current < SCHEMA_VERSION and has_tables:
            self._migration_backup(connection, current)
        try:
            connection.executescript("BEGIN IMMEDIATE;" + SCHEMA_SQL)
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception as error:
            connection.rollback()
            raise HistoryPluginError("history_recovery_required") from error

    def _migration_backup(self, connection: sqlite3.Connection, version: int) -> None:
        backup_path = self._path.with_name(
            f"{self._path.name}.migration-v{version}.bak"
        )
        try:
            backup = sqlite3.connect(backup_path)
            try:
                connection.backup(backup)
            finally:
                backup.close()
        except Exception as error:
            try:
                backup_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise HistoryPluginError("history_recovery_required") from error

    @staticmethod
    def _metadata(snapshot: HistorySaveSnapshot) -> HistoryMetadata:
        return HistoryMetadata(
            id=snapshot.id,
            created_at=snapshot.created_at,
            mode=snapshot.mode,
            style=snapshot.style,
            scene=snapshot.scene,
            provider=snapshot.provider,
            model=snapshot.model,
            elapsed_ms=snapshot.elapsed_ms,
            status=snapshot.status,
        )

    @staticmethod
    def _metadata_from_summary(row: sqlite3.Row) -> HistoryMetadata:
        return HistoryMetadata(
            id=row["id"],
            created_at=row["created_at"],
            mode=row["mode"],
            style=row["style"],
            scene=row["scene"],
            provider=row["provider"],
            model=row["model"],
            elapsed_ms=row["elapsed_ms"],
            status=row["status"],
        )

    @staticmethod
    def _tags(value: str) -> list[str]:
        try:
            tags = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return tags if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags) else []

    def _summary(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "style": row["style"],
            "scene": row["scene"],
            "provider": row["provider"],
            "model": row["model"],
            "elapsed_ms": row["elapsed_ms"],
            "status": row["status"],
            "rating": row["rating"],
            "tags": self._tags(row["tags_json"]),
        }

    def _detail_row(self, row: sqlite3.Row) -> dict[str, Any]:
        summary = self._summary(row)
        metadata = self._metadata_from_summary(row)
        try:
            input_text = self._codec.decrypt(
                EncryptedField(row["input_nonce"], row["input_ciphertext"]),
                metadata,
                row["key_version"],
                "input",
            )
            output_text = self._codec.decrypt(
                EncryptedField(row["output_nonce"], row["output_ciphertext"]),
                metadata,
                row["key_version"],
                "output",
            )
        except (InvalidTag, ValueError):
            summary.update(
                {
                    "input": CORRUPTED_PLACEHOLDER,
                    "output": CORRUPTED_PLACEHOLDER,
                    "status": "corrupted",
                    "corrupted": True,
                }
            )
            return summary
        summary.update(
            {
                "input": input_text,
                "output": output_text,
                "corrupted": False,
            }
        )
        return summary
