"""SQLite persistence with encrypted bodies and metadata-only indexes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

from cryptography.exceptions import InvalidTag
from reflex_core import CancellationToken, OperationCancelled

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

INDEX_DEFINITIONS = (
    ("history_records_created_at_idx", "CREATE INDEX history_records_created_at_idx ON history_records(created_at)"),
    ("history_records_provider_idx", "CREATE INDEX history_records_provider_idx ON history_records(provider)"),
    ("history_records_scene_idx", "CREATE INDEX history_records_scene_idx ON history_records(scene)"),
    ("history_records_style_idx", "CREATE INDEX history_records_style_idx ON history_records(style)"),
    ("history_records_rating_idx", "CREATE INDEX history_records_rating_idx ON history_records(rating)"),
    ("history_records_status_idx", "CREATE INDEX history_records_status_idx ON history_records(status)"),
)


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
        self._active_key_version = services.active_version
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

    def export_records(
        self, request: HistoryListRequest, cancellation: Any
    ) -> Iterator[dict[str, Any]]:
        if not self.exists:
            return
        cursor = None
        while True:
            cancellation.raise_if_cancelled()
            rows = self._select_rows(request, cursor, 100)
            for row in rows:
                cancellation.raise_if_cancelled()
                detail = self._detail_row(row)
                if not detail["corrupted"]:
                    yield detail
            if len(rows) < 100:
                return
            cursor = self._cursor_values(rows[-1], request)

    def scan(self, cancellation: Any) -> dict[str, Any]:
        if not self.exists:
            return {"quick_check": "ok", "record_count": 0, "verified_records": 0, "corrupted_records": 0}
        verification = self._verify_database(self._path, cancellation)
        return {
            "quick_check": "ok",
            "record_count": verification["record_count"],
            "verified_records": verification["verified"],
            "corrupted_records": verification["corrupted"],
        }

    def repair(self, cancellation: Any) -> dict[str, Any]:
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        self._require_quick_check(self._path)
        manifest = self.create_backup(cancellation)
        cancellation.raise_if_cancelled()
        verified = quarantined = 0
        with self._connection(create=False, writable=True) as connection:
            rows = self._all_rows(connection)
            record_count = 0
            try:
                for row in rows:
                    record_count += 1
                    cancellation.raise_if_cancelled()
                    if self._row_is_valid(row):
                        verified += 1
                        continue
                    connection.execute(
                        "INSERT OR REPLACE INTO repair_quarantine(id, reason, quarantined_at) VALUES (?, ?, ?)",
                        (row["id"], "history_record_corrupted", _utc_now()),
                    )
                    connection.execute("DELETE FROM history_records WHERE id = ?", (row["id"],))
                    quarantined += 1
                for name, _statement in INDEX_DEFINITIONS:
                    connection.execute(f'DROP INDEX IF EXISTS "{name}"')
                for _name, statement in INDEX_DEFINITIONS:
                    connection.execute(statement)
                cancellation.raise_if_cancelled()
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return {
            "backup_id": manifest["id"],
            "record_count": record_count,
            "verified_records": verified,
            "quarantined_records": quarantined,
            "indexes_rebuilt": True,
        }

    def create_backup(self, cancellation: Any) -> dict[str, Any]:
        if not self.exists:
            raise HistoryPluginError("history_not_found")
        backup_id = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}"
        directory = self._backup_directory()
        directory.mkdir(parents=True, exist_ok=True)
        database_path = directory / f"{backup_id}.sqlite3"
        manifest_path = directory / f"{backup_id}.json"
        try:
            self._online_backup(database_path, cancellation)
            verification = self._verify_database(database_path, cancellation)
            manifest = {
                "id": backup_id,
                "schema_version": SCHEMA_VERSION,
                "created_at": _utc_now(),
                "key_versions": [f"v{version}" for version in verification["key_versions"]],
                "record_count": verification["record_count"],
                "aead": {"verified": verification["verified"], "corrupted": verification["corrupted"]},
            }
            encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            temporary = manifest_path.with_suffix(".json.tmp")
            with temporary.open("wb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, manifest_path)
            _fsync_directory(directory)
            return manifest
        except BaseException:
            database_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            manifest_path.with_suffix(".json.tmp").unlink(missing_ok=True)
            raise

    def backups(self, cancellation: Any) -> dict[str, Any]:
        directory = self._backup_directory()
        if not directory.is_dir():
            return {"items": []}
        items: list[dict[str, Any]] = []
        for manifest_path in sorted(directory.glob("backup-*.json"), reverse=True):
            cancellation.raise_if_cancelled()
            manifest = self._load_manifest(manifest_path)
            database_path = directory / f"{manifest['id']}.sqlite3"
            if database_path.is_file():
                items.append(manifest)
        return {"items": items}

    def restore(self, backup_id: str, cancellation: Any) -> dict[str, Any]:
        selected = self._listed_backup(backup_id)
        temporary = self._path.with_name(f".{self._path.name}.restore-{uuid.uuid4().hex}.tmp")
        pre_restore_id: str | None = None
        try:
            try:
                self._copy_database(
                    self._backup_directory() / f"{selected['id']}.sqlite3",
                    temporary,
                    cancellation,
                )
                verification = self._verify_database(temporary, cancellation)
                self._require_indexes(temporary)
            except OperationCancelled:
                raise
            except (HistoryPluginError, sqlite3.Error, OSError) as error:
                raise HistoryPluginError("history_backup_invalid") from error
            if not self._verification_matches_manifest(verification, selected):
                raise HistoryPluginError("history_backup_invalid")

            current_verification: dict[str, Any] | None = None
            try:
                current_verification = self._verify_database(
                    self._path, cancellation
                )
                self._require_indexes(self._path)
                if current_verification["corrupted"] != 0:
                    current_verification = None
            except OperationCancelled:
                raise
            except (HistoryPluginError, sqlite3.Error, OSError):
                current_verification = None

            if (
                current_verification is not None
                and current_verification["content_digest"]
                == verification["content_digest"]
            ):
                temporary.unlink(missing_ok=True)
                return {
                    "restored": True,
                    "backup_id": backup_id,
                    "pre_restore_backup_id": None,
                }

            if current_verification is not None:
                pre_restore_id = self.create_backup(cancellation)["id"]
            cancellation.raise_if_cancelled()
            self._replace_database(
                temporary,
                cancellation,
                expected_record_count=selected["record_count"],
                checkpoint_current=current_verification is not None,
            )
        except HistoryPluginError:
            temporary.unlink(missing_ok=True)
            raise
        except OperationCancelled:
            temporary.unlink(missing_ok=True)
            raise
        except Exception as error:
            temporary.unlink(missing_ok=True)
            raise HistoryPluginError("history_recovery_required") from error
        return {
            "restored": True,
            "backup_id": backup_id,
            "pre_restore_backup_id": pre_restore_id,
        }

    def has_rotation_checkpoint(self) -> bool:
        if not self.exists:
            return False
        with self._connection(create=False, writable=False) as connection:
            try:
                return connection.execute("SELECT 1 FROM rotation_checkpoint WHERE id = 1").fetchone() is not None
            except sqlite3.OperationalError:
                return False

    def prepare_rotation(self, target_version: int, batch_size: int, cancellation: Any) -> dict[str, Any]:
        if self._services.pending_version != target_version or target_version not in self._keys:
            raise HistoryPluginError("history_key_unavailable")
        if target_version <= self._services.active_version:
            raise HistoryPluginError("history_payload_invalid")
        checkpoint = self._rotation_checkpoint()
        backup_id = checkpoint["backup_id"] if checkpoint else None
        try:
            if checkpoint is None:
                self._rotation_phase_hook("frozen")
                backup = self.create_backup(cancellation)
                backup_id = backup["id"]
                self._rotation_phase_hook("backup")
                with self._connection(create=False, writable=True) as connection:
                    high_water = connection.execute("SELECT MAX(id) FROM history_records").fetchone()[0]
                    connection.execute(
                        "INSERT OR REPLACE INTO rotation_checkpoint(id, rotation_id, source_version, target_version, phase, backup_id, high_water_mark, last_record_id) VALUES (1, ?, ?, ?, ?, ?, ?, NULL)",
                        (uuid.uuid4().hex, self._services.active_version, target_version, "metadata", backup_id, high_water),
                    )
                    connection.commit()
                self._rotation_phase_hook("metadata")
            else:
                self._validate_rotation_checkpoint(
                    checkpoint, target_version, cancellation
                )
            while True:
                cancellation.raise_if_cancelled()
                changed = self._reencrypt_batch(target_version, batch_size, cancellation)
                if not changed:
                    break
                self._rotation_phase_hook("reencrypt")
            verification = self._verify_database(self._path, cancellation)
            if verification["corrupted"]:
                raise HistoryPluginError("history_rotation_failed")
            with self._connection(create=False, writable=True) as connection:
                connection.execute("UPDATE rotation_checkpoint SET phase = 'verified' WHERE id = 1")
                connection.commit()
            self._rotation_phase_hook("verified")
            return {"promotion_required": True, "target_version": f"v{target_version}", "backup_id": backup_id}
        except Exception as error:
            try:
                if backup_id is not None:
                    self._restore_backup_without_snapshot(
                        backup_id,
                        CancellationToken(),
                    )
                self._clear_rotation_checkpoint()
            except Exception as rollback_error:
                raise HistoryPluginError("history_recovery_required") from rollback_error
            if isinstance(error, OperationCancelled):
                raise
            if isinstance(error, HistoryPluginError) and error.code in {"history_busy", "history_payload_invalid", "history_key_unavailable"}:
                raise
            raise HistoryPluginError("history_rotation_failed") from error

    def finalize_rotation(self, target_version: int) -> dict[str, Any]:
        checkpoint = self._rotation_checkpoint()
        if (
            checkpoint is None
            or checkpoint["target_version"] != target_version
            or checkpoint["phase"] != "verified"
            or self._services.active_version != target_version
            or self._services.pending_version is not None
        ):
            raise HistoryPluginError("history_rotation_failed")
        self._clear_rotation_checkpoint()
        return {"rotated": True, "active_version": f"v{target_version}"}

    def resume_rotation(self, target_version: int) -> dict[str, Any]:
        checkpoint = self._rotation_checkpoint()
        if checkpoint is None:
            return {"resumed": False}
        if (
            checkpoint["target_version"] != target_version
            or checkpoint["phase"] != "verified"
            or self._services.active_version != target_version
            or self._services.pending_version is not None
        ):
            raise HistoryPluginError("history_rotation_failed")
        self._clear_rotation_checkpoint()
        return {
            "resumed": True,
            "rotated": True,
            "active_version": f"v{target_version}",
        }

    def rollback_rotation(self, target_version: int, cancellation: Any) -> dict[str, Any]:
        checkpoint = self._rotation_checkpoint()
        if checkpoint is None or checkpoint["target_version"] != target_version:
            raise HistoryPluginError("history_rotation_failed")
        self._restore_backup_without_snapshot(checkpoint["backup_id"], cancellation)
        self._clear_rotation_checkpoint()
        return {"rolled_back": True, "active_version": f"v{checkpoint['source_version']}"}

    def _online_backup(self, destination: Path, cancellation: Any) -> None:
        cancellation.raise_if_cancelled()
        source = sqlite3.connect(f"file:{self._path.as_posix()}?mode=ro", uri=True, timeout=5)
        target = sqlite3.connect(destination)
        try:
            source.backup(target, pages=64, progress=lambda *_: cancellation.raise_if_cancelled())
            target.commit()
        finally:
            target.close()
            source.close()
        with destination.open("r+b") as stream:
            os.fsync(stream.fileno())

    def _copy_database(self, source_path: Path, destination: Path, cancellation: Any) -> None:
        source = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(destination)
        try:
            source.backup(target, pages=64, progress=lambda *_: cancellation.raise_if_cancelled())
            target.commit()
        finally:
            target.close()
            source.close()
        with destination.open("r+b") as stream:
            os.fsync(stream.fileno())

    def _verify_database(self, path: Path, cancellation: Any) -> dict[str, Any]:
        self._require_quick_check(path)
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise HistoryPluginError("history_backup_invalid")
            required_tables = {
                "history_records",
                "schema_meta",
                "repair_quarantine",
                "rotation_checkpoint",
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            schema_version = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if (
                not required_tables.issubset(tables)
                or schema_version is None
                or schema_version[0] != str(SCHEMA_VERSION)
            ):
                raise HistoryPluginError("history_backup_invalid")
            rows = self._all_rows(connection)
            record_count = verified = corrupted = 0
            key_versions: set[int] = set()
            digest = hashlib.sha256()
            for row in rows:
                record_count += 1
                cancellation.raise_if_cancelled()
                _update_digest(digest, "history_records")
                for column in row.keys():
                    _update_digest(digest, column)
                    _update_digest(digest, row[column])
                key_versions.add(row["key_version"])
                if self._row_is_valid(row):
                    verified += 1
                else:
                    corrupted += 1
            for table, order_by in (
                ("schema_meta", "key"),
                ("repair_quarantine", "id"),
                ("rotation_checkpoint", "id"),
            ):
                for row in connection.execute(
                    f'SELECT * FROM "{table}" ORDER BY "{order_by}"'
                ):
                    _update_digest(digest, table)
                    for column in row.keys():
                        _update_digest(digest, column)
                        _update_digest(digest, row[column])
            for name, sql in connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'history_records' "
                "AND sql IS NOT NULL ORDER BY name"
            ):
                _update_digest(digest, "index")
                _update_digest(digest, name)
                _update_digest(digest, sql)
            return {
                "record_count": record_count,
                "verified": verified,
                "corrupted": corrupted,
                "key_versions": sorted(key_versions),
                "content_digest": digest.hexdigest(),
            }
        finally:
            connection.close()

    def _require_indexes(self, path: Path) -> None:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            indexes = dict(
                connection.execute(
                    "SELECT name, sql FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'history_records' "
                    "AND sql IS NOT NULL"
                )
            )
            if indexes != dict(INDEX_DEFINITIONS):
                raise HistoryPluginError("history_backup_invalid")
        finally:
            connection.close()

    def _verification_matches_manifest(
        self, verification: dict[str, Any], manifest: dict[str, Any]
    ) -> bool:
        return (
            verification["record_count"] == manifest["record_count"]
            and verification["verified"] == manifest["aead"]["verified"]
            and verification["corrupted"] == 0
            and manifest["aead"]["corrupted"] == 0
            and [f"v{version}" for version in verification["key_versions"]]
            == manifest["key_versions"]
        )

    def _row_is_valid(self, row: sqlite3.Row) -> bool:
        metadata = self._metadata_from_summary(row)
        try:
            self._codec.decrypt(EncryptedField(row["input_nonce"], row["input_ciphertext"]), metadata, row["key_version"], "input")
            self._codec.decrypt(EncryptedField(row["output_nonce"], row["output_ciphertext"]), metadata, row["key_version"], "output")
            return True
        except (InvalidTag, ValueError):
            return False

    def _all_rows(self, connection: sqlite3.Connection) -> Iterator[sqlite3.Row]:
        last_id: str | None = None
        while True:
            if last_id is None:
                rows = connection.execute(
                    f"SELECT {SUMMARY_COLUMNS}, input_nonce, input_ciphertext, output_nonce, output_ciphertext, key_version FROM history_records ORDER BY id LIMIT 100"
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT {SUMMARY_COLUMNS}, input_nonce, input_ciphertext, output_nonce, output_ciphertext, key_version FROM history_records WHERE id > ? ORDER BY id LIMIT 100",
                    (last_id,),
                ).fetchall()
            if not rows:
                return
            last_id = rows[-1]["id"]
            yield from rows

    def _require_quick_check(self, path: Path) -> None:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute("PRAGMA quick_check").fetchall()
            if rows != [("ok",)]:
                raise HistoryPluginError("history_recovery_required")
        finally:
            connection.close()

    def _backup_directory(self) -> Path:
        return self._path.parent / "backups"

    def _load_manifest(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HistoryPluginError("history_backup_invalid") from error
        expected = {"id", "schema_version", "created_at", "key_versions", "record_count", "aead"}
        if (
            not isinstance(value, dict) or set(value) != expected
            or not isinstance(value["id"], str) or path.name != f"{value['id']}.json"
            or value["schema_version"] != SCHEMA_VERSION
            or not isinstance(value["key_versions"], list)
            or any(version not in self._services.keys for version in value["key_versions"])
            or not isinstance(value["record_count"], int)
            or not isinstance(value["aead"], dict)
            or set(value["aead"]) != {"verified", "corrupted"}
        ):
            raise HistoryPluginError("history_backup_invalid")
        return value

    def _listed_backup(self, backup_id: str) -> dict[str, Any]:
        manifest_path = self._backup_directory() / f"{backup_id}.json"
        if not manifest_path.is_file():
            raise HistoryPluginError("history_backup_invalid")
        return self._load_manifest(manifest_path)

    def _replace_database(
        self,
        replacement: Path,
        cancellation: Any,
        *,
        expected_record_count: int,
        checkpoint_current: bool = True,
    ) -> None:
        rollback = self._path.with_name(f".{self._path.name}.rollback-{uuid.uuid4().hex}")
        if checkpoint_current:
            self._checkpoint_for_replace()
        self._write_replace_state(rollback, replacement)
        try:
            os.replace(self._path, rollback)
            os.replace(replacement, self._path)
            verification = self._verify_database(self._path, cancellation)
            self._require_indexes(self._path)
            if (
                verification["record_count"] != expected_record_count
                or verification["corrupted"] != 0
                or any(
                    version not in self._keys
                    for version in verification["key_versions"]
                )
            ):
                raise HistoryPluginError("history_backup_invalid")
            cancellation.raise_if_cancelled()
            rollback.unlink(missing_ok=True)
            for suffix in ("-wal", "-shm"):
                self._path.with_name(self._path.name + suffix).unlink(missing_ok=True)
            _fsync_directory(self._path.parent)
            self._clear_replace_state()
        except BaseException:
            try:
                if rollback.exists():
                    os.replace(rollback, self._path)
                replacement.unlink(missing_ok=True)
                self._clear_replace_state()
            except BaseException as recovery_error:
                raise HistoryPluginError("history_recovery_required") from recovery_error
            raise

    def _checkpoint_for_replace(self) -> None:
        if not self._path.is_file():
            raise HistoryPluginError("history_not_found")
        connection = sqlite3.connect(self._path, timeout=5)
        try:
            result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is None or result[0] != 0:
                raise HistoryPluginError("history_storage_busy")
        finally:
            connection.close()
        for suffix in ("-wal", "-shm"):
            self._path.with_name(self._path.name + suffix).unlink(missing_ok=True)

    def recover_interrupted_replace(self) -> None:
        marker = self._replace_state_path()
        if not marker.is_file():
            return
        with self._schema_lock:
            if not marker.is_file():
                return
            try:
                state = self._load_replace_state()
                rollback = self._path.parent / state["rollback"]
                replacement = self._path.parent / state["replacement"]
                if rollback.is_file():
                    os.replace(rollback, self._path)
                elif not self._path.is_file():
                    raise HistoryPluginError("history_recovery_required")
                replacement.unlink(missing_ok=True)
                self._clear_replace_state()
            except HistoryPluginError:
                raise
            except Exception as error:
                raise HistoryPluginError("history_recovery_required") from error

    def _replace_state_path(self) -> Path:
        return self._path.with_name(f".{self._path.name}.replace-state.json")

    def _write_replace_state(self, rollback: Path, replacement: Path) -> None:
        if rollback.parent != self._path.parent or replacement.parent != self._path.parent:
            raise HistoryPluginError("history_recovery_required")
        state = {
            "version": 1,
            "rollback": rollback.name,
            "replacement": replacement.name,
        }
        if not self._valid_replace_state(state):
            raise HistoryPluginError("history_recovery_required")
        marker = self._replace_state_path()
        temporary = marker.with_name(f".{marker.name}.{uuid.uuid4().hex}.tmp")
        encoded = json.dumps(
            state,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        try:
            with temporary.open("xb") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, marker)
            _fsync_directory(self._path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_replace_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self._replace_state_path().read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise HistoryPluginError("history_recovery_required") from error
        if not self._valid_replace_state(value):
            raise HistoryPluginError("history_recovery_required")
        return value

    def _valid_replace_state(self, value: Any) -> bool:
        if not isinstance(value, dict) or set(value) != {
            "version",
            "rollback",
            "replacement",
        }:
            return False
        rollback = value["rollback"]
        replacement = value["replacement"]
        prefix = f".{self._path.name}."
        return (
            value["version"] == 1
            and isinstance(rollback, str)
            and isinstance(replacement, str)
            and Path(rollback).name == rollback
            and Path(replacement).name == replacement
            and rollback.startswith(prefix + "rollback-")
            and replacement.startswith(prefix)
            and replacement.endswith(".tmp")
        )

    def _clear_replace_state(self) -> None:
        self._replace_state_path().unlink(missing_ok=True)
        _fsync_directory(self._path.parent)

    def _rotation_checkpoint(self) -> sqlite3.Row | None:
        if not self.exists:
            return None
        with self._connection(create=False, writable=False) as connection:
            try:
                return connection.execute("SELECT * FROM rotation_checkpoint WHERE id = 1").fetchone()
            except sqlite3.OperationalError:
                return None

    def _validate_rotation_checkpoint(
        self,
        checkpoint: sqlite3.Row,
        target_version: int,
        cancellation: Any,
    ) -> None:
        valid_shape = (
            checkpoint["target_version"] == target_version
            and checkpoint["source_version"] == self._services.active_version
            and checkpoint["source_version"] in self._keys
            and checkpoint["target_version"] in self._keys
            and checkpoint["phase"] in {"metadata", "reencrypt", "verified"}
            and isinstance(checkpoint["rotation_id"], str)
            and bool(checkpoint["rotation_id"])
            and isinstance(checkpoint["backup_id"], str)
            and (
                checkpoint["high_water_mark"] is None
                or isinstance(checkpoint["high_water_mark"], str)
            )
            and (
                checkpoint["last_record_id"] is None
                or isinstance(checkpoint["last_record_id"], str)
            )
        )
        if not valid_shape:
            raise HistoryPluginError("history_recovery_required")
        try:
            selected = self._listed_backup(checkpoint["backup_id"])
            backup_path = self._backup_directory() / f"{selected['id']}.sqlite3"
            verification = self._verify_database(backup_path, cancellation)
            self._require_indexes(backup_path)
        except OperationCancelled:
            raise
        except (HistoryPluginError, sqlite3.Error, OSError) as error:
            raise HistoryPluginError("history_recovery_required") from error
        if not self._verification_matches_manifest(verification, selected):
            raise HistoryPluginError("history_recovery_required")

    def _clear_rotation_checkpoint(self) -> None:
        if not self.exists:
            return
        with self._connection(create=False, writable=True) as connection:
            connection.execute("DELETE FROM rotation_checkpoint WHERE id = 1")
            connection.commit()

    def _reencrypt_batch(self, target_version: int, batch_size: int, cancellation: Any) -> int:
        with self._connection(create=False, writable=True) as connection:
            rows = connection.execute(
                f"SELECT {SUMMARY_COLUMNS}, input_nonce, input_ciphertext, output_nonce, output_ciphertext, key_version FROM history_records WHERE key_version != ? ORDER BY id LIMIT ?",
                (target_version, batch_size),
            ).fetchall()
            try:
                for row in rows:
                    cancellation.raise_if_cancelled()
                    metadata = self._metadata_from_summary(row)
                    input_text = self._codec.decrypt(EncryptedField(row["input_nonce"], row["input_ciphertext"]), metadata, row["key_version"], "input")
                    output_text = self._codec.decrypt(EncryptedField(row["output_nonce"], row["output_ciphertext"]), metadata, row["key_version"], "output")
                    input_field = self._codec.encrypt(input_text, metadata, target_version, "input")
                    output_field = self._codec.encrypt(output_text, metadata, target_version, "output")
                    connection.execute(
                        "UPDATE history_records SET input_nonce=?, input_ciphertext=?, output_nonce=?, output_ciphertext=?, key_version=? WHERE id=?",
                        (input_field.nonce, input_field.ciphertext, output_field.nonce, output_field.ciphertext, target_version, row["id"]),
                    )
                    connection.execute("UPDATE rotation_checkpoint SET phase='reencrypt', last_record_id=? WHERE id=1", (row["id"],))
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return len(rows)

    def _restore_backup_without_snapshot(self, backup_id: str, cancellation: Any) -> None:
        selected = self._listed_backup(backup_id)
        temporary = self._path.with_name(f".{self._path.name}.rotation-rollback-{uuid.uuid4().hex}.tmp")
        self._copy_database(self._backup_directory() / f"{selected['id']}.sqlite3", temporary, cancellation)
        verification = self._verify_database(temporary, cancellation)
        self._require_indexes(temporary)
        if not self._verification_matches_manifest(verification, selected):
            temporary.unlink(missing_ok=True)
            raise HistoryPluginError("history_recovery_required")
        self._replace_database(
            temporary,
            cancellation,
            expected_record_count=selected["record_count"],
        )

    def _rotation_phase_hook(self, phase: str) -> None:
        del phase

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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _update_digest(digest: Any, value: Any) -> None:
    if value is None:
        encoded = b""
        kind = b"n"
    elif isinstance(value, int):
        encoded = str(value).encode("ascii")
        kind = b"i"
    elif isinstance(value, str):
        encoded = value.encode("utf-8")
        kind = b"s"
    elif isinstance(value, (bytes, bytearray, memoryview)):
        encoded = bytes(value)
        kind = b"b"
    else:
        raise HistoryPluginError("history_backup_invalid")
    digest.update(kind)
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
