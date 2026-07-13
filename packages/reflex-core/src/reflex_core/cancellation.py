"""Framework-independent cancellation primitives."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event as ThreadEvent
from threading import Lock


CancelCallback = Callable[[], None]
UnregisterCallback = Callable[[], None]


class OperationCancelled(RuntimeError):
    """Raised when a running optimization is cancelled."""


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = ThreadEvent()
        self._lock = Lock()
        self._callbacks: dict[int, CancelCallback] = {}
        self._next_callback_id = 0

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(reversed(tuple(self._callbacks.values())))
            self._callbacks.clear()

        for callback in callbacks:
            self._notify(callback)

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled("operation cancelled")

    def register(self, callback: CancelCallback) -> UnregisterCallback:
        """Register a one-shot callback and return an idempotent unregister function."""
        if not callable(callback):
            raise TypeError("callback must be callable")

        with self._lock:
            if self._event.is_set():
                callback_id = None
            else:
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback

        if callback_id is None:
            self._notify(callback)

        def unregister() -> None:
            if callback_id is None:
                return
            with self._lock:
                self._callbacks.pop(callback_id, None)

        return unregister

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until cancellation or timeout, returning whether cancellation won."""
        return self._event.wait(timeout)

    @staticmethod
    def _notify(callback: CancelCallback) -> None:
        try:
            callback()
        except Exception:
            pass
