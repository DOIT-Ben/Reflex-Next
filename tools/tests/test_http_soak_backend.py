"""Contract tests for the HTTP host concurrency soak tool (no network)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "http_soak_backend.py"
SPEC = importlib.util.spec_from_file_location("http_soak_backend", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
http_soak = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = http_soak
SPEC.loader.exec_module(http_soak)


def make_runner(fake_client_factory):
    return http_soak.SoakRunner(client_factory=fake_client_factory)


def test_runner_counts_completed_and_cancelled_without_bodies():
    runner = make_runner(
        lambda request_id, timeout: http_soak.FakeClient(cancel_every=2)
    )
    report = runner.run(levels=[1, 4], iterations=8, cancel_every=2, timeout_seconds=5.0)

    assert report["passed"] is True
    for level in report["levels"]:
        assert level["completed_requests"] + level["cancelled_requests"] == 8
        assert level["completed_requests"] == 4
        assert level["cancelled_requests"] == 4
        assert level["failures"] == []
        assert level["cross_talk_requests"] == 0
        assert level["missing_terminal_requests"] == 0
        assert level["latency_ms_p50"] is not None


def test_cancel_every_drives_cancellation_requests():
    cancelled_ids: list[str] = []

    class RecordingClient(http_soak.FakeClient):
        def __init__(self):
            super().__init__(cancel_every=2)

        def cancel(self, request_id: str) -> None:
            cancelled_ids.append(request_id)
            super().cancel(request_id)

    runner = make_runner(lambda request_id, timeout: RecordingClient())
    report = runner.run(levels=[2], iterations=4, cancel_every=2, timeout_seconds=5.0)

    assert report["levels"][0]["cancelled_requests"] == 2
    assert len(cancelled_ids) == 2
    assert "http-soak" in cancelled_ids[0]


def test_runtime_busy_is_counted_not_failed():
    class HalfBusyClient(http_soak.FakeClient):
        def __init__(self):
            super().__init__(cancel_every=4)

        def optimize(
            self,
            request_id: str,
            *,
            cancel: bool = False,
            on_envelope=None,
        ):
            offset = int(request_id.rsplit("-", 1)[1])
            if offset % 2 == 0:
                return [
                    {
                        "version": 1,
                        "request_id": request_id,
                        "event": {"type": "error", "data": {"code": "runtime_busy"}},
                    }
                ]
            return super().optimize(request_id, cancel=cancel, on_envelope=on_envelope)

    runner = make_runner(lambda request_id, timeout: HalfBusyClient())
    report = runner.run(levels=[2], iterations=4, cancel_every=4, timeout_seconds=5.0)

    level = report["levels"][0]
    assert level["passed"] is True
    assert level["busy_requests"] == 2
    assert level["completed_requests"] == 2
    assert level["failures"] == []


def test_cross_talk_is_detected():
    class CrossTalkClient(http_soak.FakeClient):
        def optimize(
            self,
            request_id: str,
            *,
            cancel: bool = False,
            on_envelope=None,
        ):
            envelopes = super().optimize(request_id, cancel=cancel, on_envelope=on_envelope)
            envelopes.append(
                {"version": 1, "request_id": "someone-else", "event": {"type": "chunk", "data": {}}}
            )
            return envelopes

    runner = make_runner(lambda request_id, timeout: CrossTalkClient())
    report = runner.run(levels=[1], iterations=4, cancel_every=4, timeout_seconds=5.0)

    assert report["passed"] is False
    assert report["levels"][0]["cross_talk_requests"] == 4


def test_missing_terminal_is_detected():
    class NoTerminalClient(http_soak.FakeClient):
        def optimize(
            self,
            request_id: str,
            *,
            cancel: bool = False,
            on_envelope=None,
        ):
            envelopes = [
                {"version": 1, "request_id": request_id, "event": {"type": "chunk", "data": {}}}
            ]
            if on_envelope is not None:
                for envelope in envelopes:
                    on_envelope(envelope)
            return envelopes

    runner = make_runner(lambda request_id, timeout: NoTerminalClient())
    report = runner.run(levels=[1], iterations=4, cancel_every=4, timeout_seconds=5.0)

    assert report["passed"] is False
    assert report["levels"][0]["missing_terminal_requests"] == 4


def test_expected_cancellation_missing_is_a_failure():
    class NoCancelClient(http_soak.FakeClient):
        def optimize(
            self,
            request_id: str,
            *,
            cancel: bool = False,
            on_envelope=None,
        ):
            envelopes = [
                {"version": 1, "request_id": request_id, "event": {"type": "chunk", "data": {}}},
                {"version": 1, "request_id": request_id, "event": {"type": "metric", "data": {}}},
            ]
            if on_envelope is not None:
                for envelope in envelopes:
                    on_envelope(envelope)
            return envelopes

    runner = make_runner(lambda request_id, timeout: NoCancelClient())
    report = runner.run(levels=[1], iterations=4, cancel_every=2, timeout_seconds=5.0)

    assert report["passed"] is False
    assert report["levels"][0]["failures"] == ["expected_cancellation_missing"]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("levels", []),
        ("levels", [0]),
        ("levels", [http_soak.MAX_LEVELS + 1]),
        ("iterations", 0),
        ("iterations", http_soak.MAX_ITERATIONS + 1),
        ("cancel_every", 1),
        ("timeout_seconds", 0),
        ("timeout_seconds", http_soak.MAX_TIMEOUT_SECONDS + 1),
    ),
)
def test_limits_reject_unbounded_values(field, value):
    values = {
        "levels": [1, 4],
        "iterations": 10,
        "cancel_every": 2,
        "timeout_seconds": 5.0,
    }
    values[field] = value
    with pytest.raises(ValueError):
        http_soak.validate_limits(**values)


def test_iterations_must_exercise_at_least_one_cancellation():
    with pytest.raises(ValueError, match="at least cancel-every"):
        http_soak.validate_limits(
            levels=[1],
            iterations=3,
            cancel_every=4,
            timeout_seconds=5.0,
        )


def test_http_error_gets_one_retry():
    class FlakyClient(http_soak.FakeClient):
        def __init__(self):
            super().__init__(cancel_every=4)

        def optimize(
            self,
            request_id: str,
            *,
            cancel: bool = False,
            on_envelope=None,
        ):
            if request_id.endswith("-r"):
                return super().optimize(request_id, cancel=cancel, on_envelope=on_envelope)
            raise RuntimeError("boom")

    runner = make_runner(lambda request_id, timeout: FlakyClient())
    report = runner.run(levels=[1], iterations=4, cancel_every=4, timeout_seconds=5.0)

    level = report["levels"][0]
    assert level["passed"] is True
    assert level["retried_requests"] == 4
    assert level["failures"] == []


def test_report_contains_no_request_bodies():
    runner = make_runner(lambda request_id, timeout: http_soak.FakeClient())
    report = runner.run(levels=[1], iterations=4, cancel_every=2, timeout_seconds=5.0)

    assert "reflex http soak fixture" not in str(report)
    assert "text" not in str(report["levels"])
