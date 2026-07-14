"""Thread-safe request ownership and bounded Runtime task scheduling."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition, RLock, Thread, current_thread
from typing import Any, Iterator

from reflex_core import CancellationToken


class DuplicateRequestId(RuntimeError):
    code = "duplicate_request_id"

    def __init__(self) -> None:
        super().__init__(self.code)


class TaskCapacityExceeded(RuntimeError):
    code = "runtime_busy"

    def __init__(self) -> None:
        super().__init__(self.code)


class TaskSchedulerClosed(RuntimeError):
    pass


@dataclass(frozen=True)
class _QueuedTask:
    request_id: str
    token: CancellationToken
    run: Callable[[CancellationToken], None]
    on_cancel: Callable[[], None]


class TaskRegistry:
    def __init__(self, max_tasks: int = 32) -> None:
        if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1:
            raise ValueError("max_tasks must be a positive integer")
        self._max_tasks = max_tasks
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = RLock()

    def register(
        self, request_id: str, *, enforce_capacity: bool = True
    ) -> CancellationToken:
        token = CancellationToken()
        with self._lock:
            if request_id in self._tokens:
                raise DuplicateRequestId()
            if enforce_capacity and len(self._tokens) >= self._max_tasks:
                raise TaskCapacityExceeded()
            self._tokens[request_id] = token
        return token

    @contextmanager
    def task(self, request_id: str) -> Iterator[CancellationToken]:
        token = self.register(request_id)
        try:
            yield token
        finally:
            self.cleanup(request_id, token)

    def cleanup(self, request_id: str, token: CancellationToken) -> None:
        with self._lock:
            if self._tokens.get(request_id) is token:
                self._tokens.pop(request_id, None)

    def is_active(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._tokens

    def cancel(self, request_id: str) -> bool:
        with self._lock:
            token = self._tokens.get(request_id)
        if token is None:
            return False
        token.cancel()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            tokens = tuple(self._tokens.values())
        for token in tokens:
            token.cancel()

    def has_tasks(self) -> bool:
        with self._lock:
            return bool(self._tokens)


class BoundedTaskScheduler:
    """Run tasks on fixed workers with a bounded FIFO waiting queue."""

    def __init__(
        self,
        registry: TaskRegistry,
        *,
        max_workers: int = 4,
        max_queue: int = 32,
        thread_factory: Any = Thread,
    ) -> None:
        for name, value in (("max_workers", max_workers), ("max_queue", max_queue)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self._registry = registry
        self._max_workers = max_workers
        self._max_queue = max_queue
        self._thread_factory = thread_factory
        self._condition = Condition(RLock())
        self._queue: deque[_QueuedTask] = deque()
        self._active: dict[str, _QueuedTask] = {}
        self._workers: list[Any] = []
        self._started = False
        self._closed = False

    def submit(
        self,
        request_id: str,
        run: Callable[[CancellationToken], None],
        *,
        on_cancel: Callable[[], None],
    ) -> CancellationToken:
        self._ensure_workers_started()
        token = self._registry.register(request_id, enforce_capacity=False)
        task = _QueuedTask(request_id, token, run, on_cancel)
        with self._condition:
            if self._closed:
                self._registry.cleanup(request_id, token)
                raise TaskSchedulerClosed()
            if len(self._active) + len(self._queue) >= self._max_workers + self._max_queue:
                self._registry.cleanup(request_id, token)
                raise TaskCapacityExceeded()
            self._queue.append(task)
            self._condition.notify()
        return token

    def cancel(self, request_id: str) -> bool:
        cancelled_task: _QueuedTask | None = None
        with self._condition:
            for task in self._queue:
                if task.request_id == request_id:
                    self._queue.remove(task)
                    cancelled_task = task
                    break
            if cancelled_task is None:
                task = self._active.get(request_id)
                if task is None:
                    return False
                task.token.cancel()
                return True
        cancelled_task.token.cancel()
        self._registry.cleanup(cancelled_task.request_id, cancelled_task.token)
        self._notify_cancelled(cancelled_task)
        return True

    def cancel_all(self) -> None:
        with self._condition:
            queued = tuple(self._queue)
            self._queue.clear()
            active = tuple(self._active.values())
        for task in active:
            task.token.cancel()
        for task in queued:
            task.token.cancel()
            self._registry.cleanup(task.request_id, task.token)
            self._notify_cancelled(task)

    def close(self, timeout: float = 1.0) -> None:
        with self._condition:
            self._closed = True
            queued = tuple(self._queue)
            self._queue.clear()
            active = tuple(self._active.values())
            workers = tuple(self._workers)
            self._condition.notify_all()
        for task in active:
            task.token.cancel()
        for task in queued:
            task.token.cancel()
            self._registry.cleanup(task.request_id, task.token)
            self._notify_cancelled(task)
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in workers:
            if worker is current_thread():
                continue
            worker.join(timeout=max(0.0, deadline - time.monotonic()))

    @property
    def worker_count(self) -> int:
        with self._condition:
            return len(self._workers)

    @property
    def live_worker_count(self) -> int:
        with self._condition:
            return sum(worker.is_alive() for worker in self._workers)

    def _ensure_workers_started(self) -> None:
        with self._condition:
            if self._closed:
                raise TaskSchedulerClosed()
            if self._started:
                return
            try:
                for index in range(self._max_workers):
                    worker = self._thread_factory(
                        target=self._worker,
                        daemon=True,
                        name=f"reflex-optimize-{index + 1}",
                    )
                    worker.start()
                    self._workers.append(worker)
            except Exception:
                self._closed = True
                self._condition.notify_all()
                raise
            self._started = True

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._closed:
                    self._condition.wait()
                if self._closed and not self._queue:
                    return
                task = self._queue.popleft()
                self._active[task.request_id] = task
            try:
                if task.token.is_cancelled:
                    self._notify_cancelled(task)
                else:
                    task.run(task.token)
            except Exception:
                pass
            finally:
                self._registry.cleanup(task.request_id, task.token)
                with self._condition:
                    self._active.pop(task.request_id, None)
                    self._condition.notify_all()

    @staticmethod
    def _notify_cancelled(task: _QueuedTask) -> None:
        try:
            task.on_cancel()
        except Exception:
            pass
