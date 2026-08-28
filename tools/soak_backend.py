#!/usr/bin/env python3
"""Credential-free Runtime request/cancel soak test for Reflex Next."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import tempfile
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "packages" / "reflex-runtime"
RUNTIME_SOURCE = RUNTIME_ROOT / "src"
CORE_SOURCE = REPO_ROOT / "packages" / "reflex-core" / "src"

DEFAULT_ITERATIONS = 10_000
DEFAULT_BATCH_SIZE = 4
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CANCEL_EVERY = 2
MAX_ITERATIONS = 1_000_000
MAX_BATCH_SIZE = 4
MAX_TIMEOUT_SECONDS = 30.0
MAX_DURATION_HOURS = 168.0
MAX_RATE_PER_MINUTE = 6_000.0
MAX_PROTOCOL_EVENTS = 4_096
MAX_REPORT_INTEGER = 10**12
MAX_STATUS_REPORT_BYTES = 2 * 1024 * 1024
MAX_STDERR_BYTES = 8 * 1024 * 1024
MAX_TERMINAL_HISTORY = 100_000
FINAL_OBSERVATION_SECONDS = 0.5
STATUS_HEARTBEAT_GRACE_SECONDS = 300.0

_STATUS_PLAN_FIELDS = {
    "minimum_iterations",
    "minimum_duration_hours",
    "batch_size",
    "cancel_every",
    "rate_per_minute",
    "batch_timeout_seconds",
}
_STATUS_RESULT_FIELDS = {
    "iterations",
    "completed_requests",
    "cancelled_requests",
    "protocol_events",
    "maximum_queue_depth",
    "final_observation_events",
    "elapsed_seconds",
    "graceful_shutdown",
    "failure_category",
}
_STATUS_ENVIRONMENT_FIELDS = {
    "system",
    "system_release",
    "architecture",
    "processor",
    "logical_cpu_count",
    "python_version",
}


def _is_status_report(report: Mapping[str, Any]) -> bool:
    required = {
        "schema_version",
        "status",
        "fixture",
        "pid",
        "process_started_at_utc",
        "started_at_utc",
        "finished_at_utc",
        "last_heartbeat_utc",
        "environment",
        "plan",
        "result",
        "passed",
    }
    if set(report) != required:
        return False
    status = report.get("status")
    if report.get("schema_version") != 1 or status not in {
        "running",
        "passed",
        "failed",
    }:
        return False
    if report.get("fixture") != "local_mock" or not isinstance(
        report.get("passed"), bool
    ):
        return False
    pid = report.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if not _is_utc_timestamp(report.get("process_started_at_utc"), allow_none=True):
        return False
    started_at = _parse_utc_timestamp(report.get("started_at_utc"))
    heartbeat_at = _parse_utc_timestamp(report.get("last_heartbeat_utc"))
    if started_at is None or heartbeat_at is None:
        return False
    finished_at = _parse_utc_timestamp(report.get("finished_at_utc"))
    if report.get("finished_at_utc") is not None and finished_at is None:
        return False
    process_started_at = _parse_utc_timestamp(report.get("process_started_at_utc"))
    if process_started_at is not None and process_started_at > started_at:
        return False
    if heartbeat_at < started_at:
        return False
    if finished_at is not None and finished_at < started_at:
        return False
    if finished_at is not None and heartbeat_at > finished_at:
        return False
    now = datetime.now(timezone.utc)
    if status != "running" and (started_at > now or heartbeat_at > now or (
        finished_at is not None and finished_at > now
    )):
        return False
    if not isinstance(report.get("environment"), dict) or set(
        report["environment"]
    ) != _STATUS_ENVIRONMENT_FIELDS:
        return False
    environment = report["environment"]
    if any(
        not isinstance(environment[field], str) or not environment[field]
        for field in (
            "system",
            "system_release",
            "architecture",
            "processor",
            "python_version",
        )
    ):
        return False
    if environment["logical_cpu_count"] is not None and (
        not isinstance(environment["logical_cpu_count"], int)
        or isinstance(environment["logical_cpu_count"], bool)
        or environment["logical_cpu_count"] <= 0
    ):
        return False
    plan = report.get("plan")
    result = report.get("result")
    if not isinstance(plan, dict) or set(plan) != _STATUS_PLAN_FIELDS:
        return False
    if not isinstance(result, dict) or set(result) != _STATUS_RESULT_FIELDS:
        return False
    if not isinstance(plan["minimum_iterations"], int) or isinstance(
        plan["minimum_iterations"], bool
    ) or not 1 <= plan["minimum_iterations"] <= MAX_ITERATIONS:
        return False
    if not _is_finite_number(plan["minimum_duration_hours"]) or not 0 <= plan[
        "minimum_duration_hours"
    ] <= MAX_DURATION_HOURS:
        return False
    if not isinstance(plan["batch_size"], int) or isinstance(
        plan["batch_size"], bool
    ) or not 1 <= plan["batch_size"] <= MAX_BATCH_SIZE:
        return False
    if not isinstance(plan["cancel_every"], int) or isinstance(
        plan["cancel_every"], bool
    ) or not 2 <= plan["cancel_every"] <= 100:
        return False
    if not _is_finite_number(plan["rate_per_minute"]) or not 0 <= plan[
        "rate_per_minute"
    ] <= MAX_RATE_PER_MINUTE:
        return False
    if not _is_finite_number(plan["batch_timeout_seconds"]) or not 0 < plan[
        "batch_timeout_seconds"
    ] <= MAX_TIMEOUT_SECONDS:
        return False
    for field in (
        "iterations",
        "completed_requests",
        "cancelled_requests",
        "protocol_events",
        "maximum_queue_depth",
        "final_observation_events",
    ):
        if (
            not isinstance(result[field], int)
            or isinstance(result[field], bool)
            or not 0 <= result[field] <= MAX_REPORT_INTEGER
        ):
            return False
    if result["maximum_queue_depth"] > MAX_PROTOCOL_EVENTS:
        return False
    if not _is_finite_number(result["elapsed_seconds"]) or result["elapsed_seconds"] < 0:
        return False
    if finished_at is not None and result["elapsed_seconds"] > (
        finished_at - started_at
    ).total_seconds() + 1.0:
        return False
    if not isinstance(result.get("graceful_shutdown"), bool):
        return False
    if result.get("failure_category") is not None and not isinstance(
        result.get("failure_category"), str
    ):
        return False
    passed = report.get("passed")
    if status == "running":
        return (
            passed is False
            and finished_at is None
            and result["failure_category"] is None
            and result["graceful_shutdown"] is False
            and result["completed_requests"] + result["cancelled_requests"]
            == result["iterations"]
        )
    if finished_at is None:
        return False
    if status == "passed":
        return (
            passed is True
            and result["failure_category"] is None
            and result["graceful_shutdown"] is True
            and result["iterations"] >= plan["minimum_iterations"]
            and result["completed_requests"] + result["cancelled_requests"]
            == result["iterations"]
            and result["completed_requests"] > 0
            and result["cancelled_requests"] > 0
            and result["final_observation_events"] == 0
            and result["elapsed_seconds"]
            >= plan["minimum_duration_hours"] * 3600.0
        )
    return (
        passed is False
        and isinstance(result["failure_category"], str)
        and bool(result["failure_category"])
    )


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    # ``math.isfinite`` converts integers to float and raises OverflowError for
    # arbitrarily large values.  Status validation must reject those values
    # deterministically through the explicit bounds below instead of escaping.
    return isinstance(value, int) or math.isfinite(value)


def _is_utc_timestamp(value: Any, *, allow_none: bool = False) -> bool:
    if value is None and allow_none:
        return True
    return _parse_utc_timestamp(value) is not None


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed.astimezone(timezone.utc)

FIXTURE_INPUT = "reflex runtime soak fixture"
CANCEL_FIXTURE_DELAY_MS = 100


class SoakFailure(RuntimeError):
    """A stable failure category that never includes protocol content."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class BatchResult:
    completed: int
    cancelled: int
    events: int
    maximum_queue_depth: int


@dataclass
class _RequestState:
    request_id: str
    expected_chunk: str
    should_cancel: bool
    cancel_sent: bool = False
    done_seen: bool = False
    terminal: str | None = None


def validate_limits(
    *,
    iterations: int,
    batch_size: int,
    timeout_seconds: float,
    cancel_every: int,
    duration_hours: float,
    rate_per_minute: float,
) -> None:
    if not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch-size must be between 1 and {MAX_BATCH_SIZE}")
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout must be greater than 0 and no more than {MAX_TIMEOUT_SECONDS} seconds"
        )
    if not 2 <= cancel_every <= 100:
        raise ValueError("cancel-every must be between 2 and 100")
    if iterations < cancel_every:
        raise ValueError("iterations must be at least cancel-every")
    if not 0 <= duration_hours <= MAX_DURATION_HOURS:
        raise ValueError(
            f"duration-hours must be between 0 and {MAX_DURATION_HOURS}"
        )
    if not 0 <= rate_per_minute <= MAX_RATE_PER_MINUTE:
        raise ValueError(
            f"rate-per-minute must be between 0 and {MAX_RATE_PER_MINUTE}"
        )
    if duration_hours > 0 and rate_per_minute <= 0:
        raise ValueError("rate-per-minute is required for a duration soak")


def collect_environment() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "system_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "logical_cpu_count": os.cpu_count(),
        "python_version": platform.python_version(),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_report(path: Path, report: Mapping[str, Any]) -> None:
    """Persist a report atomically so status readers never see partial JSON."""
    if path.suffix.lower() != ".json":
        raise ValueError("json-output must use a .json suffix")
    parent = path.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    serialized = (
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class RuntimeSoakSession:
    """One bounded Runtime process using only the development mock provider."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=MAX_PROTOCOL_EVENTS
        )
        self._reader_failure = threading.Event()
        self._diagnostic_overflow = threading.Event()
        self._diagnostic_failure = threading.Event()
        self._terminal_requests: dict[str, str] = {}
        self._terminal_order: deque[str] = deque()
        self._shutdown_sequence = 0
        self._process = subprocess.Popen(
            [sys.executable, "-m", "reflex_runtime.cli"],
            cwd=RUNTIME_ROOT,
            env=self._runtime_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        try:
            self._stdout_thread = threading.Thread(
                target=self._read_protocol,
                name="soak-runtime-protocol",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._drain_diagnostics,
                name="soak-runtime-diagnostics",
                daemon=True,
            )
            assert self._stdout_thread is not None and self._stderr_thread is not None
            self._stdout_thread.start()
            self._stderr_thread.start()
        except BaseException:
            self._force_stop()
            self._close_streams_and_join_readers()
            raise

    def __enter__(self) -> "RuntimeSoakSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @staticmethod
    def _runtime_environment() -> dict[str, str]:
        allowed_names = (
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
        )
        env = {
            name: os.environ[name]
            for name in allowed_names
            if name in os.environ
        }
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONPATH"] = os.pathsep.join((str(RUNTIME_SOURCE), str(CORE_SOURCE)))
        env["REFLEX_RUNTIME_DEVELOPMENT"] = "1"
        return env

    def run_batch(
        self,
        *,
        first_iteration: int,
        count: int,
        cancel_every: int,
    ) -> BatchResult:
        if self._process.poll() is not None:
            raise SoakFailure("runtime_exited")

        states: dict[str, _RequestState] = {}
        for offset in range(count):
            iteration = first_iteration + offset
            request_id = f"soak-{iteration:09d}"
            expected_chunk = f"soak-chunk-{iteration:09d}"
            state = _RequestState(
                request_id=request_id,
                expected_chunk=expected_chunk,
                should_cancel=(iteration % cancel_every == 0),
            )
            states[request_id] = state
            self._send(self._optimize_command(state))

        deadline = time.monotonic() + self.timeout_seconds
        terminal_count = 0
        event_count = 0
        maximum_queue_depth = self._events.qsize()
        while terminal_count < count:
            event_count += 1
            maximum_queue_depth = max(maximum_queue_depth, self._events.qsize())
            envelope = self._next_envelope(deadline)
            request_id = envelope.get("request_id")
            event = envelope.get("event")
            if not isinstance(request_id, str) or not isinstance(event, dict):
                raise SoakFailure("invalid_protocol_event")

            state = states.get(request_id)
            if state is None:
                self._validate_late_event(request_id, event)
                continue
            was_terminal = state.terminal is not None
            self._apply_event(state, event)
            if not was_terminal and state.terminal is not None:
                terminal_count += 1

        completed = 0
        cancelled = 0
        for state in states.values():
            if state.terminal == "completed":
                completed += 1
            elif state.terminal == "cancelled":
                cancelled += 1
            else:
                raise SoakFailure("missing_terminal_event")
            self._remember_terminal(state.request_id, state.terminal)
        return BatchResult(completed, cancelled, event_count, maximum_queue_depth)

    def observe_final_window(self) -> int:
        deadline = time.monotonic() + FINAL_OBSERVATION_SECONDS
        observed = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                envelope = self._events.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            observed += 1
            request_id = envelope.get("request_id")
            event = envelope.get("event")
            if not isinstance(request_id, str) or not isinstance(event, dict):
                raise SoakFailure("invalid_protocol_event")
            self._validate_late_event(request_id, event)
        return observed

    def close(self) -> bool:
        graceful = False
        interrupted = False
        if self._process.poll() is None:
            try:
                self._shutdown_sequence += 1
                self._send(
                    {
                        "version": 1,
                        "request_id": f"soak-shutdown-{self._shutdown_sequence}",
                        "type": "shutdown",
                        "payload": {},
                    }
                )
                self._process.wait(timeout=min(2.0, self.timeout_seconds))
                graceful = self._process.returncode == 0
            except (SoakFailure, OSError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                interrupted = isinstance(error, KeyboardInterrupt)
                self._force_stop()
        else:
            graceful = self._process.returncode == 0

        try:
            readers_stopped = self._close_streams_and_join_readers()
        except KeyboardInterrupt:
            interrupted = True
            self._force_stop()
            readers_stopped = self._close_streams_and_join_readers()
        process_stopped = self._process.poll() is not None
        return (
            graceful
            and not interrupted
            and not self._reader_failure.is_set()
            and not self._diagnostic_overflow.is_set()
            and not self._diagnostic_failure.is_set()
            and process_stopped
            and readers_stopped
        )

    def _close_streams_and_join_readers(self) -> bool:
        cleanup_ok = True
        for stream in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    cleanup_ok = False
        for reader in (self._stdout_thread, self._stderr_thread):
            if reader is None:
                continue
            is_alive = getattr(reader, "is_alive", None)
            if callable(is_alive) and is_alive():
                try:
                    reader.join(timeout=1.0)
                except Exception:
                    cleanup_ok = False
        readers_stopped = not any(
            callable(getattr(reader, "is_alive", None)) and reader.is_alive()
            for reader in (self._stdout_thread, self._stderr_thread)
            if reader is not None
        )
        return cleanup_ok and readers_stopped

    def _force_stop(self) -> bool:
        """Terminate a child even when shutdown itself was interrupted."""
        if self._process.poll() is not None:
            return True
        try:
            self._process.terminate()
        except (KeyboardInterrupt, OSError):
            pass
        try:
            self._process.wait(timeout=1.0)
            return self._process.poll() is not None
        except (KeyboardInterrupt, OSError, subprocess.TimeoutExpired):
            pass
        try:
            self._process.kill()
        except (KeyboardInterrupt, OSError):
            pass
        try:
            self._process.wait(timeout=1.0)
        except (KeyboardInterrupt, OSError, subprocess.TimeoutExpired):
            pass
        return self._process.poll() is not None

    def _apply_event(self, state: _RequestState, event: Mapping[str, Any]) -> None:
        event_type = event.get("type")
        data = event.get("data")
        if not isinstance(data, dict):
            raise SoakFailure("invalid_protocol_event")
        if state.terminal is not None:
            if state.terminal == "cancelled" and event_type in {"chunk", "done"}:
                raise SoakFailure("late_event_after_cancel")
            raise SoakFailure("duplicate_terminal_event")
        if event_type == "error":
            raise SoakFailure("runtime_error")
        if event_type == "chunk":
            if data.get("text") != state.expected_chunk:
                raise SoakFailure("request_cross_talk")
            if state.should_cancel and not state.cancel_sent:
                self._send(
                    {
                        "version": 1,
                        "request_id": state.request_id,
                        "type": "cancel",
                        "payload": {},
                    }
                )
                state.cancel_sent = True
            return
        if event_type == "done":
            if state.should_cancel:
                raise SoakFailure("completed_instead_of_cancelled")
            state.done_seen = True
            return
        if event_type == "metric":
            if state.should_cancel or not state.done_seen:
                raise SoakFailure("invalid_terminal_order")
            state.terminal = "completed"
            return
        if event_type == "status" and data.get("phase") == "cancelled":
            if not state.should_cancel or not state.cancel_sent:
                raise SoakFailure("unexpected_cancellation")
            state.terminal = "cancelled"

    def _validate_late_event(self, request_id: str, event: Mapping[str, Any]) -> None:
        terminal = self._terminal_requests.get(request_id)
        if terminal is None:
            raise SoakFailure("unknown_request_event")
        if terminal == "cancelled" and event.get("type") in {"chunk", "done"}:
            raise SoakFailure("late_event_after_cancel")
        raise SoakFailure("event_after_terminal")

    def _remember_terminal(self, request_id: str, terminal: str) -> None:
        self._terminal_requests[request_id] = terminal
        self._terminal_order.append(request_id)
        while len(self._terminal_order) > MAX_TERMINAL_HISTORY:
            expired = self._terminal_order.popleft()
            self._terminal_requests.pop(expired, None)

    def _next_envelope(self, deadline: float) -> dict[str, Any]:
        while True:
            if self._reader_failure.is_set():
                raise SoakFailure("protocol_reader_failed")
            if self._diagnostic_overflow.is_set():
                raise SoakFailure("diagnostic_output_too_large")
            if self._diagnostic_failure.is_set():
                raise SoakFailure("diagnostic_reader_failed")
            if self._process.poll() is not None and self._events.empty():
                raise SoakFailure("runtime_exited")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SoakFailure("batch_timeout")
            try:
                return self._events.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue

    def _send(self, command: Mapping[str, Any]) -> None:
        if self._process.poll() is not None or self._process.stdin is None:
            raise SoakFailure("runtime_unavailable")
        try:
            self._process.stdin.write(json.dumps(command, ensure_ascii=True) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise SoakFailure("runtime_command_failed") from error

    @staticmethod
    def _optimize_command(state: _RequestState) -> dict[str, Any]:
        delay_ms = CANCEL_FIXTURE_DELAY_MS if state.should_cancel else 0
        return {
            "version": 1,
            "request_id": state.request_id,
            "type": "optimize",
            "payload": {
                "text": FIXTURE_INPUT,
                "style": "concise",
                "provider": "mock",
                "model": "mock-stream",
                "metadata": {
                    "delay_ms": delay_ms,
                    "chunks": [state.expected_chunk] * 3,
                },
            },
        }

    def _read_protocol(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._reader_failure.set()
            return
        try:
            for line in stream:
                if not line.strip():
                    continue
                if len(line.encode("utf-8", errors="replace")) > 8 * 1024 * 1024:
                    raise ValueError("oversized protocol line")
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    raise ValueError("invalid envelope")
                self._events.put(envelope, timeout=self.timeout_seconds)
        except Exception:
            self._reader_failure.set()

    def _drain_diagnostics(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        try:
            total = 0
            for line in stream:
                total += len(line.encode("utf-8", errors="replace"))
                if total > MAX_STDERR_BYTES:
                    self._diagnostic_overflow.set()
                    return
        except Exception:
            self._diagnostic_failure.set()


def _sliced_sleep(
    seconds: float,
    *,
    slice_seconds: float = 1.0,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Sleep for ``seconds`` in bounded slices.

    A long single wait has been observed to occasionally never return on some
    Windows machines; slicing keeps every individual wait short so a hung
    timer cannot silently stall a duration soak.
    """
    deadline = monotonic() + seconds
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return
        sleeper(min(slice_seconds, remaining))


class SoakRunner:
    def __init__(
        self,
        *,
        session_factory: Callable[[float], Any] = RuntimeSoakSession,
        environment_factory: Callable[[], dict[str, Any]] = collect_environment,
        utc_clock: Callable[[], str] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = _sliced_sleep,
    ) -> None:
        self._session_factory = session_factory
        self._environment_factory = environment_factory
        self._utc_clock = utc_clock
        self._monotonic = monotonic
        self._sleeper = sleeper

    def run(
        self,
        *,
        iterations: int,
        batch_size: int,
        timeout_seconds: float,
        cancel_every: int,
        duration_hours: float,
        rate_per_minute: float,
        report_path: Path | None = None,
    ) -> dict[str, Any]:
        validate_limits(
            iterations=iterations,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            cancel_every=cancel_every,
            duration_hours=duration_hours,
            rate_per_minute=rate_per_minute,
        )
        started_at_utc = self._utc_clock()
        started_at = self._monotonic()
        minimum_duration_seconds = duration_hours * 3600.0
        completed_iterations = 0
        completed_requests = 0
        cancelled_requests = 0
        protocol_events = 0
        maximum_queue_depth = 0
        final_observation_events = 0
        failure_category: str | None = None
        graceful_shutdown = False
        session: Any | None = None
        environment = self._environment_factory()
        last_heartbeat_utc = started_at_utc
        process_started_at_utc = _process_start_time_utc(os.getpid())

        def build_report(
            *, status: str, finished_at_utc: str | None, passed: bool
        ) -> dict[str, Any]:
            elapsed_seconds = max(0.0, self._monotonic() - started_at)
            return {
                "schema_version": 1,
                "status": status,
                "fixture": "local_mock",
                "pid": os.getpid(),
                "process_started_at_utc": process_started_at_utc,
                "started_at_utc": started_at_utc,
                "finished_at_utc": finished_at_utc,
                "last_heartbeat_utc": last_heartbeat_utc,
                "environment": environment,
                "plan": {
                    "minimum_iterations": iterations,
                    "minimum_duration_hours": duration_hours,
                    "batch_size": batch_size,
                    "cancel_every": cancel_every,
                    "rate_per_minute": rate_per_minute,
                    "batch_timeout_seconds": timeout_seconds,
                },
                "result": {
                    "iterations": completed_iterations,
                    "completed_requests": completed_requests,
                    "cancelled_requests": cancelled_requests,
                    "protocol_events": protocol_events,
                    "maximum_queue_depth": maximum_queue_depth,
                    "final_observation_events": final_observation_events,
                    "elapsed_seconds": round(elapsed_seconds, 3),
                    "graceful_shutdown": graceful_shutdown,
                    "failure_category": failure_category,
                },
                "passed": passed,
            }

        if report_path is not None:
            write_json_report(
                report_path,
                build_report(status="running", finished_at_utc=None, passed=False),
            )

        try:
            session = self._session_factory(timeout_seconds)
            while (
                completed_iterations < iterations
                or self._monotonic() - started_at < minimum_duration_seconds
            ):
                batch_started_at = self._monotonic()
                count = min(batch_size, max(1, iterations - completed_iterations))
                result = session.run_batch(
                    first_iteration=completed_iterations + 1,
                    count=count,
                    cancel_every=cancel_every,
                )
                completed_iterations += count
                completed_requests += result.completed
                cancelled_requests += result.cancelled
                protocol_events += result.events
                maximum_queue_depth = max(
                    maximum_queue_depth, result.maximum_queue_depth
                )
                last_heartbeat_utc = self._utc_clock()
                if report_path is not None:
                    write_json_report(
                        report_path,
                        build_report(status="running", finished_at_utc=None, passed=False),
                    )

                if rate_per_minute > 0:
                    target_batch_seconds = (60.0 / rate_per_minute) * count
                    remaining = target_batch_seconds - (
                        self._monotonic() - batch_started_at
                    )
                    if remaining > 0:
                        self._sleeper(remaining)
            final_observation_events = session.observe_final_window()
            if final_observation_events:
                raise SoakFailure("late_protocol_event")
        except SoakFailure as error:
            failure_category = error.code
        except KeyboardInterrupt:
            # Preserve a terminal report when an operator stops the run.  A
            # report left as ``running`` would be indistinguishable from a
            # crashed or power-lost process.
            failure_category = "interrupted"
        except Exception:
            failure_category = "unexpected_failure"
        finally:
            if session is not None:
                try:
                    graceful_shutdown = bool(session.close())
                except KeyboardInterrupt:
                    graceful_shutdown = False
                    if failure_category is None:
                        failure_category = "interrupted"
                except Exception:
                    graceful_shutdown = False
                    if failure_category is None:
                        failure_category = "graceful_shutdown_failed"
            if not graceful_shutdown and failure_category is None:
                failure_category = "graceful_shutdown_failed"

        elapsed_seconds = max(0.0, self._monotonic() - started_at)
        passed = (
            failure_category is None
            and completed_iterations >= iterations
            and elapsed_seconds >= minimum_duration_seconds
            and completed_requests + cancelled_requests == completed_iterations
            and cancelled_requests > 0
            and completed_requests > 0
            and graceful_shutdown
            and final_observation_events == 0
        )
        report = build_report(
            status="passed" if passed else "failed",
            finished_at_utc=self._utc_clock(),
            passed=passed,
        )
        if report_path is not None:
            write_json_report(report_path, report)
        return report


def render_human_summary(report: Mapping[str, Any]) -> str:
    plan = report["plan"]
    result = report["result"]
    conclusion = "通过" if report["passed"] else "未通过"
    return "\n".join(
        (
            "Reflex Next Runtime 请求/取消浸泡",
            (
                f"计划: 至少 {plan['minimum_iterations']} 次 / "
                f"{plan['minimum_duration_hours']} 小时 / 并发 {plan['batch_size']}"
            ),
            (
                f"结果: {result['iterations']} 次，完成 {result['completed_requests']}，"
                f"取消 {result['cancelled_requests']}，耗时 {result['elapsed_seconds']} 秒"
            ),
            f"安全退出: {result['graceful_shutdown']} | 结论: {conclusion}",
        )
    )


def _process_start_time_utc(pid: int) -> str | None:
    """Return a Windows process creation time for PID-reuse detection."""
    if pid <= 0 or os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class FileTime(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        creation = FileTime()
        exit_time = FileTime()
        kernel_time = FileTime()
        user_time = FileTime()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        ticks = (creation.high << 32) | creation.low
        created = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(
            microseconds=ticks // 10
        )
        return _utc_timestamp(created)
    finally:
        kernel32.CloseHandle(handle)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _process_is_alive(pid: int) -> bool:
    """Probe a process without sending a termination signal on Windows."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a bounded request/cancel soak against the local mock Runtime."
    )
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument("--cancel-every", type=int, default=DEFAULT_CANCEL_EVERY)
    parser.add_argument("--duration-hours", type=float, default=0.0)
    parser.add_argument("--rate-per-minute", type=float, default=0.0)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument("--json-output", type=Path)
    output.add_argument(
        "--status",
        type=Path,
        help="Read a running or completed JSON report without touching the soak process.",
    )
    return parser


def print_status(path: Path) -> int:
    try:
        if path.stat().st_size > MAX_STATUS_REPORT_BYTES:
            raise ValueError("报告文件过大")
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, RecursionError) as error:
        print(f"无法读取浸泡状态: {error}", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("无法读取浸泡状态: 报告格式或版本无效", file=sys.stderr)
        return 2
    observed = dict(report)
    if not _is_status_report(observed):
        print("无法读取浸泡状态: 报告格式或版本无效", file=sys.stderr)
        return 2
    status = observed.get("status")
    if status == "running":
        pid = observed.get("pid")
        pid_alive = isinstance(pid, int) and _process_is_alive(pid)
        expected_process_start = _parse_utc_timestamp(
            observed.get("process_started_at_utc")
        )
        actual_process_start = (
            _parse_utc_timestamp(_process_start_time_utc(pid))
            if pid_alive and isinstance(pid, int)
            else None
        )
        process_identity_mismatch = os.name == "nt" and pid_alive and (
            expected_process_start is None
            or actual_process_start is None
            or actual_process_start != expected_process_start
        )
        heartbeat_age: float | None = None
        heartbeat_stale = True
        now = datetime.now(timezone.utc)
        heartbeat_at = _parse_utc_timestamp(observed.get("last_heartbeat_utc"))
        plan = observed["plan"]
        heartbeat_grace_seconds = STATUS_HEARTBEAT_GRACE_SECONDS
        if plan["rate_per_minute"] > 0:
            expected_batch_seconds = (
                60.0 / plan["rate_per_minute"] * plan["batch_size"]
            )
            heartbeat_grace_seconds = max(
                heartbeat_grace_seconds, expected_batch_seconds + 60.0
            )
        if heartbeat_at is not None and heartbeat_at <= now:
            heartbeat_age = (now - heartbeat_at).total_seconds()
            heartbeat_stale = heartbeat_age > heartbeat_grace_seconds
        started_at = _parse_utc_timestamp(observed.get("started_at_utc"))
        clock_skew = started_at is None or started_at > now or heartbeat_at is None or heartbeat_at > now
        observed["heartbeat_age_seconds"] = (
            round(heartbeat_age, 3) if heartbeat_age is not None else None
        )
        observed["heartbeat_grace_seconds"] = round(heartbeat_grace_seconds, 3)
        observed["heartbeat_stale"] = heartbeat_stale
        observed["clock_skew"] = clock_skew
        observed["process_identity_mismatch"] = process_identity_mismatch
        observed["observed_pid_alive"] = pid_alive
        observed["stale"] = (
            not pid_alive
            or heartbeat_stale
            or clock_skew
            or process_identity_mismatch
        )
    print(json.dumps(observed, ensure_ascii=False, indent=2))
    if status == "passed" and observed.get("passed") is True:
        return 0
    if status == "running" and observed.get("observed_pid_alive") and not observed.get("stale"):
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.status is not None:
        return print_status(args.status)
    try:
        validate_limits(
            iterations=args.iterations,
            batch_size=args.batch_size,
            timeout_seconds=args.timeout_seconds,
            cancel_every=args.cancel_every,
            duration_hours=args.duration_hours,
            rate_per_minute=args.rate_per_minute,
        )
    except ValueError as error:
        print(f"参数错误: {error}", file=sys.stderr)
        return 2

    report = SoakRunner().run(
        iterations=args.iterations,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
        cancel_every=args.cancel_every,
        duration_hours=args.duration_hours,
        rate_per_minute=args.rate_per_minute,
        report_path=args.json_output,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(render_human_summary(report), file=sys.stderr)
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
