"""Process-local coordination for the optional semantic model lifecycle."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class ModelLifecycleBusy(RuntimeError):
    pass


class ModelLifecycle:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0

    @contextmanager
    def enter(self, *, blocking: bool = False) -> Iterator[None]:
        if not self._lock.acquire(blocking=blocking):
            raise ModelLifecycleBusy
        try:
            yield
        finally:
            self._lock.release()

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def try_generation(self) -> int | None:
        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self._generation
        finally:
            self._lock.release()

    def invalidate(self) -> int:
        with self._lock:
            self._generation += 1
            return self._generation


MODEL_LIFECYCLE = ModelLifecycle()
