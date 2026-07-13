from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "benchmark_backend.py"
SPEC = importlib.util.spec_from_file_location("benchmark_backend", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark_backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark_backend)


class FakeSession:
    cold_values = iter(())
    warm_up_calls = 0

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def ping_latency_ms(self) -> float:
        return next(self.cold_values)

    def warm_up(self) -> None:
        type(self).warm_up_calls += 1

    def optimize_latencies_ms(self) -> dict[str, float]:
        return {
            "runtime_first_status": 10.0,
            "provider_first_chunk": 20.0,
            "total_duration": 30.0,
        }

    def cancellation_latency_ms(self) -> float:
        return 15.0


def test_percentiles_use_nearest_rank_and_keep_tail_visible():
    assert benchmark_backend.calculate_percentiles([1, 2, 3, 4, 100]) == {
        "p50_ms": 3.0,
        "p95_ms": 100.0,
        "p99_ms": 100.0,
    }


def test_runner_emits_complete_bounded_report_without_fixture_bodies():
    FakeSession.cold_values = iter([100.0, 110.0, 120.0])
    FakeSession.warm_up_calls = 0
    runner = benchmark_backend.BenchmarkRunner(
        session_factory=FakeSession,
        environment_factory=lambda: {"system": "fixture-os"},
        clock=lambda: "2026-07-14T00:00:00Z",
    )

    report = runner.run(samples=3, timeout_seconds=2.0)

    assert report["schema_version"] == 1
    assert report["fixture"] == "local_mock"
    assert report["sample_count"] == 3
    assert report["timeout_seconds"] == 2.0
    assert set(report["metrics"]) == set(benchmark_backend.METRIC_THRESHOLDS_MS)
    assert report["metrics"]["cold_start"]["p95_ms"] == 120.0
    assert report["metrics"]["cold_start"]["failures"] == 0
    assert report["metrics"]["cancellation_latency"]["threshold_passed"] is True
    assert report["overall_threshold_passed"] is True
    assert FakeSession.warm_up_calls == 1

    visible = json.dumps(report, ensure_ascii=False)
    assert benchmark_backend.FIXTURE_INPUT not in visible
    assert benchmark_backend.FIXTURE_CHUNK not in visible
    assert "prompt" not in visible.lower()
    assert "response" not in visible.lower()


def test_failed_samples_are_counted_without_exposing_exception_text():
    class FailingSession(FakeSession):
        cold_values = iter([100.0, RuntimeError("private fixture failure")])

        def ping_latency_ms(self) -> float:
            value = next(self.cold_values)
            if isinstance(value, Exception):
                raise value
            return value

    report = benchmark_backend.BenchmarkRunner(
        session_factory=FailingSession,
        environment_factory=dict,
        clock=lambda: "2026-07-14T00:00:00Z",
    ).run(samples=2, timeout_seconds=1.0)

    cold = report["metrics"]["cold_start"]
    assert cold["successful_samples"] == 1
    assert cold["failures"] == 1
    assert cold["threshold_passed"] is False
    assert "private fixture failure" not in json.dumps(report)
    assert report["overall_threshold_passed"] is False


@pytest.mark.parametrize("samples", [0, benchmark_backend.MAX_SAMPLES + 1])
def test_sample_count_is_rejected_outside_safe_bounds(samples):
    with pytest.raises(ValueError, match="samples"):
        benchmark_backend.validate_limits(samples, 1.0)


@pytest.mark.parametrize("timeout_seconds", [0, benchmark_backend.MAX_TIMEOUT_SECONDS + 0.1])
def test_timeout_is_rejected_outside_safe_bounds(timeout_seconds):
    with pytest.raises(ValueError, match="timeout"):
        benchmark_backend.validate_limits(1, timeout_seconds)


def test_human_summary_contains_thresholds_but_not_raw_samples():
    FakeSession.cold_values = iter([100.0])
    report = benchmark_backend.BenchmarkRunner(
        session_factory=FakeSession,
        environment_factory=dict,
        clock=lambda: "2026-07-14T00:00:00Z",
    ).run(samples=1, timeout_seconds=1.0)

    summary = benchmark_backend.render_human_summary(report)

    assert "P50/P95/P99" in summary
    assert "冷启动" in summary
    assert "通过" in summary
    assert "raw" not in summary.lower()


def test_runtime_environment_does_not_inherit_provider_credentials(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "private-fixture-value")
    monkeypatch.setenv("OPENAI_API_KEY", "another-private-fixture-value")

    child_environment = benchmark_backend.RuntimeSession._runtime_environment()

    assert "MINIMAX_API_KEY" not in child_environment
    assert "OPENAI_API_KEY" not in child_environment
    assert child_environment["REFLEX_RUNTIME_DEVELOPMENT"] == "1"
