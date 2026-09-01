#!/usr/bin/env python3
"""Bounded, credential-free backend latency benchmark for Reflex Next."""

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
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT / "packages" / "reflex-runtime"
RUNTIME_SOURCE = RUNTIME_ROOT / "src"
CORE_SOURCE = REPO_ROOT / "packages" / "reflex-core" / "src"

DEFAULT_SAMPLES = 10
MAX_SAMPLES = 100
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_STARTUP_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_PROTOCOL_EVENTS = 256

FIXTURE_INPUT = "reflex backend benchmark fixture"
FIXTURE_CHUNK = "benchmark-chunk"

METRIC_THRESHOLDS_MS: dict[str, float] = {
    "cold_start": 3000.0,
    "runtime_first_status": 200.0,
    "provider_first_chunk": 500.0,
    "total_duration": 1000.0,
    "cancellation_latency": 250.0,
}

METRIC_THRESHOLD_SOURCES = {
    "cold_start": "production_slo",
    "runtime_first_status": "production_slo",
    "provider_first_chunk": "local_fixture_guardrail",
    "total_duration": "local_fixture_guardrail",
    "cancellation_latency": "production_slo",
}

METRIC_LABELS = {
    "cold_start": "冷启动",
    "runtime_first_status": "Runtime 首状态",
    "provider_first_chunk": "Provider 首包",
    "total_duration": "本地 Mock 总耗时",
    "cancellation_latency": "取消确认",
}


class BenchmarkFailure(RuntimeError):
    """Internal measurement failure whose details must not enter reports."""


def validate_limits(samples: int, timeout_seconds: float) -> None:
    if not 1 <= samples <= MAX_SAMPLES:
        raise ValueError(f"samples must be between 1 and {MAX_SAMPLES}")
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout must be greater than 0 and no more than {MAX_TIMEOUT_SECONDS} seconds"
        )


def calculate_percentiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "p99_ms": None}
    ordered = sorted(values)

    def nearest_rank(percentile: float) -> float:
        index = max(0, math.ceil(percentile * len(ordered)) - 1)
        return round(float(ordered[index]), 3)

    return {
        "p50_ms": nearest_rank(0.50),
        "p95_ms": nearest_rank(0.95),
        "p99_ms": nearest_rank(0.99),
    }


def collect_environment() -> dict[str, Any]:
    return {
        "system": platform.system(),
        "system_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "logical_cpu_count": os.cpu_count(),
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RuntimeSession:
    """One isolated development Runtime process using only the built-in mock."""

    def __init__(
        self,
        timeout_seconds: float,
        *,
        startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.startup_timeout_seconds = startup_timeout_seconds
        self._sequence = 0
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(
            maxsize=MAX_PROTOCOL_EVENTS
        )
        self._reader_failure = threading.Event()
        self._started_at = time.perf_counter()
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
            target=self._read_protocol, name="benchmark-runtime-protocol", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_diagnostics,
            name="benchmark-runtime-diagnostics",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def __enter__(self) -> "RuntimeSession":
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

    def ping_latency_ms(self) -> float:
        request_id = self._next_request_id("cold")
        self._send(
            {
                "version": 1,
                "request_id": request_id,
                "type": "ping",
                "payload": {},
            }
        )
        self._wait_for(
            request_id,
            lambda event: event.get("type") == "status",
            timeout=self.startup_timeout_seconds,
        )
        return self._elapsed_ms(self._started_at)

    def warm_up(self) -> None:
        request_id = self._next_request_id("warmup")
        self._send(
            {
                "version": 1,
                "request_id": request_id,
                "type": "ping",
                "payload": {},
            }
        )
        self._wait_for(request_id, lambda event: event.get("type") == "status")

    def optimize_latencies_ms(self) -> dict[str, float]:
        request_id = self._next_request_id("optimize")
        started_at = time.perf_counter()
        self._send(self._optimize_command(request_id, delay_ms=0))
        self._wait_for(request_id, lambda event: event.get("type") == "status")
        first_status = self._elapsed_ms(started_at)
        self._wait_for(request_id, lambda event: event.get("type") == "chunk")
        first_chunk = self._elapsed_ms(started_at)
        self._wait_for(request_id, lambda event: event.get("type") == "metric")
        total = self._elapsed_ms(started_at)
        return {
            "runtime_first_status": first_status,
            "provider_first_chunk": first_chunk,
            "total_duration": total,
        }

    def cancellation_latency_ms(self) -> float:
        request_id = self._next_request_id("cancel")
        self._send(self._optimize_command(request_id, delay_ms=100))
        self._wait_for(request_id, lambda event: event.get("type") == "chunk")
        cancel_started_at = time.perf_counter()
        self._send(
            {
                "version": 1,
                "request_id": request_id,
                "type": "cancel",
                "payload": {},
            }
        )
        self._wait_for(
            request_id,
            lambda event: event.get("type") == "status"
            and event.get("data", {}).get("phase") == "cancelled",
        )
        return self._elapsed_ms(cancel_started_at)

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                request_id = self._next_request_id("shutdown")
                self._send(
                    {
                        "version": 1,
                        "request_id": request_id,
                        "type": "shutdown",
                        "payload": {},
                    }
                )
                self._process.wait(timeout=min(2.0, self.timeout_seconds))
            except (BenchmarkFailure, OSError, subprocess.TimeoutExpired):
                self._process.terminate()
                try:
                    self._process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=1.0)
        for stream in (
            self._process.stdin,
            self._process.stdout,
            self._process.stderr,
        ):
            if stream is not None:
                stream.close()

    def _optimize_command(self, request_id: str, *, delay_ms: int) -> dict[str, Any]:
        return {
            "version": 1,
            "request_id": request_id,
            "type": "optimize",
            "payload": {
                "text": FIXTURE_INPUT,
                "style": "concise",
                "provider": "mock",
                "model": "mock-stream",
                "metadata": {
                    "delay_ms": delay_ms,
                    "chunks": [FIXTURE_CHUNK, FIXTURE_CHUNK],
                },
            },
        }

    def _next_request_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"benchmark-{prefix}-{self._sequence}"

    def _send(self, command: Mapping[str, Any]) -> None:
        if self._process.poll() is not None or self._process.stdin is None:
            raise BenchmarkFailure("runtime unavailable")
        try:
            self._process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise BenchmarkFailure("runtime command failed") from error

    def _wait_for(
        self,
        request_id: str,
        predicate: Callable[[dict[str, Any]], bool],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + (
            self.timeout_seconds if timeout is None else timeout
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BenchmarkFailure("measurement timeout")
            if self._process.poll() is not None and self._events.empty():
                raise BenchmarkFailure("runtime exited")
            if self._reader_failure.is_set() and self._events.empty():
                raise BenchmarkFailure("protocol reader failed")
            try:
                envelope = self._events.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if envelope.get("request_id") != request_id:
                continue
            event = envelope.get("event")
            if not isinstance(event, dict):
                raise BenchmarkFailure("invalid protocol event")
            if event.get("type") == "error":
                raise BenchmarkFailure("runtime returned error")
            if predicate(event):
                return event

    def _read_protocol(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._reader_failure.set()
            return
        try:
            for line in stream:
                if not line.strip():
                    continue
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
        for _ in stream:
            pass

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return (time.perf_counter() - started_at) * 1000.0


class BenchmarkRunner:
    def __init__(
        self,
        *,
        session_factory: Callable[[float], Any] = RuntimeSession,
        environment_factory: Callable[[], dict[str, Any]] = collect_environment,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._environment_factory = environment_factory
        self._clock = clock

    def run(self, *, samples: int, timeout_seconds: float) -> dict[str, Any]:
        validate_limits(samples, timeout_seconds)
        values: dict[str, list[float]] = {
            name: [] for name in METRIC_THRESHOLDS_MS
        }
        failures = {name: 0 for name in METRIC_THRESHOLDS_MS}

        for _ in range(samples):
            try:
                with self._session_factory(timeout_seconds) as session:
                    values["cold_start"].append(session.ping_latency_ms())
            except Exception:
                failures["cold_start"] += 1

        try:
            with self._session_factory(timeout_seconds) as session:
                session.warm_up()
                for _ in range(samples):
                    try:
                        measured = session.optimize_latencies_ms()
                    except Exception:
                        for name in (
                            "runtime_first_status",
                            "provider_first_chunk",
                            "total_duration",
                        ):
                            failures[name] += 1
                    else:
                        for name, value in measured.items():
                            values[name].append(value)

                for _ in range(samples):
                    try:
                        values["cancellation_latency"].append(
                            session.cancellation_latency_ms()
                        )
                    except Exception:
                        failures["cancellation_latency"] += 1
        except Exception:
            for name in (
                "runtime_first_status",
                "provider_first_chunk",
                "total_duration",
                "cancellation_latency",
            ):
                missing = samples - len(values[name]) - failures[name]
                failures[name] += max(0, missing)

        metrics: dict[str, dict[str, Any]] = {}
        for name, threshold_ms in METRIC_THRESHOLDS_MS.items():
            percentiles = calculate_percentiles(values[name])
            passed = (
                failures[name] == 0
                and percentiles["p95_ms"] is not None
                and percentiles["p95_ms"] <= threshold_ms
            )
            metrics[name] = {
                "successful_samples": len(values[name]),
                "failures": failures[name],
                **percentiles,
                "threshold_ms": threshold_ms,
                "threshold_source": METRIC_THRESHOLD_SOURCES[name],
                "threshold_passed": passed,
            }

        return {
            "schema_version": 1,
            "generated_at_utc": self._clock(),
            "fixture": "local_mock",
            "environment": self._environment_factory(),
            "sample_count": samples,
            "timeout_seconds": timeout_seconds,
            "percentile_method": "nearest_rank",
            "metrics": metrics,
            "overall_threshold_passed": all(
                metric["threshold_passed"] for metric in metrics.values()
            ),
        }


def render_human_summary(report: Mapping[str, Any]) -> str:
    lines = [
        "Reflex Next 后端本地 Mock 性能基准",
        (
            f"样本数: {report['sample_count']} | 单次超时: "
            f"{report['timeout_seconds']}s | P50/P95/P99: nearest-rank"
        ),
    ]
    metrics = report["metrics"]
    for name in METRIC_THRESHOLDS_MS:
        metric = metrics[name]
        result = "通过" if metric["threshold_passed"] else "未通过"

        def display(value: float | None) -> str:
            return "N/A" if value is None else f"{value:.3f}ms"

        lines.append(
            f"- {METRIC_LABELS[name]}: "
            f"P50 {display(metric['p50_ms'])}, "
            f"P95 {display(metric['p95_ms'])}, "
            f"P99 {display(metric['p99_ms'])}, "
            f"失败 {metric['failures']}, "
            f"阈值 {metric['threshold_ms']:.0f}ms, {result}"
        )
    overall = "通过" if report["overall_threshold_passed"] else "未通过"
    lines.append(f"总体阈值结论: {overall}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure bounded Reflex Next backend latency with a local mock."
    )
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path for the JSON report; JSON is always written to stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        validate_limits(args.samples, args.timeout_seconds)
    except ValueError as error:
        print(f"参数错误: {error}", file=sys.stderr)
        return 2

    report = BenchmarkRunner().run(
        samples=args.samples, timeout_seconds=args.timeout_seconds
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output is not None:
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(render_human_summary(report), file=sys.stderr)
    print(serialized)
    return 0 if report["overall_threshold_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
