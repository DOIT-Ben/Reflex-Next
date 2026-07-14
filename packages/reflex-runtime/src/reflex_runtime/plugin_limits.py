"""Bounded resource accounting for trusted Runtime plugin calls."""

from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

from reflex_core import CancellationToken


DEFAULT_PLUGIN_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_PLUGIN_EVENTS = 50_000
DEFAULT_MAX_PLUGIN_OUTPUT_BYTES = 2 * 1024 * 1024
DEFAULT_MAX_PLUGIN_CONCURRENCY = 4
DEFAULT_PLUGIN_EVENT_BUFFER = 64

_Message = TypeVar("_Message")


class PluginLimitExceeded(RuntimeError):
    """A plugin call exceeded a stable Runtime resource budget."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PluginCallBudget:
    """Track one plugin call's deadline and emitted output budget."""

    def __init__(
        self,
        cancellation: CancellationToken,
        *,
        timeout_seconds: float = DEFAULT_PLUGIN_TIMEOUT_SECONDS,
        max_events: int = DEFAULT_MAX_PLUGIN_EVENTS,
        max_output_bytes: int = DEFAULT_MAX_PLUGIN_OUTPUT_BYTES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("plugin timeout must be positive")
        if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events <= 0:
            raise ValueError("plugin event limit must be positive")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or max_output_bytes <= 0
        ):
            raise ValueError("plugin output limit must be positive")

        self._cancellation = cancellation
        self._clock = clock
        self._deadline = clock() + float(timeout_seconds)
        self._max_events = max_events
        self._max_output_bytes = max_output_bytes
        self._events = 0
        self._output_bytes = 0
        self._expired = threading.Event()
        self._timer = threading.Timer(float(timeout_seconds), self._expire)
        self._timer.daemon = True
        self._timer.start()

    @property
    def expired(self) -> bool:
        return self._expired.is_set() or self._clock() >= self._deadline

    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - self._clock())

    def check(self) -> None:
        if self.expired:
            self._expired.set()
            self._cancellation.cancel()
            raise PluginLimitExceeded("plugin_timeout")

    def account_event(self, data: dict[str, Any]) -> None:
        self.check()
        self._events += 1
        if self._events > self._max_events:
            raise PluginLimitExceeded("plugin_event_limit")
        try:
            encoded = json.dumps(
                data,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as error:
            raise PluginLimitExceeded("plugin_invalid_result") from error
        self._output_bytes += len(encoded)
        if self._output_bytes > self._max_output_bytes:
            raise PluginLimitExceeded("plugin_output_too_large")

    def close(self) -> None:
        self._timer.cancel()

    def _expire(self) -> None:
        self._expired.set()
        self._cancellation.cancel()


@dataclass(frozen=True)
class PluginExecutionFailure:
    error: Exception


class PluginExecution(Generic[_Message]):
    def __init__(self, cancellation: CancellationToken, max_buffered_events: int) -> None:
        self._cancellation = cancellation
        self._messages: queue.Queue[_Message | PluginExecutionFailure] = queue.Queue(
            maxsize=max_buffered_events
        )
        self._completed = threading.Event()

    @property
    def completed(self) -> bool:
        return self._completed.is_set()

    def receive(self, timeout: float) -> _Message | PluginExecutionFailure:
        return self._messages.get(timeout=timeout)

    def send(self, message: _Message | PluginExecutionFailure) -> bool:
        while not self._cancellation.is_cancelled:
            try:
                self._messages.put(message, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def mark_completed(self) -> None:
        self._completed.set()


class BoundedPluginExecutor:
    """Isolate plugin iteration from Runtime workers without unbounded threads."""

    def __init__(
        self,
        *,
        max_workers: int = DEFAULT_MAX_PLUGIN_CONCURRENCY,
        max_buffered_events: int = DEFAULT_PLUGIN_EVENT_BUFFER,
        thread_factory: Any = threading.Thread,
    ) -> None:
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0:
            raise ValueError("plugin concurrency must be positive")
        if (
            isinstance(max_buffered_events, bool)
            or not isinstance(max_buffered_events, int)
            or max_buffered_events <= 0
        ):
            raise ValueError("plugin event buffer must be positive")
        self._slots = threading.BoundedSemaphore(max_workers)
        self._max_buffered_events = max_buffered_events
        self._thread_factory = thread_factory
        self._lock = threading.Lock()
        self._threads: set[Any] = set()
        self._closed = False

    def submit(
        self,
        cancellation: CancellationToken,
        run: Callable[[Callable[[_Message], bool]], None],
    ) -> PluginExecution[_Message]:
        with self._lock:
            if self._closed:
                raise PluginLimitExceeded("plugin_busy")
            if not self._slots.acquire(blocking=False):
                raise PluginLimitExceeded("plugin_busy")

        execution: PluginExecution[_Message] = PluginExecution(
            cancellation, self._max_buffered_events
        )
        try:
            thread = self._thread_factory(
                target=self._run,
                args=(execution, run),
                daemon=True,
                name="reflex-plugin-call",
            )
        except Exception:
            self._slots.release()
            raise
        with self._lock:
            if self._closed:
                self._slots.release()
                raise PluginLimitExceeded("plugin_busy")
            self._threads.add(thread)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._threads.discard(thread)
            self._slots.release()
            raise
        return execution

    def close(self, timeout: float = 1.0) -> None:
        with self._lock:
            self._closed = True
            threads = tuple(self._threads)
        deadline = time.monotonic() + max(0.0, timeout)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._threads)

    def _run(
        self,
        execution: PluginExecution[_Message],
        run: Callable[[Callable[[_Message], bool]], None],
    ) -> None:
        try:
            run(execution.send)
        except Exception as error:
            execution.send(PluginExecutionFailure(error))
        finally:
            execution.mark_completed()
            with self._lock:
                self._threads.discard(threading.current_thread())
            self._slots.release()
