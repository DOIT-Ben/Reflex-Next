"""Graded concurrency soak for the Reflex Next HTTP host (SSE).

The tool expects a running ``reflex-http-host`` service (see
``packages/reflex-http-host``) and drives it with increasing concurrency
levels.  Every request consumes the full SSE stream and is checked for:

- request cross-talk (events of another request_id in the stream);
- a terminal event (metric/error, or a status phase reaching
  completed/cancelled/error);
- cancellation semantics when ``--cancel-every`` is used;
- stable ``runtime_busy`` errors reported as a separate counter.

The tool only exercises the development mock provider, never real provider
credentials, and writes a bounded report without request bodies.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

DEFAULT_LEVELS = "1,4,16,32"
DEFAULT_ITERATIONS = 20
DEFAULT_CANCEL_EVERY = 4
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_LEVELS = 64
MAX_ITERATIONS = 10_000
MAX_TIMEOUT_SECONDS = 120.0
CANCEL_DELAY_MS = 400
TERMINAL_PHASES = frozenset({"completed", "cancelled", "error"})


class SoakFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RequestOutcome:
    request_id: str
    completed: bool = False
    cancelled: bool = False
    busy: bool = False
    failure: str | None = None
    failure_detail: str | None = None
    cross_talk: bool = False
    missing_terminal: bool = False
    elapsed_ms: float = 0.0
    chunks: int = 0
    retried: bool = False


class HttpSoakClient:
    """Real httpx SSE client used by the runner (injected in contract tests)."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        import httpx

        self._httpx = httpx
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds

    def optimize(
        self,
        request_id: str,
        *,
        cancel: bool = False,
        on_envelope: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        """POST /v1/optimize and consume the full SSE stream.

        Cancellation fixtures slow the mock stream down (``delay_ms``) so the
        cancel command can land before the stream finishes.  ``on_envelope``
        is invoked for every event as it arrives, so callers can cancel
        mid-stream.
        """
        payload: dict[str, Any] = {
            "text": "reflex http soak fixture",
            "style": "concise",
            "provider": "mock",
            "model": "mock-stream",
            "request_id": request_id,
        }
        if cancel:
            payload["metadata"] = {"delay_ms": CANCEL_DELAY_MS, "chunks": ["a", "b", "c"]}
        envelopes: list[dict[str, Any]] = []
        with self._httpx.stream(
            "POST",
            f"{self._base_url}/v1/optimize",
            json=payload,
            timeout=self._timeout_seconds,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                line = line.strip()
                if not line.startswith("data: "):
                    continue
                envelope = json.loads(line[6:])
                if on_envelope is not None:
                    on_envelope(envelope)
                envelopes.append(envelope)
        return envelopes

    def cancel(self, request_id: str) -> None:
        self._httpx.post(f"{self._base_url}/v1/requests/{request_id}/cancel", timeout=5.0)


class FakeClient:
    """Injected client for contract tests; no network access.

    Requests whose offset matches ``cancel_every`` end with a ``cancelled``
    status (the cancellation fixture taking effect); all others complete.
    """

    def __init__(self, *, cancel_every: int | None = None, busy: bool = False) -> None:
        self._cancel_every = cancel_every
        self._busy = busy
        self.cancelled: list[str] = []

    def optimize(
        self,
        request_id: str,
        *,
        cancel: bool = False,
        on_envelope: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        if self._busy:
            return [
                {
                    "version": 1,
                    "request_id": request_id,
                    "event": {"type": "error", "data": {"code": "runtime_busy"}},
                }
            ]
        envelopes = [
            {"version": 1, "request_id": request_id, "event": {"type": "chunk", "data": {"text": "a"}}},
            {"version": 1, "request_id": request_id, "event": {"type": "chunk", "data": {"text": "b"}}},
        ]
        tail = request_id.rsplit("-", 1)[1]
        offset = int(tail) if tail.isdigit() else int(request_id.rsplit("-", 2)[1])
        if self._cancel_every is not None and offset % self._cancel_every == 0:
            envelopes.append(
                {
                    "version": 1,
                    "request_id": request_id,
                    "event": {
                        "type": "status",
                        "data": {"phase": "cancelled", "message": "cancelled"},
                    },
                }
            )
        else:
            envelopes.append({"version": 1, "request_id": request_id, "event": {"type": "metric", "data": {}}})
        if on_envelope is not None:
            for envelope in envelopes:
                on_envelope(envelope)
        return envelopes

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)


def _is_terminal(envelope: dict[str, Any]) -> bool:
    event = envelope.get("event")
    if isinstance(event, dict):
        if event.get("type") in {"metric", "error"}:
            return True
        if event.get("type") == "status":
            return event.get("data", {}).get("phase") in TERMINAL_PHASES
    return False


def _error_code(envelope: dict[str, Any]) -> str | None:
    event = envelope.get("event")
    if isinstance(event, dict) and event.get("type") == "error":
        return event.get("data", {}).get("code")
    return None


def run_request(
    client: Any,
    request_id: str,
    *,
    cancel: bool,
    timeout_seconds: float,
) -> RequestOutcome:
    """Execute one full SSE request with cancellation when requested."""
    outcome = RequestOutcome(request_id=request_id)
    started = time.perf_counter()
    cancel_sent = False

    def maybe_cancel(envelope: dict[str, Any]) -> None:
        nonlocal cancel_sent
        if not cancel or cancel_sent:
            return
        event = envelope.get("event")
        if envelope.get("request_id") == request_id and isinstance(event, dict):
            if event.get("type") == "chunk":
                try:
                    client.cancel(request_id)
                except Exception:
                    outcome.failure = "cancel_failed"
                cancel_sent = True

    try:
        envelopes = client.optimize(
            request_id,
            cancel=cancel,
            on_envelope=maybe_cancel,
        )
    except Exception as error:
        outcome.failure = "http_error" if not isinstance(error, SoakFailure) else error.code
        outcome.failure_detail = type(error).__name__
        outcome.elapsed_ms = (time.perf_counter() - started) * 1000
        return outcome

    terminal_seen = False
    for envelope in envelopes:
        if envelope.get("request_id") != request_id:
            outcome.cross_talk = True
            continue
        event = envelope.get("event")
        if not isinstance(event, dict):
            continue
        if event.get("type") == "chunk":
            outcome.chunks += 1
        code = _error_code(envelope)
        if code == "runtime_busy":
            outcome.busy = True
            outcome.elapsed_ms = (time.perf_counter() - started) * 1000
            return outcome
        if code is not None:
            outcome.failure = code
            outcome.elapsed_ms = (time.perf_counter() - started) * 1000
            return outcome
        if _is_terminal(envelope) and not terminal_seen:
            terminal_seen = True
            event_type = envelope.get("event", {}).get("type")
            if event_type == "status":
                phase = envelope.get("event", {}).get("data", {}).get("phase")
                if phase == "cancelled":
                    outcome.cancelled = True
                elif phase == "completed":
                    outcome.completed = True
            elif event_type == "metric":
                outcome.completed = True
        elif terminal_seen and event.get("type") == "chunk":
            outcome.cross_talk = True

    outcome.elapsed_ms = (time.perf_counter() - started) * 1000
    if cancel and not outcome.cancelled and cancel_sent:
        outcome.failure = "expected_cancellation_missing"
    if not terminal_seen:
        outcome.missing_terminal = True
    return outcome


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile))
    return round(ordered[index], 1)


class SoakRunner:
    def __init__(
        self,
        *,
        client_factory: Callable[[str, float], Any],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_factory = client_factory
        self._clock = clock

    def run(
        self,
        *,
        levels: list[int],
        iterations: int,
        cancel_every: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        validate_limits(
            levels=levels,
            iterations=iterations,
            cancel_every=cancel_every,
            timeout_seconds=timeout_seconds,
        )
        level_reports = []
        for concurrency in levels:
            level_reports.append(
                self._run_level(
                    concurrency=concurrency,
                    iterations=iterations,
                    cancel_every=cancel_every,
                    timeout_seconds=timeout_seconds,
                )
            )
        passed = all(level["passed"] for level in level_reports)
        return {
            "schema_version": 1,
            "fixture": "http_mock_sse",
            "plan": {
                "levels": levels,
                "iterations_per_level": iterations,
                "cancel_every": cancel_every,
                "timeout_seconds": timeout_seconds,
            },
            "levels": level_reports,
            "passed": passed,
        }

    def _run_level(
        self,
        *,
        concurrency: int,
        iterations: int,
        cancel_every: int,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        outcomes: list[RequestOutcome] = []
        lock = threading.Lock()

        def worker(worker_index: int) -> None:
            for offset in range(worker_index, iterations, concurrency):
                request_id = f"http-soak-{worker_index:02d}-{offset:05d}"
                cancel = (offset % cancel_every == 0)
                outcome = run_request(
                    self._client_factory(request_id, timeout_seconds),
                    request_id,
                    cancel=cancel,
                    timeout_seconds=timeout_seconds,
                )
                if outcome.failure == "http_error":
                    # Transient connection-level errors get one retry so a
                    # single environment hiccup cannot fail the level.
                    retried_id = f"{request_id}-r"
                    retried = run_request(
                        self._client_factory(retried_id, timeout_seconds),
                        retried_id,
                        cancel=cancel,
                        timeout_seconds=timeout_seconds,
                    )
                    if retried.failure is None:
                        retried.retried = True
                        outcome = retried
                with lock:
                    outcomes.append(outcome)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(concurrency)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        completed = sum(1 for outcome in outcomes if outcome.completed)
        cancelled = sum(1 for outcome in outcomes if outcome.cancelled)
        busy = sum(1 for outcome in outcomes if outcome.busy)
        failures = [outcome for outcome in outcomes if outcome.failure is not None]
        cross_talk = sum(1 for outcome in outcomes if outcome.cross_talk)
        missing_terminal = sum(1 for outcome in outcomes if outcome.missing_terminal)
        latencies = [outcome.elapsed_ms for outcome in outcomes if outcome.elapsed_ms > 0]

        passed = (
            completed + cancelled + busy == len(outcomes)
            and not failures
            and not cross_talk
            and not missing_terminal
            and (completed + cancelled) > 0
        )
        failure_details = sorted(
            {outcome.failure_detail for outcome in outcomes if outcome.failure_detail}
        )
        retried = sum(1 for outcome in outcomes if outcome.retried)
        return {
            "concurrency": concurrency,
            "iterations": len(outcomes),
            "completed_requests": completed,
            "cancelled_requests": cancelled,
            "busy_requests": busy,
            "retried_requests": retried,
            "failures": sorted({outcome.failure for outcome in failures if outcome.failure}),
            "failure_details": failure_details,
            "cross_talk_requests": cross_talk,
            "missing_terminal_requests": missing_terminal,
            "latency_ms_p50": _percentile(latencies, 0.5),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "passed": passed,
        }


def validate_limits(
    *,
    levels: list[int],
    iterations: int,
    cancel_every: int,
    timeout_seconds: float,
) -> None:
    if not levels or any(not 1 <= level <= MAX_LEVELS for level in levels):
        raise ValueError(f"levels must be between 1 and {MAX_LEVELS}")
    if not 1 <= iterations <= MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")
    if not 2 <= cancel_every <= 100:
        raise ValueError("cancel-every must be between 2 and 100")
    if iterations < cancel_every:
        raise ValueError("iterations must be at least cancel-every")
    if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout-seconds must be greater than 0 and no more than {MAX_TIMEOUT_SECONDS}"
        )


def render_human_summary(report: dict[str, Any]) -> str:
    plan = report["plan"]
    conclusion = "通过" if report["passed"] else "未通过"
    lines = [
        "Reflex Next HTTP Host 并发浸泡",
        (
            f"计划: 并发 {plan['levels']} / 每档 {plan['iterations_per_level']} 次 / "
            f"取消每 {plan['cancel_every']} 次"
        ),
    ]
    for level in report["levels"]:
        lines.append(
            f"并发 {level['concurrency']}: 完成 {level['completed_requests']}、"
            f"取消 {level['cancelled_requests']}、busy {level['busy_requests']}、"
            f"P50 {level['latency_ms_p50']}ms / P95 {level['latency_ms_p95']}ms"
        )
    lines.append(f"结论: {conclusion}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Graded concurrency soak against a running reflex-http-host."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    parser.add_argument("--levels", default=DEFAULT_LEVELS)
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--cancel-every", type=int, default=DEFAULT_CANCEL_EVERY)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    levels = [int(part) for part in args.levels.split(",") if part.strip()]
    try:
        validate_limits(
            levels=levels,
            iterations=args.iterations,
            cancel_every=args.cancel_every,
            timeout_seconds=args.timeout_seconds,
        )
    except ValueError as error:
        print(f"参数错误: {error}", file=sys.stderr)
        return 2

    base_url = f"http://{args.host}:{args.port}"

    def client_factory(request_id: str, timeout_seconds: float) -> Any:
        return HttpSoakClient(base_url=base_url, timeout_seconds=timeout_seconds)

    report = SoakRunner(client_factory=client_factory).run(
        levels=levels,
        iterations=args.iterations,
        cancel_every=args.cancel_every,
        timeout_seconds=args.timeout_seconds,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output is not None:
        args.json_output.write_text(serialized + "\n", encoding="utf-8")
    print(render_human_summary(report), file=sys.stderr)
    print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
