"""Strict, path-free public payload contracts for history operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Mapping

MAX_BODY_LENGTH = 1_000_000
MAX_PAGE_SIZE = 100
DEFAULT_RETENTION_MAX_RECORDS = 10_000
DEFAULT_RETENTION_MAX_AGE_DAYS = 180
DEFAULT_RETENTION_MAX_DATABASE_BYTES = 512 * 1024 * 1024
DEFAULT_RETENTION_CLEANUP_BATCH_SIZE = 500
DEFAULT_RETENTION_CHECK_INTERVAL_SAVES = 100
DEFAULT_RETENTION_BACKUP_MAX_COUNT = 3
DEFAULT_RETENTION_BACKUP_MAX_AGE_DAYS = 30
ALLOWED_MODES = frozenset({"content", "prompt"})
ALLOWED_STYLES = frozenset(
    {"concise", "balanced", "detailed", "creative", "precise"}
)
ALLOWED_STATUSES = frozenset({"completed", "failed", "cancelled"})
ALLOWED_SORTS = frozenset({"created_at", "rating"})
ALLOWED_DIRECTIONS = frozenset({"asc", "desc"})
ALLOWED_EXPORT_FORMATS = frozenset({"json", "csv", "markdown"})
ROTATION_ACTIONS = frozenset({"prepare", "finalize", "rollback", "resume"})
FILTER_FIELDS = frozenset(
    {"provider", "scene", "style", "date_from", "date_to", "rating"}
)
SAVE_FIELDS = frozenset(
    {
        "id",
        "created_at",
        "input",
        "output",
        "mode",
        "style",
        "scene",
        "provider",
        "model",
        "elapsed_ms",
        "status",
        "tags",
    }
)
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class HistoryPluginError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
            raise ValueError("invalid history error code")
        self.code = code
        super().__init__(code)


class _RedactedMapping(Mapping[str, Any]):
    def __init__(self, values: Mapping[str, Any]) -> None:
        self._values = dict(values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return "<redacted private mapping>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self._values) == dict(other)


def invalid_payload() -> HistoryPluginError:
    return HistoryPluginError("history_payload_invalid")


def _exact_fields(payload: object, allowed: frozenset[str], required: frozenset[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - allowed or not required.issubset(payload):
        raise invalid_payload()
    return payload


def _string(value: object, *, maximum: int, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise invalid_payload()
    return value


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise invalid_payload()
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or len(value) > 40 or not value.endswith("Z"):
        raise invalid_payload()
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise invalid_payload() from error
    return value


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise HistoryPluginError("history_service_unavailable")
    return value


@dataclass(frozen=True, repr=False)
class HistoryRetentionPolicy:
    max_records: int = DEFAULT_RETENTION_MAX_RECORDS
    max_age_days: int = DEFAULT_RETENTION_MAX_AGE_DAYS
    max_database_bytes: int = DEFAULT_RETENTION_MAX_DATABASE_BYTES
    cleanup_batch_size: int = DEFAULT_RETENTION_CLEANUP_BATCH_SIZE
    check_interval_saves: int = DEFAULT_RETENTION_CHECK_INTERVAL_SAVES
    backup_max_count: int = DEFAULT_RETENTION_BACKUP_MAX_COUNT
    backup_max_age_days: int = DEFAULT_RETENTION_BACKUP_MAX_AGE_DAYS

    @classmethod
    def from_value(cls, value: object) -> "HistoryRetentionPolicy":
        if value is None:
            return cls()
        allowed = {
            "max_records",
            "max_age_days",
            "max_database_bytes",
            "cleanup_batch_size",
            "check_interval_saves",
            "backup_max_count",
            "backup_max_age_days",
        }
        if not isinstance(value, Mapping) or not set(value).issubset(allowed):
            raise HistoryPluginError("history_service_unavailable")
        defaults = cls()
        return cls(
            max_records=_bounded_integer(
                value.get("max_records", defaults.max_records),
                minimum=1,
                maximum=1_000_000,
            ),
            max_age_days=_bounded_integer(
                value.get("max_age_days", defaults.max_age_days),
                minimum=1,
                maximum=3_650,
            ),
            max_database_bytes=_bounded_integer(
                value.get("max_database_bytes", defaults.max_database_bytes),
                minimum=64 * 1024,
                maximum=10 * 1024 * 1024 * 1024,
            ),
            cleanup_batch_size=_bounded_integer(
                value.get("cleanup_batch_size", defaults.cleanup_batch_size),
                minimum=1,
                maximum=500,
            ),
            check_interval_saves=_bounded_integer(
                value.get("check_interval_saves", defaults.check_interval_saves),
                minimum=1,
                maximum=10_000,
            ),
            backup_max_count=_bounded_integer(
                value.get("backup_max_count", defaults.backup_max_count),
                minimum=1,
                maximum=100,
            ),
            backup_max_age_days=_bounded_integer(
                value.get("backup_max_age_days", defaults.backup_max_age_days),
                minimum=1,
                maximum=3_650,
            ),
        )


@dataclass(frozen=True, repr=False)
class HistoryServiceSnapshot:
    database_path: Path
    keys: Mapping[str, str]
    history_enabled: bool
    privacy_mode: bool
    history_redaction: str
    retention: HistoryRetentionPolicy = HistoryRetentionPolicy()
    active_key_version: str | None = None
    pending_key_version: str | None = None

    @classmethod
    def from_services(cls, services: object) -> "HistoryServiceSnapshot":
        if not isinstance(services, Mapping):
            raise HistoryPluginError("history_service_unavailable")
        value = services.get("history")
        allowed = {
            "database_path", "keys", "history_enabled", "privacy_mode",
            "history_redaction", "retention", "active_key_version", "pending_key_version",
        }
        if not isinstance(value, Mapping) or not set(value).issubset(allowed) or not {
            "database_path", "keys", "history_enabled", "privacy_mode", "history_redaction"
        }.issubset(value):
            raise HistoryPluginError("history_service_unavailable")
        database_path = value["database_path"]
        keys = value["keys"]
        if not isinstance(database_path, Path) or not database_path.is_absolute():
            raise HistoryPluginError("history_service_unavailable")
        if not isinstance(keys, Mapping) or any(
            not isinstance(version, str)
            or re.fullmatch(r"v[1-9][0-9]{0,6}", version) is None
            or not isinstance(secret, str)
            or re.fullmatch(r"[0-9a-f]{64}", secret) is None
            for version, secret in keys.items()
        ):
            raise HistoryPluginError("history_key_unavailable")
        if not isinstance(value["history_enabled"], bool) or not isinstance(
            value["privacy_mode"], bool
        ):
            raise HistoryPluginError("history_service_unavailable")
        if value["history_redaction"] not in {"secrets", "none"}:
            raise HistoryPluginError("history_service_unavailable")
        for name in ("active_key_version", "pending_key_version"):
            version = value.get(name)
            if version is not None and (
                not isinstance(version, str) or re.fullmatch(r"v[1-9][0-9]{0,6}", version) is None
            ):
                raise HistoryPluginError("history_service_unavailable")
        return cls(
            database_path=database_path,
            keys=_RedactedMapping(keys),
            history_enabled=value["history_enabled"],
            privacy_mode=value["privacy_mode"],
            history_redaction=value["history_redaction"],
            retention=HistoryRetentionPolicy.from_value(value.get("retention")),
            active_key_version=value.get("active_key_version"),
            pending_key_version=value.get("pending_key_version"),
        )

    def decoded_keys(self) -> dict[int, bytes]:
        if not self.keys:
            raise HistoryPluginError("history_key_unavailable")
        return {int(version[1:]): bytes.fromhex(secret) for version, secret in self.keys.items()}

    @property
    def active_version(self) -> int:
        if self.active_key_version is not None:
            return int(self.active_key_version[1:])
        return max(self.decoded_keys())

    @property
    def pending_version(self) -> int | None:
        return int(self.pending_key_version[1:]) if self.pending_key_version else None


@dataclass(frozen=True, repr=False)
class HistorySaveSnapshot:
    id: str
    created_at: str
    input: str
    output: str
    mode: str
    style: str
    scene: str | None
    provider: str
    model: str | None
    elapsed_ms: int | None
    status: str
    tags: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: object) -> "HistorySaveSnapshot":
        value = _exact_fields(payload, SAVE_FIELDS, SAVE_FIELDS)
        input_text = value["input"]
        output_text = value["output"]
        if (
            not isinstance(input_text, str)
            or not isinstance(output_text, str)
            or not input_text
            or len(input_text) > MAX_BODY_LENGTH
            or len(output_text) > MAX_BODY_LENGTH
        ):
            raise invalid_payload()
        mode = value["mode"]
        style = value["style"]
        status = value["status"]
        if mode not in ALLOWED_MODES or style not in ALLOWED_STYLES or status not in ALLOWED_STATUSES:
            raise invalid_payload()
        elapsed_ms = value["elapsed_ms"]
        if elapsed_ms is not None and (
            not isinstance(elapsed_ms, int)
            or isinstance(elapsed_ms, bool)
            or not 0 <= elapsed_ms <= 2**31 - 1
        ):
            raise invalid_payload()
        tags = value["tags"]
        if (
            not isinstance(tags, list)
            or len(tags) > 32
            or any(
                not isinstance(tag, str)
                or not tag
                or len(tag) > 64
                or any(ord(character) < 32 for character in tag)
                for tag in tags
            )
        ):
            raise invalid_payload()
        scene = _string(value["scene"], maximum=128, optional=True)
        model = _string(value["model"], maximum=128, optional=True)
        return cls(
            id=_safe_id(value["id"]),
            created_at=_timestamp(value["created_at"]),
            input=input_text,
            output=output_text,
            mode=mode,
            style=style,
            scene=scene,
            provider=_safe_id(value["provider"]),
            model=model,
            elapsed_ms=elapsed_ms,
            status=status,
            tags=tuple(tags),
        )


@dataclass(frozen=True, repr=False)
class HistoryListRequest:
    page_size: int
    sort: str
    direction: str
    cursor: str | None
    filters: Mapping[str, Any]
    keyword: str | None

    @classmethod
    def from_payload(cls, payload: object) -> "HistoryListRequest":
        allowed = frozenset({"page_size", "sort", "direction", "cursor", "filters", "keyword"})
        value = _exact_fields(payload, allowed, frozenset())
        page_size = value.get("page_size", 50)
        sort = value.get("sort", "created_at")
        direction = value.get("direction", "desc")
        cursor = value.get("cursor")
        filters = value.get("filters", {})
        keyword = value.get("keyword")
        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not 1 <= page_size <= MAX_PAGE_SIZE
            or sort not in ALLOWED_SORTS
            or direction not in ALLOWED_DIRECTIONS
            or (cursor is not None and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096))
            or not isinstance(filters, dict)
            or set(filters) - FILTER_FIELDS
            or (keyword is not None and (not isinstance(keyword, str) or not keyword or len(keyword) > 256))
        ):
            raise invalid_payload()
        normalized_filters: dict[str, Any] = {}
        for field, item in filters.items():
            if field in {"provider", "scene"}:
                normalized_filters[field] = _safe_id(item)
            elif field == "style":
                if item not in ALLOWED_STYLES:
                    raise invalid_payload()
                normalized_filters[field] = item
            elif field in {"date_from", "date_to"}:
                normalized_filters[field] = _timestamp(item)
            elif field == "rating":
                if not isinstance(item, int) or isinstance(item, bool) or not 1 <= item <= 5:
                    raise invalid_payload()
                normalized_filters[field] = item
        if (
            "date_from" in normalized_filters
            and "date_to" in normalized_filters
            and normalized_filters["date_from"] > normalized_filters["date_to"]
        ):
            raise invalid_payload()
        return cls(
            page_size,
            sort,
            direction,
            cursor,
            _RedactedMapping(normalized_filters),
            keyword,
        )


def parse_id_payload(payload: object) -> str:
    value = _exact_fields(payload, frozenset({"id"}), frozenset({"id"}))
    return _safe_id(value["id"])


def parse_rate_payload(payload: object) -> tuple[str, int | None]:
    value = _exact_fields(
        payload,
        frozenset({"id", "rating"}),
        frozenset({"id", "rating"}),
    )
    rating = value["rating"]
    if rating is not None and (
        not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5
    ):
        raise invalid_payload()
    return _safe_id(value["id"]), rating


def parse_clear_payload(payload: object) -> None:
    _exact_fields(payload, frozenset(), frozenset())


def parse_export_payload(payload: object) -> tuple[str, HistoryListRequest]:
    value = _exact_fields(payload, frozenset({"format", "filters"}), frozenset({"format", "filters"}))
    if value["format"] not in ALLOWED_EXPORT_FORMATS or not isinstance(value["filters"], dict):
        raise invalid_payload()
    request = HistoryListRequest.from_payload(
        {"page_size": MAX_PAGE_SIZE, "sort": "created_at", "direction": "asc", "filters": value["filters"]}
    )
    return value["format"], request


def parse_backup_id_payload(payload: object) -> str:
    value = _exact_fields(payload, frozenset({"backup_id"}), frozenset({"backup_id"}))
    return _safe_id(value["backup_id"])


def parse_rotate_payload(payload: object) -> tuple[str, str, int]:
    allowed = frozenset({"action", "target_version", "batch_size"})
    value = _exact_fields(payload, allowed, frozenset({"action", "target_version"}))
    target = value["target_version"]
    if value["action"] not in ROTATION_ACTIONS or not isinstance(target, str) or re.fullmatch(r"v[1-9][0-9]{0,6}", target) is None:
        raise invalid_payload()
    batch_size = value.get("batch_size", 25)
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or not 1 <= batch_size <= 100:
        raise invalid_payload()
    return value["action"], target, batch_size
