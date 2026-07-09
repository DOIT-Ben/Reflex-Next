"""Framework-independent cancellation primitives."""

from __future__ import annotations

from threading import Event as ThreadEvent


class OperationCancelled(RuntimeError):
    """Raised when a running optimization is cancelled."""


class CancellationToken:
    """Thread-safe cooperative cancellation token."""

    def __init__(self) -> None:
        self._event = ThreadEvent()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise OperationCancelled("operation cancelled")
