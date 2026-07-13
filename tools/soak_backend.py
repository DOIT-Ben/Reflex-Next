#!/usr/bin/env python3
"""Credential-free Runtime request/cancel soak test for Reflex Next."""

from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
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
MAX_STDERR_BYTES = 8 * 1024 * 1024
MAX_TERMINAL_HISTORY = 100_000
FINAL_OBSERVATION_SECONDS = 0.5

FIXTURE_INPUT = "reflex runtime soak fixture"


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


class RuntimeSoakSession:
    """One bounded Runtime process using only the development mock provider."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=MAX_PROTOCOL_EVENTS
        )
        self._reader_failure = threading.Event()
        self._diagnostic_overflow = threading.Event()
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
        self._stdout_thread.start()
        self._stderr_thread.start()

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
            except (SoakFailure, OSError, subprocess.TimeoutExpired):
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        else:
            graceful = self._process.returncode == 0

        for stream in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if stream is not None:
                stream.close()
        self._stdout_thread.join(timeout=1.0)
        self._stderr_thread.join(timeout=1.0)
        return (
            graceful
            and not self._reader_failure.is_set()
            and not self._diagnostic_overflow.is_set()
            and self._process.poll() is not None
        )

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
        delay_ms = 10 if state.should_cancel else 0
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
        except (json.JSONDecodeError, ValueError, queue.Full):
            self._reader_failure.set()

    def _drain_diagnostics(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        total = 0
        for line in stream:
            total += len(line.encode("utf-8", errors="replace"))
            if total > MAX_STDERR_BYTES:
                self._diagnostic_overflow.set()
                return


class SoakRunner:
    def __init__(
        self,
        *,
        session_factory: Callable[[float], Any] = RuntimeSoakSession,
        environment_factory: Callable[[], dict[str, Any]] = collect_environment,
        utc_clock: Callable[[], str] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
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

                if rate_per_minute > 0:
                    target_batch_seconds = (60.0 / rate_per_minute) * count
                    remaining = target_batch_seconds - (
                        self._monotonic() - batch_started_at
                    )
                    if remaining > 0:
                        self._sleeper(remaining)
            final_observation_events = session.observe_final_window()
        except SoakFailure as error:
            failure_category = error.code
        except Exception:
            failure_category = "unexpected_failure"
        finally:
            if session is not None:
                try:
                    graceful_shutdown = bool(session.close())
                except Exception:
                    graceful_shutdown = False

        elapsed_seconds = max(0.0, self._monotonic() - started_at)
        passed = (
            failure_category is None
            and completed_iterations >= iterations
            and elapsed_seconds >= minimum_duration_seconds
            and completed_requests + cancelled_requests == completed_iterations
            and cancelled_requests > 0
            and completed_requests > 0
            and graceful_shutdown
        )
        return {
            "schema_version": 1,
            "fixture": "local_mock",
            "started_at_utc": started_at_utc,
            "finished_at_utc": self._utc_clock(),
            "environment": self._environment_factory(),
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
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output is not None:
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(render_human_summary(report), file=sys.stderr)
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
