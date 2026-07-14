#!/usr/bin/env python3
"""Privacy-safe performance benchmark for the SQLite history plugin."""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD_COUNT = 10_000
DEFAULT_PROFILE = "small"
DEFAULT_PAGE_SIZE = 100
DEFAULT_ROTATION_BATCH_SIZE = 100
DEFAULT_STORAGE_SAMPLE_EVERY = 100
MAX_RECORD_COUNT = 10_000
MIB = 1024 * 1024

PROFILE_SIZES = {
    "small": {"input_bytes": 1024, "output_bytes": 4096},
    "heavy": {"input_bytes": 16 * 1024, "output_bytes": 64 * 1024},
}

LIMITS_MS = {
    "save_p95": 30.0,
    "save_p99": 100.0,
    "pagination_p95": 50.0,
    "pagination_p99": 150.0,
    "search_hit": 2_000.0,
    "search_miss": 2_000.0,
    "search_hard_deadline": 5_000.0,
    "export_first_chunk": 500.0,
    "export_total": 10_000.0,
    "rotation_total": 30_000.0,
    "rotation_hard_deadline": 60_000.0,
}

QUERY_PLAN_SQL = {
    "created_at_page": (
        "SELECT id, created_at FROM history_records "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (DEFAULT_PAGE_SIZE,),
    ),
    "provider_filter": (
        "SELECT id, created_at FROM history_records WHERE provider = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        ("benchmark", DEFAULT_PAGE_SIZE),
    ),
    "rating_page": (
        "SELECT id, rating FROM history_records "
        "ORDER BY rating IS NULL ASC, rating DESC, id DESC LIMIT ?",
        (DEFAULT_PAGE_SIZE,),
    ),
    "rotation_batch": (
        "SELECT id FROM history_records WHERE key_version != ? "
        "ORDER BY key_version, id LIMIT ?",
        (2, DEFAULT_ROTATION_BATCH_SIZE),
    ),
}


class BenchmarkFailure(RuntimeError):
    """A stable failure category that never includes private data."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BenchmarkProfile:
    name: str
    input_bytes: int
    output_bytes: int


@dataclass(frozen=True)
class StorageSample:
    database_bytes: int
    wal_bytes: int
    backup_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.database_bytes + self.wal_bytes + self.backup_bytes


class BenchmarkWorkload(Protocol):
    def execute(
        self,
        *,
        record_count: int,
        profile: BenchmarkProfile,
        page_size: int,
        rotation_batch_size: int,
        storage_sample_every: int,
    ) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


def validate_options(
    *,
    record_count: int,
    profile: str,
    page_size: int,
    rotation_batch_size: int,
    storage_sample_every: int,
) -> None:
    if (
        not isinstance(record_count, int)
        or isinstance(record_count, bool)
        or not 1 <= record_count <= MAX_RECORD_COUNT
    ):
        raise ValueError(f"record-count must be between 1 and {MAX_RECORD_COUNT}")
    if profile not in PROFILE_SIZES:
        raise ValueError("profile must be small or heavy")
    if (
        not isinstance(page_size, int)
        or isinstance(page_size, bool)
        or not 1 <= page_size <= 100
    ):
        raise ValueError("page-size must be between 1 and 100")
    if (
        not isinstance(rotation_batch_size, int)
        or isinstance(rotation_batch_size, bool)
        or not 1 <= rotation_batch_size <= 100
    ):
        raise ValueError("rotation-batch-size must be between 1 and 100")
    if (
        not isinstance(storage_sample_every, int)
        or isinstance(storage_sample_every, bool)
        or not 1 <= storage_sample_every <= MAX_RECORD_COUNT
    ):
        raise ValueError(
            f"storage-sample-every must be between 1 and {MAX_RECORD_COUNT}"
        )


def _profile(name: str) -> BenchmarkProfile:
    values = PROFILE_SIZES[name]
    return BenchmarkProfile(name, values["input_bytes"], values["output_bytes"])


def _source_path(name: str) -> Path:
    return {
        "core": REPO_ROOT / "packages" / "reflex-core" / "src",
        "runtime": REPO_ROOT / "packages" / "reflex-runtime" / "src",
        "history": REPO_ROOT / "plugins" / "history-sqlite" / "src",
    }[name]


def _load_local_dependencies() -> tuple[Any, Any, Any, Any, Any]:
    for name in ("history", "runtime", "core"):
        source = str(_source_path(name))
        if source not in sys.path:
            sys.path.insert(0, source)
    from reflex_core import CancellationToken
    from reflex_history_sqlite.plugin import HistorySqlitePlugin
    from reflex_history_sqlite.repository import INDEX_DEFINITIONS
    from reflex_runtime.capability_registry import CapabilityRegistry
    from reflex_runtime.plugin_contracts import PluginDescriptor

    return (
        CancellationToken,
        HistorySqlitePlugin,
        CapabilityRegistry,
        PluginDescriptor,
        INDEX_DEFINITIONS,
    )


def _safe_query_objects(index_definitions: Any) -> frozenset[str]:
    try:
        names = tuple(item[0] for item in index_definitions)
    except (TypeError, IndexError):
        raise BenchmarkFailure("invalid_index_definitions") from None
    if not names or any(
        not isinstance(name, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", name) is None
        for name in names
    ):
        raise BenchmarkFailure("invalid_index_definitions")
    return frozenset(
        {*names, "history_records", "sqlite_autoindex_history_records_1"}
    )


def _current_safe_query_objects() -> frozenset[str]:
    return _safe_query_objects(_load_local_dependencies()[-1])


def _descriptor_for(plugin: Any, descriptor_type: Any) -> Any:
    source = plugin.descriptor
    return descriptor_type(
        plugin_id=source.plugin_id,
        display_name=source.display_name,
        version=source.version,
        kind=source.kind,
        permissions=source.permissions,
        operations=source.operations,
        public_operations=source.public_operations,
    )


class LocalHistoryBenchmark:
    """Drive the real plugin through the Runtime capability registry."""

    def __init__(self, *, clock: Callable[[], float] = time.perf_counter) -> None:
        (
            cancellation_type,
            plugin_type,
            registry_type,
            descriptor_type,
            index_definitions,
        ) = _load_local_dependencies()
        self._cancellation_type = cancellation_type
        self._clock = clock
        self._temporary = tempfile.TemporaryDirectory(prefix="reflex-history-benchmark-")
        root = Path(self._temporary.name).resolve()
        self._database_path = root / "history" / "history.sqlite3"
        self._backup_path = self._database_path.parent / "backups"
        self._plugin = plugin_type()
        self._safe_query_objects = _safe_query_objects(index_definitions)
        self._registry = registry_type(
            [(_descriptor_for(self._plugin, descriptor_type), self._plugin)]
        )
        self._registry.configure_history_keys(
            {"v1": "11" * 32, "v2": "22" * 32},
            active_version="v1",
            pending_version="v2",
        )
        self._registry.configure_history_path(self._database_path)
        self._registry.configure_history_policy(
            history_enabled=True,
            privacy_mode=False,
            history_redaction="secrets",
        )
        self._created_at_base = datetime.now(timezone.utc)
        self._storage_samples: list[StorageSample] = []
        self._closed = False

    def execute(
        self,
        *,
        record_count: int,
        profile: BenchmarkProfile,
        page_size: int,
        rotation_batch_size: int,
        storage_sample_every: int,
    ) -> Mapping[str, Any]:
        if self._closed:
            raise BenchmarkFailure("workload_closed")
        # Keep the fixture inside the default retention window so this benchmark
        # measures storage behavior instead of intentionally deleting its input.
        self._created_at_base = datetime.now(timezone.utc)
        save_durations: list[float] = []
        for index in range(record_count):
            started = self._clock()
            self._save(index, record_count, profile)
            save_durations.append(_elapsed_ms(started, self._clock()))
            if (index + 1) % storage_sample_every == 0:
                self._sample_storage()
        after_load = self._sample_storage()

        query_plans = self._query_plans()
        pagination = self._benchmark_pagination(page_size)
        search = self._benchmark_search()
        export = self._benchmark_export()
        steady_peak = _storage_peak_values(self._storage_samples)
        rotation = self._benchmark_rotation(rotation_batch_size)
        final_storage = self._sample_storage()
        overall_peak = _storage_peak_values(self._storage_samples)

        return {
            "record_count": record_count,
            "save_ms": _latency_summary(save_durations),
            "pagination": pagination,
            "search": search,
            "export": export,
            "rotation": rotation,
            "storage": {
                "after_load": _storage_values(after_load),
                "steady_peak": steady_peak,
                "overall_peak": overall_peak,
                "final": _storage_values(final_storage),
            },
            "query_plans": query_plans,
        }

    def _save(
        self, index: int, record_count: int, profile: BenchmarkProfile
    ) -> None:
        record_id = f"benchmark-{index:09d}"
        input_body = _body(profile.input_bytes, index, include_hit=False)
        output_body = _body(
            profile.output_bytes,
            index,
            include_hit=index == record_count - 1,
        )
        created_at = (
            self._created_at_base + timedelta(milliseconds=index)
        ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self._registry.invoke_internal(
            "history-sqlite",
            "save",
            {
                "id": record_id,
                "created_at": created_at,
                "input": input_body,
                "output": output_body,
                "mode": "content",
                "style": "concise",
                "scene": "coding",
                "provider": "benchmark",
                "model": "local-fixture",
                "elapsed_ms": 1,
                "status": "completed",
                "tags": ["benchmark"],
            },
            {},
            self._cancellation_type(),
            trusted=True,
        )

    def _benchmark_pagination(self, page_size: int) -> dict[str, Any]:
        cursor: str | None = None
        durations: list[float] = []
        item_count = 0
        page_count = 0
        seen_ids: set[str] = set()
        while True:
            payload: dict[str, Any] = {
                "page_size": page_size,
                "sort": "created_at",
                "direction": "asc",
            }
            if cursor is not None:
                payload["cursor"] = cursor
            started = self._clock()
            page = self._registry.invoke_public(
                "history-sqlite",
                "list",
                payload,
                {},
                self._cancellation_type(),
            )
            durations.append(_elapsed_ms(started, self._clock()))
            items = page.get("items", [])
            if not isinstance(items, list):
                raise BenchmarkFailure("invalid_pagination_result")
            for item in items:
                record_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(record_id, str) or record_id in seen_ids:
                    raise BenchmarkFailure("invalid_pagination_result")
                seen_ids.add(record_id)
            item_count += len(items)
            page_count += 1
            cursor = page.get("next_cursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or page_count > MAX_RECORD_COUNT:
                raise BenchmarkFailure("invalid_pagination_result")
        return {
            "page_count": page_count,
            "record_count": item_count,
            "latency_ms": _latency_summary(durations),
        }

    def _benchmark_search(self) -> dict[str, Any]:
        return {
            "hit_ms": self._search("benchmark-match-token", expected_matches=1),
            "miss_ms": self._search("benchmark-absent-token", expected_matches=0),
        }

    def _search(self, keyword: str, *, expected_matches: int) -> float:
        started = self._clock()
        result = self._registry.invoke_public(
            "history-sqlite",
            "list",
            {
                "page_size": 1,
                "sort": "created_at",
                "direction": "asc",
                "keyword": keyword,
            },
            {},
            self._cancellation_type(),
        )
        elapsed = _elapsed_ms(started, self._clock())
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("items"), list)
            or len(result["items"]) != expected_matches
        ):
            raise BenchmarkFailure("invalid_search_result")
        return elapsed

    def _benchmark_export(self) -> dict[str, Any]:
        started = self._clock()
        first_chunk_ms: float | None = None
        chunk_count = 0
        raw_bytes = 0
        record_count: int | None = None
        failure_category: str | None = None
        try:
            events = self._registry.invoke_admin(
                "history-sqlite",
                "export",
                {"format": "json", "filters": {}},
                {},
                self._cancellation_type(),
            )
            for event in events:
                if not isinstance(event, dict):
                    raise BenchmarkFailure("invalid_export_result")
                if event.get("status") == "chunk":
                    if first_chunk_ms is None:
                        first_chunk_ms = _elapsed_ms(started, self._clock())
                    encoded = event.get("data", {}).get("bytes")
                    if not isinstance(encoded, str):
                        raise BenchmarkFailure("invalid_export_result")
                    try:
                        raw_bytes += len(base64.b64decode(encoded, validate=True))
                    except (ValueError, TypeError):
                        raise BenchmarkFailure("invalid_export_result") from None
                    chunk_count += 1
                elif event.get("status") == "result":
                    value = event.get("data", {}).get("record_count")
                    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                        raise BenchmarkFailure("invalid_export_result")
                    record_count = value
                else:
                    raise BenchmarkFailure("invalid_export_result")
        except BenchmarkFailure:
            raise
        except Exception as error:
            failure_category = _safe_error_code(error, "export_failed")
        total_ms = _elapsed_ms(started, self._clock())
        return {
            "first_chunk_ms": first_chunk_ms,
            "total_ms": total_ms,
            "chunk_count": chunk_count,
            "raw_bytes": raw_bytes,
            "record_count": record_count,
            "failure_category": failure_category,
            "completed": failure_category is None and record_count is not None,
        }

    def _benchmark_rotation(self, batch_size: int) -> dict[str, Any]:
        started = self._clock()
        failure_category: str | None = None
        prepared = False
        finalized = False
        try:
            result = self._registry.invoke_admin(
                "history-sqlite",
                "rotate",
                {
                    "action": "prepare",
                    "target_version": "v2",
                    "batch_size": batch_size,
                },
                {},
                self._cancellation_type(),
            )
            prepared = (
                isinstance(result, dict)
                and result.get("promotion_required") is True
                and result.get("target_version") == "v2"
            )
            self._sample_storage()
            if not prepared:
                raise BenchmarkFailure("invalid_rotation_result")
            self._registry.configure_history_keys(
                {"v1": "11" * 32, "v2": "22" * 32},
                active_version="v2",
                pending_version=None,
            )
            result = self._registry.invoke_admin(
                "history-sqlite",
                "rotate",
                {"action": "finalize", "target_version": "v2"},
                {},
                self._cancellation_type(),
            )
            finalized = (
                isinstance(result, dict)
                and result.get("rotated") is True
                and result.get("active_version") == "v2"
            )
            if not finalized:
                raise BenchmarkFailure("invalid_rotation_result")
        except BenchmarkFailure:
            raise
        except Exception as error:
            failure_category = _safe_error_code(error, "rotation_failed")
        return {
            "total_ms": _elapsed_ms(started, self._clock()),
            "prepared": prepared,
            "finalized": finalized,
            "failure_category": failure_category,
            "completed": failure_category is None and prepared and finalized,
        }

    def _query_plans(self) -> dict[str, Any]:
        plans: dict[str, Any] = {}
        connection = sqlite3.connect(
            f"file:{self._database_path.as_posix()}?mode=ro", uri=True, timeout=5
        )
        try:
            for name, (statement, parameters) in QUERY_PLAN_SQL.items():
                rows = connection.execute(
                    "EXPLAIN QUERY PLAN " + statement, parameters
                ).fetchall()
                plans[name] = _normalize_query_plan(rows, self._safe_query_objects)
        finally:
            connection.close()
        return plans

    def _sample_storage(self) -> StorageSample:
        wal_path = self._database_path.with_name(self._database_path.name + "-wal")
        backup_bytes = 0
        if self._backup_path.is_dir():
            for child in self._backup_path.iterdir():
                if child.is_file() and not child.is_symlink():
                    backup_bytes += child.stat().st_size
        sample = StorageSample(
            database_bytes=_file_size(self._database_path),
            wal_bytes=_file_size(wal_path),
            backup_bytes=backup_bytes,
        )
        self._storage_samples.append(sample)
        return sample

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._temporary.cleanup()


class HistoryBenchmarkRunner:
    def __init__(
        self,
        *,
        workload_factory: Callable[[], BenchmarkWorkload] = LocalHistoryBenchmark,
    ) -> None:
        self._workload_factory = workload_factory

    def run(
        self,
        *,
        record_count: int = DEFAULT_RECORD_COUNT,
        profile: str = DEFAULT_PROFILE,
        page_size: int = DEFAULT_PAGE_SIZE,
        rotation_batch_size: int = DEFAULT_ROTATION_BATCH_SIZE,
        storage_sample_every: int = DEFAULT_STORAGE_SAMPLE_EVERY,
    ) -> dict[str, Any]:
        validate_options(
            record_count=record_count,
            profile=profile,
            page_size=page_size,
            rotation_batch_size=rotation_batch_size,
            storage_sample_every=storage_sample_every,
        )
        workload: BenchmarkWorkload | None = None
        measurements: Mapping[str, Any] | None = None
        failure_category: str | None = None
        cleanup_succeeded = False
        try:
            workload = self._workload_factory()
            candidate = workload.execute(
                record_count=record_count,
                profile=_profile(profile),
                page_size=page_size,
                rotation_batch_size=rotation_batch_size,
                storage_sample_every=storage_sample_every,
            )
            _validate_measurements(candidate, record_count)
            measurements = candidate
        except BenchmarkFailure as error:
            failure_category = error.code
        except Exception:
            failure_category = "unexpected_failure"
        finally:
            if workload is not None:
                try:
                    workload.close()
                    cleanup_succeeded = True
                except Exception:
                    if failure_category is None:
                        failure_category = "workload_cleanup_failed"

        threshold_report = (
            evaluate_thresholds(measurements, record_count=record_count)
            if measurements is not None and failure_category is None
            else None
        )
        execution_class = (
            "manual_production" if record_count == DEFAULT_RECORD_COUNT else "ci_smoke"
        )
        operation_succeeded = failure_category is None and cleanup_succeeded
        passed = operation_succeeded and threshold_report is not None
        if threshold_report is not None:
            checks = threshold_report["checks"]
            required_checks = (
                tuple(checks)
                if threshold_report["applicable"]
                else (
                    "record_count",
                    "pagination_complete",
                    "export_completed",
                    "rotation_completed",
                )
            )
            passed = passed and all(checks[name] for name in required_checks)
        return {
            "schema_version": 1,
            "plan": {
                "profile": profile,
                "record_count": record_count,
                "input_bytes": PROFILE_SIZES[profile]["input_bytes"],
                "output_bytes": PROFILE_SIZES[profile]["output_bytes"],
                "page_size": page_size,
                "rotation_batch_size": rotation_batch_size,
                "storage_sample_every": storage_sample_every,
                "execution_class": execution_class,
            },
            "result": {
                "failure_category": failure_category,
                "cleanup_succeeded": cleanup_succeeded,
            },
            "metrics": dict(measurements) if measurements is not None else None,
            "thresholds": threshold_report,
            "passed": passed,
        }


def evaluate_thresholds(
    measurements: Mapping[str, Any], *, record_count: int
) -> dict[str, Any]:
    save = measurements["save_ms"]
    pagination = measurements["pagination"]
    page_latency = pagination["latency_ms"]
    search = measurements["search"]
    export = measurements["export"]
    rotation = measurements["rotation"]
    storage = measurements["storage"]
    plans = measurements["query_plans"]
    after_load = storage["after_load"]
    database_bytes = max(after_load["database_bytes"], 1)
    steady_total = storage["steady_peak"]["total_bytes"]
    overall_total = storage["overall_peak"]["total_bytes"]

    checks = {
        "record_count": measurements["record_count"] == record_count,
        "pagination_complete": pagination["record_count"] == record_count,
        "save_p95": save["p95"] <= LIMITS_MS["save_p95"],
        "save_p99": save["p99"] <= LIMITS_MS["save_p99"],
        "pagination_p95": page_latency["p95"] <= LIMITS_MS["pagination_p95"],
        "pagination_p99": page_latency["p99"] <= LIMITS_MS["pagination_p99"],
        "search_hit": search["hit_ms"] <= LIMITS_MS["search_hit"],
        "search_miss": search["miss_ms"] <= LIMITS_MS["search_miss"],
        "search_hard_deadline": max(search.values()) <= LIMITS_MS["search_hard_deadline"],
        "export_completed": export["completed"] is True
        and export["record_count"] == record_count,
        "export_first_chunk": export["first_chunk_ms"] is not None
        and export["first_chunk_ms"] <= LIMITS_MS["export_first_chunk"],
        "export_total": export["total_ms"] <= LIMITS_MS["export_total"],
        "rotation_completed": rotation["completed"] is True,
        "rotation_total": rotation["total_ms"] <= LIMITS_MS["rotation_total"],
        "rotation_hard_deadline": rotation["total_ms"]
        <= LIMITS_MS["rotation_hard_deadline"],
        "steady_storage": steady_total <= database_bytes * 2,
        "rotation_storage": overall_total <= database_bytes * 3,
        "created_at_page_no_temp_sort": not plans["created_at_page"][
            "uses_temp_btree"
        ],
        "provider_filter_uses_index": plans["provider_filter"]["uses_index"],
        "rotation_batch_uses_index": plans["rotation_batch"]["uses_index"],
    }
    return {
        "applicable": record_count == DEFAULT_RECORD_COUNT,
        "limits_ms": dict(LIMITS_MS),
        "storage_limits": {"steady_ratio": 2, "rotation_ratio": 3},
        "checks": checks,
        "passed": all(checks.values()),
    }


def _validate_measurements(value: Mapping[str, Any], record_count: int) -> None:
    expected = {
        "record_count",
        "save_ms",
        "pagination",
        "search",
        "export",
        "rotation",
        "storage",
        "query_plans",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise BenchmarkFailure("invalid_benchmark_result")
    if value["record_count"] != record_count:
        raise BenchmarkFailure("invalid_benchmark_result")
    _validate_latency_mapping(value["save_ms"])
    pagination = _exact_mapping(
        value["pagination"], {"page_count", "record_count", "latency_ms"}
    )
    _nonnegative_integer(pagination["page_count"])
    _nonnegative_integer(pagination["record_count"])
    _validate_latency_mapping(pagination["latency_ms"])
    search = _exact_mapping(value["search"], {"hit_ms", "miss_ms"})
    _nonnegative_number(search["hit_ms"])
    _nonnegative_number(search["miss_ms"])
    export = _exact_mapping(
        value["export"],
        {
            "first_chunk_ms",
            "total_ms",
            "chunk_count",
            "raw_bytes",
            "record_count",
            "failure_category",
            "completed",
        },
    )
    if export["first_chunk_ms"] is not None:
        _nonnegative_number(export["first_chunk_ms"])
    _nonnegative_number(export["total_ms"])
    _nonnegative_integer(export["chunk_count"])
    _nonnegative_integer(export["raw_bytes"])
    if export["record_count"] is not None:
        _nonnegative_integer(export["record_count"])
    _failure_category(export["failure_category"])
    if not isinstance(export["completed"], bool):
        raise BenchmarkFailure("invalid_benchmark_result")
    rotation = _exact_mapping(
        value["rotation"],
        {
            "total_ms",
            "prepared",
            "finalized",
            "failure_category",
            "completed",
        },
    )
    _nonnegative_number(rotation["total_ms"])
    if any(
        not isinstance(rotation[name], bool)
        for name in ("prepared", "finalized", "completed")
    ):
        raise BenchmarkFailure("invalid_benchmark_result")
    _failure_category(rotation["failure_category"])
    storage = _exact_mapping(
        value["storage"], {"after_load", "steady_peak", "overall_peak", "final"}
    )
    for sample in storage.values():
        _validate_storage_mapping(sample)
    plans = _exact_mapping(value["query_plans"], set(QUERY_PLAN_SQL))
    safe_query_objects = _current_safe_query_objects()
    for plan in plans.values():
        _validate_query_plan(plan, safe_query_objects)
    rendered = json.dumps(value, ensure_ascii=True)
    forbidden = ("history.sqlite3", "benchmark-match-token", "11" * 32, "22" * 32)
    if any(item in rendered for item in forbidden):
        raise BenchmarkFailure("unsafe_benchmark_report")
    allowed_strings = safe_query_objects | {
        "search",
        "scan",
        "temp_btree",
        "other",
    }
    for item in _string_values(value):
        if item not in allowed_strings and re.fullmatch(
            r"[a-z][a-z0-9_]{0,63}", item
        ) is None:
            raise BenchmarkFailure("unsafe_benchmark_report")


def _string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _string_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _string_values(item)


def _exact_mapping(value: Any, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise BenchmarkFailure("invalid_benchmark_result")
    return value


def _nonnegative_integer(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BenchmarkFailure("invalid_benchmark_result")


def _nonnegative_number(value: Any) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        raise BenchmarkFailure("invalid_benchmark_result")


def _validate_latency_mapping(value: Any) -> None:
    latency = _exact_mapping(value, {"p50", "p95", "p99", "max"})
    for item in latency.values():
        _nonnegative_number(item)
    if not latency["p50"] <= latency["p95"] <= latency["p99"] <= latency["max"]:
        raise BenchmarkFailure("invalid_benchmark_result")


def _failure_category(value: Any) -> None:
    if value is not None and (
        not isinstance(value, str)
        or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) is None
    ):
        raise BenchmarkFailure("unsafe_benchmark_report")


def _validate_storage_mapping(value: Any) -> None:
    sample = _exact_mapping(
        value, {"database_bytes", "wal_bytes", "backup_bytes", "total_bytes"}
    )
    for item in sample.values():
        _nonnegative_integer(item)
    if sample["total_bytes"] < max(
        sample["database_bytes"], sample["wal_bytes"], sample["backup_bytes"]
    ):
        raise BenchmarkFailure("invalid_benchmark_result")


def _validate_query_plan(value: Any, safe_query_objects: frozenset[str]) -> None:
    plan = _exact_mapping(value, {"steps", "uses_index", "uses_temp_btree"})
    if (
        not isinstance(plan["steps"], list)
        or not plan["steps"]
        or not isinstance(plan["uses_index"], bool)
        or not isinstance(plan["uses_temp_btree"], bool)
    ):
        raise BenchmarkFailure("invalid_benchmark_result")
    for item in plan["steps"]:
        step = _exact_mapping(item, {"operation", "object", "covering"})
        if (
            step["operation"] not in {"search", "scan", "temp_btree", "other"}
            or (
                step["object"] is not None
                and step["object"] not in safe_query_objects
            )
            or not isinstance(step["covering"], bool)
        ):
            raise BenchmarkFailure("invalid_benchmark_result")


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise BenchmarkFailure("invalid_latency_sample")
    return {
        "p50": _percentile(values, 50),
        "p95": _percentile(values, 95),
        "p99": _percentile(values, 99),
        "max": round(max(values), 3),
    }


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil((percentile / 100) * len(ordered)) - 1)
    return round(ordered[index], 3)


def _elapsed_ms(started: float, ended: float) -> float:
    elapsed = (ended - started) * 1000
    if not math.isfinite(elapsed) or elapsed < 0:
        raise BenchmarkFailure("invalid_clock_sample")
    return round(elapsed, 3)


def _body(size: int, index: int, *, include_hit: bool) -> str:
    prefix = f"fixture-{index:09d}-"
    marker = "benchmark-match-token" if include_hit else ""
    seed = prefix + marker + "x"
    repeats = (size // len(seed)) + 1
    return (seed * repeats)[:size]


def _safe_error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code):
        return code
    return fallback


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() and not path.is_symlink() else 0
    except OSError:
        return 0


def _storage_peak_values(samples: list[StorageSample]) -> dict[str, int]:
    if not samples:
        return _storage_values(StorageSample(0, 0, 0))
    return {
        "database_bytes": max(sample.database_bytes for sample in samples),
        "wal_bytes": max(sample.wal_bytes for sample in samples),
        "backup_bytes": max(sample.backup_bytes for sample in samples),
        "total_bytes": max(sample.total_bytes for sample in samples),
    }


def _storage_values(sample: StorageSample) -> dict[str, int]:
    return {
        "database_bytes": sample.database_bytes,
        "wal_bytes": sample.wal_bytes,
        "backup_bytes": sample.backup_bytes,
        "total_bytes": sample.total_bytes,
    }


def _normalize_query_plan(
    rows: list[tuple[Any, ...]], safe_query_objects: frozenset[str]
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    for row in rows:
        detail = str(row[-1]).upper()
        operation = "other"
        if "USE TEMP B-TREE" in detail:
            operation = "temp_btree"
        elif detail.startswith("SEARCH"):
            operation = "search"
        elif detail.startswith("SCAN"):
            operation = "scan"
        object_name = None
        index_match = re.search(
            r"USING (?:COVERING )?INDEX ([A-Z0-9_]+)", detail
        )
        if index_match is not None:
            candidate = index_match.group(1).lower()
            if candidate in safe_query_objects:
                object_name = candidate
        if object_name is None:
            table_match = re.match(r"(?:SEARCH|SCAN) ([A-Z0-9_]+)", detail)
            if table_match is not None:
                candidate = table_match.group(1).lower()
                if candidate in safe_query_objects:
                    object_name = candidate
        steps.append(
            {
                "operation": operation,
                "object": object_name,
                "covering": "COVERING INDEX" in detail,
            }
        )
    return {
        "steps": steps,
        "uses_index": any(
            step["object"] is not None
            and (step["object"].endswith("_idx") or "autoindex" in step["object"])
            for step in steps
        ),
        "uses_temp_btree": any(step["operation"] == "temp_btree" for step in steps),
    }


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    if not isinstance(path, Path) or path.suffix.lower() != ".json":
        raise ValueError("json-output must use a .json suffix")
    parent = path.parent.resolve()
    if not parent.is_dir():
        raise ValueError("json-output parent must exist")
    serialized = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark the real SQLite history plugin through CapabilityRegistry."
    )
    parser.add_argument("--record-count", type=int, default=DEFAULT_RECORD_COUNT)
    parser.add_argument("--profile", choices=tuple(PROFILE_SIZES), default=DEFAULT_PROFILE)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument(
        "--rotation-batch-size", type=int, default=DEFAULT_ROTATION_BATCH_SIZE
    )
    parser.add_argument(
        "--storage-sample-every", type=int, default=DEFAULT_STORAGE_SAMPLE_EVERY
    )
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_options(
            record_count=args.record_count,
            profile=args.profile,
            page_size=args.page_size,
            rotation_batch_size=args.rotation_batch_size,
            storage_sample_every=args.storage_sample_every,
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2
    report = HistoryBenchmarkRunner().run(
        record_count=args.record_count,
        profile=args.profile,
        page_size=args.page_size,
        rotation_batch_size=args.rotation_batch_size,
        storage_sample_every=args.storage_sample_every,
    )
    if args.json_output is not None:
        try:
            write_report(args.json_output, report)
        except (OSError, ValueError):
            print("report write failed", file=sys.stderr)
            return 2
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
