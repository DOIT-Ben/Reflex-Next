#!/usr/bin/env python3
"""Bounded mixed Runtime/history soak with privacy-safe resource reporting."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITERATIONS = 1_000
DEFAULT_WARMUP_ITERATIONS = 100
DEFAULT_SAMPLE_EVERY = 100
MAX_ITERATIONS = 1_000_000
MAX_WARMUP_ITERATIONS = 100_000
MIB = 1024 * 1024
MEMORY_LIMIT_BYTES = 50 * MIB
MEMORY_LIMIT_RATIO = 0.20
FINAL_HANDLE_DELTA_LIMIT = 8
CHECKPOINT_HANDLE_DELTA_LIMIT = 16
FINAL_THREAD_DELTA_LIMIT = 0
CHECKPOINT_THREAD_DELTA_LIMIT = 1
SQLITE_PEAK_ACTIVE_LIMIT = 4
OPERATIONS = ("save", "list", "detail", "rate", "export", "batch_parse")


class SoakFailure(RuntimeError):
    """A stable failure category that never carries private operation content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ResourceSample:
    private_bytes: int
    working_set_bytes: int
    handle_count: int
    thread_count: int
    sqlite_opened: int
    sqlite_active: int
    sqlite_peak_active: int
    database_bytes: int
    wal_bytes: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResourceSample":
        fields = cls.__dataclass_fields__
        if set(value) != set(fields):
            raise SoakFailure("invalid_probe_sample")
        if any(
            not isinstance(value[name], int)
            or isinstance(value[name], bool)
            or value[name] < 0
            for name in fields
        ):
            raise SoakFailure("invalid_probe_sample")
        return cls(**{name: value[name] for name in fields})


class ResourceProbe(Protocol):
    def sample(self, database_path: Path) -> ResourceSample | Mapping[str, Any]: ...


class MixedWorkload(Protocol):
    @property
    def database_path(self) -> Path: ...

    def run_iteration(self, iteration: int, *, warmup: bool) -> Mapping[str, int]: ...

    def storage_sample(self) -> Mapping[str, int]: ...

    def finish(self) -> None: ...

    def close(self) -> None: ...


def validate_limits(*, iterations: int, warmup_iterations: int, sample_every: int) -> None:
    if not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")
    if not 0 <= warmup_iterations <= MAX_WARMUP_ITERATIONS:
        raise ValueError(
            f"warmup-iterations must be between 0 and {MAX_WARMUP_ITERATIONS}"
        )
    if not 1 <= sample_every <= iterations:
        raise ValueError("sample-every must be between 1 and iterations")


def _source_path(name: str) -> Path:
    roots = {
        "core": REPO_ROOT / "packages" / "reflex-core" / "src",
        "runtime": REPO_ROOT / "packages" / "reflex-runtime" / "src",
        "history": REPO_ROOT / "plugins" / "history-sqlite" / "src",
        "batch": REPO_ROOT / "plugins" / "batch-runner" / "src",
    }
    return roots[name]


def _load_local_dependencies() -> tuple[Any, Any, Any, Any, Any, Any]:
    for name in ("batch", "history", "runtime", "core"):
        source = str(_source_path(name))
        if source not in sys.path:
            sys.path.insert(0, source)
    from reflex_core import CancellationToken
    from reflex_history_sqlite.plugin import HistorySqlitePlugin
    from reflex_history_sqlite.repository import HistoryRepository
    from reflex_batch_runner.plugin import BatchRunnerPlugin
    from reflex_runtime.capability_registry import CapabilityRegistry
    from reflex_runtime.plugin_contracts import PluginDescriptor

    return (
        CancellationToken,
        HistorySqlitePlugin,
        HistoryRepository,
        CapabilityRegistry,
        PluginDescriptor,
        BatchRunnerPlugin,
    )


class LocalPluginHistoryWorkload:
    """Exercise history through the Runtime capability policy boundary."""

    def __init__(self) -> None:
        (
            self._cancellation_type,
            history_type,
            repository_type,
            registry_type,
            descriptor_type,
            batch_type,
        ) = _load_local_dependencies()
        self._temporary = tempfile.TemporaryDirectory(prefix="reflex-history-soak-")
        root = Path(self._temporary.name).resolve()
        self._database_path = root / "history" / "history.sqlite3"
        self._connections = {"opened": 0, "active": 0, "peak_active": 0}
        connection_metrics = self._connections

        class TrackedRepository(repository_type):
            @contextmanager
            def _connection(self, *args: Any, **kwargs: Any):
                connection_metrics["opened"] += 1
                connection_metrics["active"] += 1
                connection_metrics["peak_active"] = max(
                    connection_metrics["peak_active"], connection_metrics["active"]
                )
                try:
                    with super()._connection(*args, **kwargs) as connection:
                        yield connection
                finally:
                    connection_metrics["active"] -= 1

        class TrackedHistoryPlugin(history_type):
            def _repository(self, services: Any):
                return TrackedRepository(services, schema_lock=self._schema_lock)

        history = TrackedHistoryPlugin()
        batch = batch_type()

        def descriptor_for(capability: Any) -> Any:
            source = capability.descriptor
            return descriptor_type(
                plugin_id=source.plugin_id,
                display_name=source.display_name,
                version=source.version,
                kind=source.kind,
                permissions=source.permissions,
                operations=source.operations,
                public_operations=source.public_operations,
            )

        self._registry = registry_type(
            [(descriptor_for(history), history), (descriptor_for(batch), batch)],
            enabled_plugins={"batch-runner"},
        )
        self._registry.configure_history_keys({"v1": "11" * 32})
        self._registry.configure_history_path(self._database_path)
        self._registry.configure_history_policy(
            history_enabled=True,
            privacy_mode=False,
            history_redaction="secrets",
        )
        self._record_ids: list[str] = []
        self._closed = False

    @property
    def database_path(self) -> Path:
        return self._database_path

    def run_iteration(self, iteration: int, *, warmup: bool) -> Mapping[str, int]:
        if self._closed:
            raise SoakFailure("workload_closed")
        phase = "warmup" if warmup else "measured"
        record_id = f"{phase}-{iteration:09d}"
        cancellation = self._cancellation_type()
        operation = OPERATIONS[(iteration - 1) % len(OPERATIONS)]
        if operation == "save":
            self._registry.invoke_internal(
                "history-sqlite",
                "save",
                {
                    "id": record_id,
                    "created_at": "2026-01-01T00:00:00.000Z",
                    "input": "local soak input",
                    "output": "local soak output",
                    "mode": "content",
                    "style": "concise",
                    "scene": "coding",
                    "provider": "mock",
                    "model": "mock-stream",
                    "elapsed_ms": 1,
                    "status": "completed",
                    "tags": ["soak"],
                },
                {},
                cancellation,
                trusted=True,
            )
            self._record_ids.append(record_id)
        elif operation == "list":
            self._registry.invoke_public(
                "history-sqlite", "list", {"page_size": 10}, {}, cancellation
            )
        elif operation == "detail":
            self._registry.invoke_public(
                "history-sqlite",
                "detail",
                {"id": self._latest_record_id()},
                {},
                cancellation,
            )
        elif operation == "rate":
            self._registry.invoke_public(
                "history-sqlite",
                "rate",
                {"id": self._latest_record_id(), "rating": (iteration % 5) + 1},
                {},
                cancellation,
            )
        elif operation == "export":
            export_events = self._registry.invoke_admin(
                "history-sqlite",
                "export",
                {"format": "json", "filters": {}},
                {},
                cancellation,
            )
            for _ in export_events:
                pass
        else:
            self._registry.invoke_public(
                "batch-runner",
                "parse",
                {"format": "txt", "content": "first fixture\nsecond fixture"},
                {},
                cancellation,
            )
        return {operation: 1}

    def _latest_record_id(self) -> str:
        if not self._record_ids:
            raise SoakFailure("history_fixture_unavailable")
        return self._record_ids[-1]

    def finish(self) -> None:
        return None

    def storage_sample(self) -> Mapping[str, int]:
        wal_path = self._database_path.with_name(f"{self._database_path.name}-wal")
        return {
            "sqlite_opened": self._connections["opened"],
            "sqlite_active": self._connections["active"],
            "sqlite_peak_active": self._connections["peak_active"],
            "database_bytes": self._database_path.stat().st_size
            if self._database_path.is_file()
            else 0,
            "wal_bytes": wal_path.stat().st_size if wal_path.is_file() else 0,
        }

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._temporary.cleanup()


class _WindowsCompositeProbe:
    def __init__(self, workload: MixedWorkload, process_sampler: Callable[[int], Any]) -> None:
        self._workload = workload
        self._process_sampler = process_sampler

    def sample(self, database_path: Path) -> Mapping[str, int]:
        process = self._process_sampler(os.getpid())
        process_values = {
            name: getattr(process, name)
            for name in (
                "private_bytes",
                "working_set_bytes",
                "handle_count",
                "thread_count",
            )
        }
        return {**process_values, **dict(self._workload.storage_sample())}


def _default_probe_factory(workload: MixedWorkload) -> ResourceProbe:
    try:
        from windows_resource_probe import sample_process
    except ImportError as error:
        raise SoakFailure("resource_probe_unavailable") from error
    return _WindowsCompositeProbe(workload, sample_process)


def _operation_counts(value: Mapping[str, int]) -> Counter[str]:
    if (
        not isinstance(value, Mapping)
        or set(value) - set(OPERATIONS)
        or any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in value.values()
        )
    ):
        raise SoakFailure("invalid_workload_result")
    return Counter(value)


def _sample(probe: ResourceProbe, database_path: Path) -> ResourceSample:
    value = probe.sample(database_path)
    if isinstance(value, ResourceSample):
        return value
    if not isinstance(value, Mapping):
        raise SoakFailure("invalid_probe_sample")
    return ResourceSample.from_mapping(value)


def _threshold_result(
    baseline: ResourceSample,
    checkpoints: list[ResourceSample],
    final: ResourceSample,
) -> dict[str, Any]:
    memory_limit = min(int(baseline.private_bytes * MEMORY_LIMIT_RATIO), MEMORY_LIMIT_BYTES)
    private_delta = final.private_bytes - baseline.private_bytes
    handle_deltas = [sample.handle_count - baseline.handle_count for sample in checkpoints]
    thread_deltas = [sample.thread_count - baseline.thread_count for sample in checkpoints]
    active_values = [sample.sqlite_active for sample in checkpoints]
    peak_active = max(
        [baseline.sqlite_peak_active, final.sqlite_peak_active]
        + [sample.sqlite_peak_active for sample in checkpoints]
    )
    checks = {
        "private_bytes": private_delta <= memory_limit,
        "checkpoint_handles": all(delta <= CHECKPOINT_HANDLE_DELTA_LIMIT for delta in handle_deltas),
        "final_handles": final.handle_count - baseline.handle_count <= FINAL_HANDLE_DELTA_LIMIT,
        "checkpoint_threads": all(delta <= CHECKPOINT_THREAD_DELTA_LIMIT for delta in thread_deltas),
        "final_threads": final.thread_count - baseline.thread_count == FINAL_THREAD_DELTA_LIMIT,
        "sqlite_active": all(value == 0 for value in active_values) and final.sqlite_active == 0,
        "sqlite_peak_active": peak_active <= SQLITE_PEAK_ACTIVE_LIMIT,
    }
    return {
        "limits": {
            "private_bytes_delta": memory_limit,
            "checkpoint_handle_delta": CHECKPOINT_HANDLE_DELTA_LIMIT,
            "final_handle_delta": FINAL_HANDLE_DELTA_LIMIT,
            "checkpoint_thread_delta": CHECKPOINT_THREAD_DELTA_LIMIT,
            "final_thread_delta": FINAL_THREAD_DELTA_LIMIT,
            "sqlite_active": 0,
            "sqlite_peak_active": SQLITE_PEAK_ACTIVE_LIMIT,
        },
        "checks": checks,
        "passed": all(checks.values()),
    }


class PluginHistorySoakRunner:
    def __init__(
        self,
        *,
        workload_factory: Callable[[], MixedWorkload] = LocalPluginHistoryWorkload,
        probe_factory: Callable[[MixedWorkload], ResourceProbe] = _default_probe_factory,
    ) -> None:
        self._workload_factory = workload_factory
        self._probe_factory = probe_factory

    def run(
        self,
        *,
        iterations: int = DEFAULT_ITERATIONS,
        warmup_iterations: int = DEFAULT_WARMUP_ITERATIONS,
        sample_every: int = DEFAULT_SAMPLE_EVERY,
    ) -> dict[str, Any]:
        validate_limits(
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            sample_every=sample_every,
        )
        completed_warmup = 0
        completed_iterations = 0
        operation_counts: Counter[str] = Counter()
        checkpoints: list[ResourceSample] = []
        baseline: ResourceSample | None = None
        final: ResourceSample | None = None
        failure_category: str | None = None
        workload: MixedWorkload | None = None
        try:
            workload = self._workload_factory()
            probe = self._probe_factory(workload)
            for iteration in range(1, warmup_iterations + 1):
                _operation_counts(workload.run_iteration(iteration, warmup=True))
                completed_warmup += 1
            baseline = _sample(probe, workload.database_path)
            for iteration in range(1, iterations + 1):
                operation_counts.update(
                    _operation_counts(workload.run_iteration(iteration, warmup=False))
                )
                completed_iterations += 1
                if iteration % sample_every == 0 and iteration != iterations:
                    checkpoints.append(_sample(probe, workload.database_path))
            workload.finish()
            final = _sample(probe, workload.database_path)
        except SoakFailure as error:
            failure_category = error.code
        except Exception:
            failure_category = "unexpected_failure"
        finally:
            if workload is not None:
                try:
                    workload.close()
                except Exception:
                    if failure_category is None:
                        failure_category = "workload_cleanup_failed"

        thresholds = None
        if baseline is not None and final is not None:
            thresholds = _threshold_result(baseline, checkpoints, final)
        passed = (
            failure_category is None
            and completed_warmup == warmup_iterations
            and completed_iterations == iterations
            and thresholds is not None
            and thresholds["passed"]
        )
        resources = _resource_report(baseline, checkpoints, final)
        storage = {
            "database_bytes": final.database_bytes if final is not None else None,
            "wal_bytes": final.wal_bytes if final is not None else None,
        }
        return {
            "schema_version": 1,
            "plan": {
                "warmup_iterations": warmup_iterations,
                "iterations": iterations,
                "sample_every": sample_every,
            },
            "result": {
                "completed_warmup": completed_warmup,
                "completed_iterations": completed_iterations,
                "checkpoint_samples": len(checkpoints) + (1 if final is not None else 0),
                "operation_counts": {
                    operation: operation_counts[operation] for operation in OPERATIONS
                },
                "failure_category": failure_category,
            },
            "resources": resources,
            "storage": storage,
            "thresholds": thresholds,
            "passed": passed,
        }


def _resource_report(
    baseline: ResourceSample | None,
    checkpoints: list[ResourceSample],
    final: ResourceSample | None,
) -> dict[str, Any] | None:
    if baseline is None or final is None:
        return None
    return {
        "baseline": _resource_values(baseline),
        "final": _resource_values(final),
        "maximum_checkpoint": {
            name: max(getattr(sample, name) for sample in [*checkpoints, final])
            for name in (
                "private_bytes",
                "working_set_bytes",
                "handle_count",
                "thread_count",
                "sqlite_opened",
                "sqlite_active",
                "sqlite_peak_active",
            )
        },
        "delta": {
            "private_bytes": final.private_bytes - baseline.private_bytes,
            "working_set_bytes": final.working_set_bytes - baseline.working_set_bytes,
            "handle_count": final.handle_count - baseline.handle_count,
            "thread_count": final.thread_count - baseline.thread_count,
            "sqlite_opened": final.sqlite_opened - baseline.sqlite_opened,
        },
    }


def _resource_values(sample: ResourceSample) -> dict[str, int]:
    return {
        "private_bytes": sample.private_bytes,
        "working_set_bytes": sample.working_set_bytes,
        "handle_count": sample.handle_count,
        "thread_count": sample.thread_count,
        "sqlite_opened": sample.sqlite_opened,
        "sqlite_active": sample.sqlite_active,
        "sqlite_peak_active": sample.sqlite_peak_active,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded mixed Runtime plugin and SQLite history soak."
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument(
        "--warmup-iterations", type=int, default=DEFAULT_WARMUP_ITERATIONS
    )
    parser.add_argument("--sample-every", type=int, default=DEFAULT_SAMPLE_EVERY)
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_limits(
            iterations=args.iterations,
            warmup_iterations=args.warmup_iterations,
            sample_every=args.sample_every,
        )
    except ValueError as error:
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2
    report = PluginHistorySoakRunner().run(
        iterations=args.iterations,
        warmup_iterations=args.warmup_iterations,
        sample_every=args.sample_every,
    )
    serialized = json.dumps(report, ensure_ascii=True, indent=2)
    if args.json_output is not None:
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
