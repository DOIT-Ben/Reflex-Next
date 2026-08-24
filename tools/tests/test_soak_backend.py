from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "soak_backend.py"
SPEC = importlib.util.spec_from_file_location("soak_backend", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
soak_backend = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = soak_backend
SPEC.loader.exec_module(soak_backend)


class FakeSession:
    fail_with: Exception | None = None
    closed = False
    batches: list[tuple[int, int, int]] = []

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds

    def run_batch(self, *, first_iteration: int, count: int, cancel_every: int):
        type(self).batches.append((first_iteration, count, cancel_every))
        if type(self).fail_with is not None:
            raise type(self).fail_with
        cancelled = sum(
            1
            for iteration in range(first_iteration, first_iteration + count)
            if iteration % cancel_every == 0
        )
        return soak_backend.BatchResult(
            completed=count - cancelled,
            cancelled=cancelled,
            events=count * 6,
            maximum_queue_depth=count * 2,
        )

    def observe_final_window(self) -> int:
        return 0

    def close(self) -> bool:
        type(self).closed = True
        return True


@pytest.fixture(autouse=True)
def reset_fake_session():
    FakeSession.fail_with = None
    FakeSession.closed = False
    FakeSession.batches = []


def make_runner():
    ticks = iter((0.0, 0.0, 0.1, 0.1, 0.2, 0.2, 1.0))
    return soak_backend.SoakRunner(
        session_factory=FakeSession,
        environment_factory=lambda: {"system": "fixture"},
        utc_clock=lambda: "2026-07-14T00:00:00Z",
        monotonic=lambda: next(ticks, 1.0),
        sleeper=lambda _: None,
    )


def test_runner_counts_completed_and_cancelled_requests_without_bodies():
    report = make_runner().run(
        iterations=10,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
    )

    assert report["passed"] is True
    assert report["result"]["iterations"] == 10
    assert report["result"]["completed_requests"] == 5
    assert report["result"]["cancelled_requests"] == 5
    assert report["result"]["graceful_shutdown"] is True
    assert FakeSession.closed is True
    assert FakeSession.batches == [(1, 4, 2), (5, 4, 2), (9, 2, 2)]
    assert soak_backend.FIXTURE_INPUT not in str(report)
    assert "soak-chunk" not in str(report)


def test_stable_failure_category_is_reported_without_exception_details():
    FakeSession.fail_with = soak_backend.SoakFailure("request_cross_talk")
    report = make_runner().run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
    )

    assert report["passed"] is False
    assert report["result"]["failure_category"] == "request_cross_talk"
    assert FakeSession.closed is True


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("iterations", 0),
        ("iterations", soak_backend.MAX_ITERATIONS + 1),
        ("batch_size", 0),
        ("batch_size", 5),
        ("timeout_seconds", 0),
        ("cancel_every", 1),
        ("duration_hours", soak_backend.MAX_DURATION_HOURS + 1),
        ("rate_per_minute", soak_backend.MAX_RATE_PER_MINUTE + 1),
    ),
)
def test_limits_reject_unbounded_values(field, value):
    values = {
        "iterations": 10,
        "batch_size": 4,
        "timeout_seconds": 5,
        "cancel_every": 2,
        "duration_hours": 0,
        "rate_per_minute": 0,
    }
    values[field] = value
    with pytest.raises(ValueError):
        soak_backend.validate_limits(**values)


def test_duration_soak_requires_an_explicit_bounded_rate():
    with pytest.raises(ValueError, match="rate-per-minute"):
        soak_backend.validate_limits(
            iterations=10_000,
            batch_size=4,
            timeout_seconds=5,
            cancel_every=2,
            duration_hours=72,
            rate_per_minute=0,
        )


def test_iteration_count_must_exercise_at_least_one_cancellation():
    with pytest.raises(ValueError, match="at least cancel-every"):
        soak_backend.validate_limits(
            iterations=3,
            batch_size=3,
            timeout_seconds=5,
            cancel_every=4,
            duration_hours=0,
            rate_per_minute=0,
        )


def test_runtime_environment_does_not_inherit_provider_credentials(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "fixture-private-value")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-private-value")
    child_environment = soak_backend.RuntimeSoakSession._runtime_environment()

    assert child_environment["REFLEX_RUNTIME_DEVELOPMENT"] == "1"
    assert "MINIMAX_API_KEY" not in child_environment
    assert "OPENAI_API_KEY" not in child_environment


def test_cancel_fixture_leaves_a_bounded_window_after_first_chunk():
    state = soak_backend._RequestState(
        request_id="soak-000000002",
        expected_chunk="soak-chunk-000000002",
        should_cancel=True,
    )
    command = soak_backend.RuntimeSoakSession._optimize_command(state)

    assert command["payload"]["metadata"]["delay_ms"] == soak_backend.CANCEL_FIXTURE_DELAY_MS
    assert soak_backend.CANCEL_FIXTURE_DELAY_MS >= 100


def test_summary_contains_counts_but_not_failure_or_fixture_content():
    report = make_runner().run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
    )
    summary = soak_backend.render_human_summary(report)

    assert "4 次" in summary
    assert "完成 2" in summary
    assert "取消 2" in summary
    assert soak_backend.FIXTURE_INPUT not in summary


def test_sliced_sleep_bounds_every_wait_and_covers_the_deadline():
    calls: list[float] = []
    clock = iter((0.0, 0.2, 0.4, 0.6, 0.8, 1.0))
    soak_backend._sliced_sleep(
        1.0,
        slice_seconds=0.3,
        sleeper=lambda seconds: calls.append(seconds),
        monotonic=lambda: next(clock, 1.0),
    )

    assert calls == pytest.approx([0.3, 0.3, 0.3, 0.2])
    assert all(seconds <= 0.3 for seconds in calls)
    assert sum(calls) > 0

