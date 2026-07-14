from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "soak_plugin_history.py"
SPEC = importlib.util.spec_from_file_location("soak_plugin_history", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
soak = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = soak
SPEC.loader.exec_module(soak)


def sample(**changes):
    values = {
        "private_bytes": 100 * soak.MIB,
        "working_set_bytes": 80 * soak.MIB,
        "handle_count": 100,
        "thread_count": 10,
        "sqlite_opened": 100,
        "sqlite_active": 0,
        "sqlite_peak_active": 2,
        "database_bytes": 4096,
        "wal_bytes": 0,
    }
    values.update(changes)
    return soak.ResourceSample(**values)


class FakeWorkload:
    instances = []

    def __init__(self):
        self.database_path = Path("C:/private/history/history.sqlite3")
        self.calls = []
        self.finished = False
        self.closed = False
        type(self).instances.append(self)

    def run_iteration(self, iteration, *, warmup):
        self.calls.append((iteration, warmup))
        return {operation: 1 for operation in soak.OPERATIONS}

    def finish(self):
        self.finished = True

    def storage_sample(self):
        raise AssertionError("the injected combined probe owns fixture storage metrics")

    def close(self):
        self.closed = True


class FakeProbe:
    def __init__(self, samples):
        self.samples = iter(samples)
        self.paths = []

    def sample(self, database_path):
        self.paths.append(database_path)
        return next(self.samples)


@pytest.fixture(autouse=True)
def reset_workload():
    FakeWorkload.instances = []


def run_with(samples, **changes):
    values = {"iterations": 4, "warmup_iterations": 2, "sample_every": 2}
    values.update(changes)
    probe = FakeProbe(samples)
    report = soak.PluginHistorySoakRunner(
        workload_factory=FakeWorkload,
        probe_factory=lambda _: probe,
    ).run(**values)
    return report, probe, FakeWorkload.instances[-1]


def test_runner_warms_up_samples_and_counts_only_measured_operations():
    report, probe, workload = run_with(
        [sample(), sample(handle_count=110), sample(private_bytes=110 * soak.MIB)]
    )

    assert report["passed"] is True
    assert report["result"] == {
        "completed_warmup": 2,
        "completed_iterations": 4,
        "checkpoint_samples": 2,
        "operation_counts": {operation: 4 for operation in soak.OPERATIONS},
        "failure_category": None,
    }
    assert workload.calls == [
        (1, True),
        (2, True),
        (1, False),
        (2, False),
        (3, False),
        (4, False),
    ]
    assert workload.finished is True
    assert workload.closed is True
    assert probe.paths == [workload.database_path] * 3


def test_report_is_structurally_free_of_bodies_ids_paths_and_keys():
    report, _, _ = run_with([sample(), sample(), sample()])
    rendered = json.dumps(report)

    for private_value in (
        "local soak input",
        "local soak output",
        "measured-000000001",
        "history.sqlite3",
        "C:/private",
        "11" * 32,
    ):
        assert private_value not in rendered
    assert set(report) == {
        "schema_version",
        "plan",
        "result",
        "resources",
        "storage",
        "thresholds",
        "passed",
    }


def test_thresholds_enforce_memory_handle_thread_and_sqlite_limits():
    baseline = sample()
    checkpoint = sample(handle_count=116, thread_count=11, sqlite_active=0)
    final = sample(
        private_bytes=120 * soak.MIB,
        handle_count=108,
        thread_count=10,
        sqlite_active=0,
        sqlite_peak_active=4,
    )
    report, _, _ = run_with([baseline, checkpoint, final])

    assert report["passed"] is True
    assert report["thresholds"]["limits"]["private_bytes_delta"] == 20 * soak.MIB
    assert all(report["thresholds"]["checks"].values())


@pytest.mark.parametrize(
    ("checkpoint", "final", "failed_check"),
    (
        (sample(), sample(private_bytes=120 * soak.MIB + 1), "private_bytes"),
        (sample(handle_count=117), sample(), "checkpoint_handles"),
        (sample(), sample(handle_count=109), "final_handles"),
        (sample(thread_count=12), sample(), "checkpoint_threads"),
        (sample(), sample(thread_count=11), "final_threads"),
        (sample(sqlite_active=1), sample(), "sqlite_active"),
        (sample(), sample(sqlite_peak_active=5), "sqlite_peak_active"),
    ),
)
def test_each_resource_limit_fails_independently(checkpoint, final, failed_check):
    report, _, _ = run_with([sample(), checkpoint, final])

    assert report["passed"] is False
    assert report["thresholds"]["checks"][failed_check] is False


def test_memory_limit_is_capped_at_fifty_mib_for_large_baseline():
    baseline = sample(private_bytes=500 * soak.MIB)
    final = sample(private_bytes=550 * soak.MIB)
    report, _, _ = run_with([baseline, baseline, final])

    assert report["thresholds"]["limits"]["private_bytes_delta"] == 50 * soak.MIB
    assert report["passed"] is True


def test_probe_mapping_must_have_exact_non_negative_integer_fields():
    value = sample().__dict__.copy()
    value["private_bytes"] = -1
    report, _, workload = run_with([value])

    assert report["passed"] is False
    assert report["result"]["failure_category"] == "invalid_probe_sample"
    assert workload.closed is True


def test_unexpected_workload_failure_is_redacted_and_cleanup_runs():
    class FailingWorkload(FakeWorkload):
        def run_iteration(self, iteration, *, warmup):
            raise RuntimeError("private body and request id")

    report = soak.PluginHistorySoakRunner(
        workload_factory=FailingWorkload,
        probe_factory=lambda _: FakeProbe([sample()]),
    ).run(iterations=1, warmup_iterations=1, sample_every=1)

    assert report["result"]["failure_category"] == "unexpected_failure"
    assert "private body" not in json.dumps(report)
    assert FailingWorkload.instances[-1].closed is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("iterations", 0),
        ("iterations", soak.MAX_ITERATIONS + 1),
        ("warmup_iterations", -1),
        ("warmup_iterations", soak.MAX_WARMUP_ITERATIONS + 1),
        ("sample_every", 0),
        ("sample_every", 11),
    ),
)
def test_limits_reject_unbounded_values(field, value):
    values = {"iterations": 10, "warmup_iterations": 2, "sample_every": 2}
    values[field] = value
    with pytest.raises(ValueError):
        soak.validate_limits(**values)


def test_default_plan_matches_production_soak_budget():
    parser = soak.build_parser()
    args = parser.parse_args([])

    assert args.iterations == 1_000
    assert args.warmup_iterations == 100
    assert args.sample_every == 100
