from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "benchmark_history_sqlite.py"
SPEC = importlib.util.spec_from_file_location("benchmark_history_sqlite", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = benchmark
SPEC.loader.exec_module(benchmark)


def latency(value=1.0):
    return {"p50": value, "p95": value, "p99": value, "max": value}


def plan(*, uses_index=True, uses_temp_btree=False):
    safe_objects = benchmark._current_safe_query_objects()
    index_name = next(name for name in safe_objects if name.endswith("_idx"))
    return {
        "steps": [
            {
                "operation": "search" if uses_index else "scan",
                "object": index_name if uses_index else "history_records",
                "covering": False,
            }
        ],
        "uses_index": uses_index,
        "uses_temp_btree": uses_temp_btree,
    }


def measurements(record_count=10):
    storage = {
        "database_bytes": 1000,
        "wal_bytes": 0,
        "backup_bytes": 0,
        "total_bytes": 1000,
    }
    return {
        "record_count": record_count,
        "save_ms": latency(),
        "pagination": {
            "page_count": 1,
            "record_count": record_count,
            "latency_ms": latency(),
        },
        "search": {"hit_ms": 10.0, "miss_ms": 10.0},
        "export": {
            "first_chunk_ms": 10.0,
            "total_ms": 20.0,
            "chunk_count": 1,
            "raw_bytes": 100,
            "record_count": record_count,
            "failure_category": None,
            "completed": True,
        },
        "rotation": {
            "total_ms": 20.0,
            "prepared": True,
            "finalized": True,
            "failure_category": None,
            "completed": True,
        },
        "storage": {
            "after_load": storage,
            "steady_peak": storage,
            "overall_peak": {
                **storage,
                "backup_bytes": 1000,
                "total_bytes": 2000,
            },
            "final": storage,
        },
        "query_plans": {
            "created_at_page": plan(),
            "provider_filter": plan(),
            "rating_page": plan(),
            "rotation_batch": plan(),
        },
    }


class FakeWorkload:
    instances = []

    def __init__(self):
        self.closed = False
        self.options = None
        type(self).instances.append(self)

    def execute(self, **options):
        self.options = options
        return measurements(options["record_count"])

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_workload():
    FakeWorkload.instances = []


def test_defaults_define_ten_thousand_small_manual_production_gate():
    args = benchmark.build_parser().parse_args([])

    assert args.record_count == 10_000
    assert args.profile == "small"
    assert args.page_size == 100
    assert args.rotation_batch_size == 100
    assert args.storage_sample_every == 100

    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=FakeWorkload
    ).run()
    assert report["plan"]["execution_class"] == "manual_production"
    assert report["plan"]["input_bytes"] == 1024
    assert report["plan"]["output_bytes"] == 4096
    assert report["thresholds"]["applicable"] is True


def test_heavy_profile_uses_exact_body_sizes_and_is_not_default_ci_work():
    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=FakeWorkload
    ).run(record_count=10, profile="heavy", storage_sample_every=10)

    assert report["plan"]["input_bytes"] == 16 * 1024
    assert report["plan"]["output_bytes"] == 64 * 1024
    assert report["plan"]["execution_class"] == "ci_smoke"
    assert report["thresholds"]["applicable"] is False
    assert FakeWorkload.instances[-1].options["profile"].name == "heavy"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("record_count", 0),
        ("record_count", 10_001),
        ("profile", "unknown"),
        ("page_size", 0),
        ("page_size", 101),
        ("rotation_batch_size", 0),
        ("rotation_batch_size", 101),
        ("storage_sample_every", 0),
        ("storage_sample_every", 10_001),
    ),
)
def test_options_reject_unbounded_or_unknown_values(field, value):
    options = {
        "record_count": 10,
        "profile": "small",
        "page_size": 10,
        "rotation_batch_size": 10,
        "storage_sample_every": 10,
    }
    options[field] = value

    with pytest.raises(ValueError):
        benchmark.validate_options(**options)


def test_runner_forwards_options_and_always_cleans_up():
    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=FakeWorkload
    ).run(
        record_count=7,
        profile="small",
        page_size=3,
        rotation_batch_size=2,
        storage_sample_every=7,
    )

    workload = FakeWorkload.instances[-1]
    assert workload.closed is True
    assert workload.options["record_count"] == 7
    assert workload.options["page_size"] == 3
    assert report["result"] == {
        "failure_category": None,
        "cleanup_succeeded": True,
    }
    assert report["passed"] is True


def test_small_smoke_accepts_default_storage_sampling_interval():
    benchmark.validate_options(
        record_count=2,
        profile="small",
        page_size=100,
        rotation_batch_size=100,
        storage_sample_every=100,
    )


def test_ci_smoke_reports_production_threshold_misses_without_failing_smoke():
    class SlowSmoke(FakeWorkload):
        def execute(self, **options):
            value = measurements(options["record_count"])
            value["save_ms"].update(p95=999.0, p99=999.0, max=999.0)
            value["query_plans"]["provider_filter"].update(uses_index=False)
            return value

    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=SlowSmoke
    ).run(record_count=2, storage_sample_every=1)

    assert report["thresholds"]["applicable"] is False
    assert report["thresholds"]["passed"] is False
    assert report["passed"] is True


def test_unexpected_failure_is_redacted_and_cleanup_still_runs():
    class FailingWorkload(FakeWorkload):
        def execute(self, **options):
            raise RuntimeError("secret body C:/private/history.sqlite3")

    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=FailingWorkload
    ).run(record_count=1, storage_sample_every=1)

    assert report["result"]["failure_category"] == "unexpected_failure"
    assert report["result"]["cleanup_succeeded"] is True
    assert report["metrics"] is None
    assert "secret body" not in json.dumps(report)
    assert FailingWorkload.instances[-1].closed is True


def test_report_schema_is_strictly_free_of_bodies_ids_paths_and_keys():
    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=FakeWorkload
    ).run(record_count=10, storage_sample_every=10)
    rendered = json.dumps(report)

    assert set(report) == {
        "schema_version",
        "plan",
        "result",
        "metrics",
        "thresholds",
        "passed",
    }
    for private_value in (
        "benchmark-match-token",
        "benchmark-000000001",
        "history.sqlite3",
        "C:/private",
        "11" * 32,
        "22" * 32,
    ):
        assert private_value not in rendered


def test_unsafe_measurement_string_is_rejected_before_report_output():
    class UnsafeWorkload(FakeWorkload):
        def execute(self, **options):
            value = measurements(options["record_count"])
            value["export"]["failure_category"] = "C:/private/body.txt"
            return value

    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=UnsafeWorkload
    ).run(record_count=1, storage_sample_every=1)

    assert report["result"]["failure_category"] == "unsafe_benchmark_report"
    assert report["metrics"] is None
    assert "C:/private" not in json.dumps(report)


def test_non_finite_or_malformed_measurements_are_rejected():
    class InvalidWorkload(FakeWorkload):
        def execute(self, **options):
            value = measurements(options["record_count"])
            value["save_ms"]["p99"] = float("nan")
            return value

    report = benchmark.HistoryBenchmarkRunner(
        workload_factory=InvalidWorkload
    ).run(record_count=1, storage_sample_every=1)

    assert report["result"]["failure_category"] == "invalid_benchmark_result"
    assert report["metrics"] is None
    assert report["passed"] is False


@pytest.mark.parametrize(
    ("mutation", "failed_check"),
    (
        (lambda value: value["save_ms"].update(p95=30.001), "save_p95"),
        (lambda value: value["save_ms"].update(p99=100.001), "save_p99"),
        (
            lambda value: value["pagination"]["latency_ms"].update(p95=50.001),
            "pagination_p95",
        ),
        (
            lambda value: value["pagination"]["latency_ms"].update(p99=150.001),
            "pagination_p99",
        ),
        (lambda value: value["search"].update(hit_ms=2000.001), "search_hit"),
        (lambda value: value["search"].update(miss_ms=2000.001), "search_miss"),
        (
            lambda value: value["export"].update(first_chunk_ms=500.001),
            "export_first_chunk",
        ),
        (lambda value: value["export"].update(total_ms=10000.001), "export_total"),
        (lambda value: value["rotation"].update(total_ms=30000.001), "rotation_total"),
        (
            lambda value: value["storage"]["steady_peak"].update(total_bytes=2001),
            "steady_storage",
        ),
        (
            lambda value: value["storage"]["overall_peak"].update(total_bytes=3001),
            "rotation_storage",
        ),
        (
            lambda value: value["query_plans"]["created_at_page"].update(
                uses_temp_btree=True
            ),
            "created_at_page_no_temp_sort",
        ),
        (
            lambda value: value["query_plans"]["provider_filter"].update(
                uses_index=False
            ),
            "provider_filter_uses_index",
        ),
        (
            lambda value: value["query_plans"]["rotation_batch"].update(
                uses_index=False
            ),
            "rotation_batch_uses_index",
        ),
    ),
)
def test_each_threshold_can_fail_independently(mutation, failed_check):
    value = measurements(10_000)
    mutation(value)

    result = benchmark.evaluate_thresholds(value, record_count=10_000)

    assert result["checks"][failed_check] is False
    assert result["passed"] is False


def test_failed_export_and_rotation_are_visible_without_private_errors():
    value = measurements(10_000)
    value["export"].update(
        completed=False,
        record_count=None,
        failure_category="history_export_too_large",
    )
    value["rotation"].update(
        completed=False,
        finalized=False,
        failure_category="history_rotation_failed",
    )

    result = benchmark.evaluate_thresholds(value, record_count=10_000)

    assert result["checks"]["export_completed"] is False
    assert result["checks"]["rotation_completed"] is False
    assert result["passed"] is False


def test_query_plan_normalization_whitelists_only_known_objects():
    safe_objects = frozenset({"history_records", "allowed_idx"})
    rows = [
        (1, 0, 0, "SEARCH history_records USING INDEX allowed_idx"),
        (2, 0, 0, "USE TEMP B-TREE FOR ORDER BY"),
        (3, 0, 0, "SCAN private_customer_table"),
    ]

    result = benchmark._normalize_query_plan(rows, safe_objects)

    assert result["steps"] == [
        {
            "operation": "search",
            "object": "allowed_idx",
            "covering": False,
        },
        {"operation": "temp_btree", "object": None, "covering": False},
        {"operation": "scan", "object": None, "covering": False},
    ]
    assert "private_customer_table" not in json.dumps(result)


def test_body_profiles_are_exact_ascii_sizes_and_hit_marker_is_bounded():
    small = benchmark._body(1024, 3, include_hit=False)
    heavy = benchmark._body(64 * 1024, 3, include_hit=True)

    assert len(small.encode("utf-8")) == 1024
    assert len(heavy.encode("utf-8")) == 64 * 1024
    assert "benchmark-match-token" not in small
    assert "benchmark-match-token" in heavy


def test_atomic_report_writer_replaces_target_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "report.json"
    target.write_text("old", encoding="utf-8")
    report = {"schema_version": 1, "passed": True}

    benchmark.write_report(target, report)

    assert json.loads(target.read_text(encoding="utf-8")) == report
    assert list(tmp_path.glob(".report.json.*.tmp")) == []


def test_atomic_report_writer_rejects_unsafe_output_contract(tmp_path):
    with pytest.raises(ValueError):
        benchmark.write_report(tmp_path / "report.txt", {})
    with pytest.raises(ValueError):
        benchmark.write_report(tmp_path / "missing" / "report.json", {})


def test_real_plugin_registry_smoke_uses_all_operations_and_cleans_tempdir():
    workload = benchmark.LocalHistoryBenchmark()
    root = Path(workload._temporary.name)
    try:
        result = workload.execute(
            record_count=3,
            profile=benchmark._profile("small"),
            page_size=2,
            rotation_batch_size=3,
            storage_sample_every=1,
        )
        assert result["record_count"] == 3
        assert result["pagination"]["record_count"] == 3
        assert result["search"]["hit_ms"] >= 0
        assert result["search"]["miss_ms"] >= 0
        assert result["export"]["completed"] is True
        assert result["rotation"]["completed"] is True
        assert set(result["query_plans"]) == set(benchmark.QUERY_PLAN_SQL)
    finally:
        workload.close()

    assert not root.exists()
