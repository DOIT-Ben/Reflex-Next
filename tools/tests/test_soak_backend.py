from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
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


def test_runner_writes_running_heartbeats_and_final_status_atomically(tmp_path, monkeypatch):
    writes = []
    real_writer = soak_backend.write_json_report

    def capture(path, report):
        real_writer(path, report)
        writes.append(json.loads(path.read_text(encoding="utf-8")))

    monkeypatch.setattr(soak_backend, "write_json_report", capture)
    report = make_runner().run(
        iterations=10,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
        report_path=tmp_path / "soak.json",
    )

    assert writes[0]["status"] == "running"
    assert any(item["status"] == "running" and item["result"]["iterations"] == 4 for item in writes)
    assert writes[-1]["status"] == "passed"
    assert writes[-1]["passed"] is True
    assert list(tmp_path.glob(".*.tmp")) == []


def test_runner_fails_when_final_observation_has_late_events():
    class ResidualEventSession(FakeSession):
        def observe_final_window(self) -> int:
            return 1

    runner = soak_backend.SoakRunner(
        session_factory=ResidualEventSession,
        environment_factory=lambda: {"system": "fixture"},
        utc_clock=lambda: "2026-07-14T00:00:00Z",
        monotonic=lambda: 1.0,
        sleeper=lambda _: None,
    )

    report = runner.run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
    )

    assert report["passed"] is False
    assert report["status"] == "failed"
    assert report["result"]["final_observation_events"] == 1
    assert report["result"]["failure_category"] == "late_protocol_event"


def make_status_report(*, pid: int, heartbeat: str) -> dict:
    return {
        "schema_version": 1,
        "status": "running",
        "fixture": "local_mock",
        "pid": pid,
        "process_started_at_utc": soak_backend._process_start_time_utc(pid),
        "started_at_utc": heartbeat,
        "finished_at_utc": None,
        "last_heartbeat_utc": heartbeat,
        "environment": {
            "system": "fixture",
            "system_release": "fixture",
            "architecture": "fixture",
            "processor": "fixture",
            "logical_cpu_count": 1,
            "python_version": "3.12.0",
        },
        "plan": {
            "minimum_iterations": 10,
            "minimum_duration_hours": 0,
            "batch_size": 4,
            "cancel_every": 2,
            "rate_per_minute": 0,
            "batch_timeout_seconds": 5,
        },
        "result": {
            "iterations": 0,
            "completed_requests": 0,
            "cancelled_requests": 0,
            "protocol_events": 0,
            "maximum_queue_depth": 0,
            "final_observation_events": 0,
            "elapsed_seconds": 0,
            "graceful_shutdown": False,
            "failure_category": None,
        },
        "passed": False,
    }

def test_status_command_reads_a_report_without_starting_a_session(tmp_path, capsys):
    path = tmp_path / "soak.json"
    path.write_text(
        json.dumps(make_status_report(pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()))
        + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 0
    output = capsys.readouterr().out
    assert '"status": "running"' in output
    assert '"observed_pid_alive": true' in output
    assert '"heartbeat_stale": false' in output


def test_status_command_marks_a_dead_running_process_as_stale(tmp_path, capsys):
    path = tmp_path / "stale.json"
    path.write_text(
        json.dumps(make_status_report(pid=99999999, heartbeat=datetime.now(timezone.utc).isoformat()))
        + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 1
    output = capsys.readouterr().out
    assert '"stale": true' in output


def test_status_command_marks_an_alive_process_with_a_stale_heartbeat(tmp_path, capsys):
    path = tmp_path / "heartbeat-stale.json"
    report = make_status_report(pid=os.getpid(), heartbeat="2020-01-01T00:00:00+00:00")
    report["process_started_at_utc"] = None
    path.write_text(
        json.dumps(report)
        + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 1
    output = capsys.readouterr().out
    assert '"observed_pid_alive": true' in output
    assert '"heartbeat_stale": true' in output
    assert '"stale": true' in output


def test_status_command_extends_heartbeat_grace_for_a_slow_plan(tmp_path, capsys, monkeypatch):
    path = tmp_path / "slow-plan.json"
    heartbeat = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    report = make_status_report(pid=os.getpid(), heartbeat=heartbeat)
    process_started = "2020-01-01T00:00:00Z"
    report["process_started_at_utc"] = process_started
    monkeypatch.setattr(soak_backend, "_process_start_time_utc", lambda _pid: process_started)
    report["plan"]["rate_per_minute"] = 0.1
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 0
    output = capsys.readouterr().out
    assert '"heartbeat_stale": false' in output
    assert '"heartbeat_grace_seconds": 2460.0' in output


def test_status_command_rejects_a_timezone_less_heartbeat(tmp_path, capsys):
    path = tmp_path / "heartbeat-naive.json"
    path.write_text(
        json.dumps(make_status_report(pid=os.getpid(), heartbeat="2026-08-28T00:00:00")) + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_marks_a_future_heartbeat_as_stale(tmp_path, capsys):
    path = tmp_path / "heartbeat-future.json"
    path.write_text(
        json.dumps(
            make_status_report(
                pid=os.getpid(), heartbeat="2999-01-01T00:00:00Z"
            )
        )
        + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 1
    output = capsys.readouterr().out
    assert '"clock_skew": true' in output
    assert '"stale": true' in output


@pytest.mark.skipif(os.name != "nt", reason="process creation time identity is Windows-specific")
def test_status_command_marks_a_reused_pid_as_stale(tmp_path, capsys):
    path = tmp_path / "pid-reused.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()
    )
    report["process_started_at_utc"] = "2000-01-01T00:00:00Z"
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 1
    output = capsys.readouterr().out
    assert '"process_identity_mismatch": true' in output
    assert '"stale": true' in output


@pytest.mark.parametrize(
    "contents",
    ["[]", '{"status":"running","passed":false}'],
)
def test_status_command_rejects_invalid_report_shape_or_version(tmp_path, capsys, contents):
    path = tmp_path / "invalid.json"
    path.write_text(contents + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "无法读取浸泡状态:" in capsys.readouterr().err


def test_status_command_rejects_a_schema_valid_but_incomplete_report(tmp_path, capsys):
    path = tmp_path / "incomplete.json"
    path.write_text(
        json.dumps({"schema_version": 1, "status": "passed", "passed": True}) + "\n",
        encoding="utf-8",
    )

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


@pytest.mark.parametrize(
    "mutate",
    (
        lambda report: report["plan"].update(batch_size="4"),
        lambda report: report["result"].update(iterations="0"),
        lambda report: report.update(status="passed"),
        lambda report: report.update(unexpected=True),
        lambda report: report["plan"].update(unexpected=True),
        lambda report: report["result"].update(unexpected=True),
        lambda report: report["environment"].update(unexpected=True),
        lambda report: report["environment"].update(logical_cpu_count="8"),
        lambda report: report["result"].update(iterations=1),
        lambda report: report["result"].update(protocol_events=10**13),
        lambda report: report.update(finished_at_utc="2025-01-01T00:00:00Z"),
    ),
)
def test_status_command_rejects_invalid_values_and_terminal_coherence(tmp_path, capsys, mutate):
    path = tmp_path / "invalid-values.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()
    )
    mutate(report)
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_rejects_failed_report_without_failure_category(tmp_path, capsys):
    path = tmp_path / "failed-without-category.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()
    )
    report.update(status="failed", finished_at_utc=datetime.now(timezone.utc).isoformat())
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_rejects_inconsistent_or_future_passed_report(tmp_path, capsys):
    path = tmp_path / "invalid-passed.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()
    )
    report.update(
        status="passed",
        started_at_utc="2999-01-01T00:00:00Z",
        last_heartbeat_utc="2999-01-01T00:00:00Z",
        finished_at_utc="2999-01-01T00:00:01Z",
        passed=True,
    )
    report["result"].update(
        iterations=0,
        completed_requests=0,
        cancelled_requests=0,
        graceful_shutdown=True,
    )
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_rejects_arbitrarily_large_integer_without_raising(tmp_path, capsys):
    path = tmp_path / "huge-integer.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat=datetime.now(timezone.utc).isoformat()
    )
    report["plan"]["rate_per_minute"] = 10**1000
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_rejects_deep_or_digit_limited_json_without_traceback(tmp_path, capsys):
    path = tmp_path / "malformed-depth.json"
    path.write_text("[" * 1100 + "]" * 1100, encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_status_command_rejects_an_oversized_report(tmp_path, capsys):
    path = tmp_path / "oversized.json"
    path.write_text("x" * (soak_backend.MAX_STATUS_REPORT_BYTES + 1), encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告文件过大" in capsys.readouterr().err


def test_status_command_rejects_elapsed_time_longer_than_report_window(tmp_path, capsys):
    path = tmp_path / "time-contradiction.json"
    report = make_status_report(
        pid=os.getpid(), heartbeat="2026-08-28T00:00:01Z"
    )
    report.update(
        status="passed",
        started_at_utc="2026-08-28T00:00:00Z",
        last_heartbeat_utc="2026-08-28T00:00:01Z",
        finished_at_utc="2026-08-28T00:00:02Z",
        passed=True,
    )
    report["result"].update(
        iterations=10,
        completed_requests=5,
        cancelled_requests=5,
        elapsed_seconds=999,
        graceful_shutdown=True,
    )
    path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    assert soak_backend.print_status(path) == 2
    assert "报告格式或版本无效" in capsys.readouterr().err


def test_write_json_report_replaces_the_target_without_a_temporary_file(tmp_path):
    path = tmp_path / "soak.json"
    path.write_text('{"status":"old"}\n', encoding="utf-8")
    soak_backend.write_json_report(path, {"status": "running", "value": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "status": "running",
        "value": "new",
    }
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_write_json_report_preserves_the_previous_target_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "soak.json"
    path.write_text('{"status":"old"}\n', encoding="utf-8")

    def fail_replace(_temporary, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(soak_backend.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        soak_backend.write_json_report(path, {"status": "new"})

    assert path.read_text(encoding="utf-8") == '{"status":"old"}\n'
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_write_json_report_rejects_non_finite_numbers(tmp_path):
    with pytest.raises(ValueError, match="Out of range float values are not JSON compliant"):
        soak_backend.write_json_report(tmp_path / "soak.json", {"elapsed": float("nan")})


def test_runtime_session_force_stops_when_shutdown_is_interrupted():
    class FakeProcess:
        stdin = None
        stdout = None
        stderr = None

        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = -15

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        def wait(self, timeout=None):
            return self.returncode

    class FakeThread:
        def join(self, timeout=None):
            return None

    process = FakeProcess()
    session = object.__new__(soak_backend.RuntimeSoakSession)
    session._process = process
    session._stdout_thread = FakeThread()
    session._stderr_thread = FakeThread()
    session._reader_failure = soak_backend.threading.Event()
    session._diagnostic_overflow = soak_backend.threading.Event()
    session._diagnostic_failure = soak_backend.threading.Event()
    session._shutdown_sequence = 0
    session._send = lambda _command: (_ for _ in ()).throw(KeyboardInterrupt)

    assert session.close() is False
    assert process.terminate_calls == 1
    assert process.kill_calls == 0
    assert process.poll() is not None


def test_runtime_session_force_stops_a_stubborn_process():
    class StubbornProcess:
        stdin = None
        stdout = None
        stderr = None

        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0
            self.kill_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1

        def kill(self):
            self.kill_calls += 1
            self.returncode = -9

        def wait(self, timeout=None):
            if self.returncode is None:
                raise soak_backend.subprocess.TimeoutExpired("fixture", timeout)
            return self.returncode

    process = StubbornProcess()
    session = object.__new__(soak_backend.RuntimeSoakSession)
    session._process = process

    session._force_stop()

    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.poll() is not None


def test_runtime_session_reports_reader_that_survives_cleanup():
    class FakeProcess:
        stdin = None
        stdout = None
        stderr = None
        returncode = 0

        def poll(self):
            return self.returncode

    class AliveThread:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            return None

    session = object.__new__(soak_backend.RuntimeSoakSession)
    session._process = FakeProcess()
    session._stdout_thread = AliveThread()
    session._stderr_thread = None
    session._reader_failure = soak_backend.threading.Event()
    session._diagnostic_overflow = soak_backend.threading.Event()
    session._diagnostic_failure = soak_backend.threading.Event()

    assert session.close() is False


def test_runtime_session_closes_every_stream_when_one_close_fails():
    class FailingStream:
        def __init__(self, should_fail):
            self.should_fail = should_fail
            self.closed = False

        def close(self):
            self.closed = True
            if self.should_fail:
                raise OSError("close failed")

    class FakeProcess:
        returncode = 0

        def __init__(self):
            self.stdin = FailingStream(True)
            self.stdout = FailingStream(False)
            self.stderr = FailingStream(False)

        def poll(self):
            return self.returncode

    class FakeThread:
        def __init__(self):
            self.joined = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.joined = True

    process = FakeProcess()
    stdout_thread = FakeThread()
    stderr_thread = FakeThread()
    session = object.__new__(soak_backend.RuntimeSoakSession)
    session._process = process
    session._stdout_thread = stdout_thread
    session._stderr_thread = stderr_thread
    session._reader_failure = soak_backend.threading.Event()
    session._diagnostic_overflow = soak_backend.threading.Event()
    session._diagnostic_failure = soak_backend.threading.Event()

    assert session.close() is False
    assert process.stdin.closed and process.stdout.closed and process.stderr.closed
    assert stdout_thread.joined and stderr_thread.joined


def test_reader_io_failures_are_recorded_as_terminal_failures():
    class BrokenStream:
        def __iter__(self):
            raise OSError("reader failed")

    session = object.__new__(soak_backend.RuntimeSoakSession)
    session._process = type("Process", (), {"stdout": BrokenStream()})()
    session._reader_failure = soak_backend.threading.Event()
    session._events = soak_backend.queue.Queue()
    session.timeout_seconds = 1

    session._read_protocol()

    assert session._reader_failure.is_set()


def test_runtime_session_cleans_up_if_reader_start_is_interrupted(monkeypatch):
    class FakeProcess:
        stdin = None
        stdout = None
        stderr = None

        def __init__(self):
            self.returncode = None
            self.terminate_calls = 0

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminate_calls += 1
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

    starts = 0

    class FakeThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            nonlocal starts
            starts += 1
            if starts == 2:
                raise KeyboardInterrupt

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    process = FakeProcess()
    monkeypatch.setattr(soak_backend.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(soak_backend.threading, "Thread", FakeThread)

    with pytest.raises(KeyboardInterrupt):
        soak_backend.RuntimeSoakSession(timeout_seconds=1)

    assert starts == 2
    assert process.terminate_calls == 1
    assert process.poll() is not None


def test_interrupted_run_writes_a_terminal_failure_report(tmp_path):
    class InterruptedSession(FakeSession):
        def run_batch(self, *, first_iteration: int, count: int, cancel_every: int):
            raise KeyboardInterrupt

    runner = soak_backend.SoakRunner(
        session_factory=InterruptedSession,
        environment_factory=lambda: {"system": "fixture"},
        utc_clock=lambda: "2026-07-14T00:00:00Z",
        monotonic=lambda: 0.0,
        sleeper=lambda _: None,
    )
    report = runner.run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
        report_path=tmp_path / "interrupted.json",
    )

    assert report["status"] == "failed"
    assert report["result"]["failure_category"] == "interrupted"
    assert report["passed"] is False
    persisted = json.loads((tmp_path / "interrupted.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert persisted["result"]["failure_category"] == "interrupted"


def test_run_marks_a_non_graceful_shutdown_with_a_failure_category():
    class NonGracefulSession(FakeSession):
        def close(self) -> bool:
            return False

    runner = soak_backend.SoakRunner(
        session_factory=NonGracefulSession,
        environment_factory=lambda: {
            "system": "fixture",
            "system_release": "fixture",
            "architecture": "fixture",
            "processor": "fixture",
            "logical_cpu_count": 1,
            "python_version": "3.12.0",
        },
        utc_clock=lambda: "2026-07-14T00:00:00Z",
        monotonic=lambda: 0.0,
        sleeper=lambda _: None,
    )

    report = runner.run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
    )

    assert report["status"] == "failed"
    assert report["result"]["failure_category"] == "graceful_shutdown_failed"


def test_keyboard_interrupt_during_session_cleanup_still_writes_terminal_report(tmp_path):
    class CleanupInterruptedSession(FakeSession):
        def close(self) -> bool:
            raise KeyboardInterrupt

    runner = soak_backend.SoakRunner(
        session_factory=CleanupInterruptedSession,
        environment_factory=lambda: {"system": "fixture"},
        utc_clock=lambda: "2026-07-14T00:00:00Z",
        monotonic=lambda: 0.0,
        sleeper=lambda _: None,
    )
    report_path = tmp_path / "cleanup-interrupted.json"
    report = runner.run(
        iterations=4,
        batch_size=4,
        timeout_seconds=5,
        cancel_every=2,
        duration_hours=0,
        rate_per_minute=0,
        report_path=report_path,
    )

    assert report["status"] == "failed"
    assert report["result"]["failure_category"] == "interrupted"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "failed"


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

