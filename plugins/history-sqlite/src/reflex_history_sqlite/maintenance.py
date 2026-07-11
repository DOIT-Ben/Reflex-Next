"""Process-local writer freeze shared by history calls and maintenance."""

from __future__ import annotations

from contextlib import contextmanager
from threading import Condition, RLock
from typing import Any, Iterator

from .contract import HistoryPluginError


class MaintenanceCoordinator:
    def __init__(self) -> None:
        self._condition = Condition(RLock())
        self._maintenance = False
        self._block_reads = False
        self._active_reads = 0
        self._active_writes = 0

    @property
    def active(self) -> bool:
        with self._condition:
            return self._maintenance

    @contextmanager
    def read(self) -> Iterator[None]:
        with self._condition:
            if self._maintenance and self._block_reads:
                raise HistoryPluginError("history_busy")
            self._active_reads += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_reads -= 1
                self._condition.notify_all()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._condition:
            if self._maintenance:
                raise HistoryPluginError("history_busy")
            self._active_writes += 1
        try:
            yield
        finally:
            with self._condition:
                self._active_writes -= 1
                self._condition.notify_all()

    def begin(self, cancellation: Any, *, block_reads: bool = False) -> None:
        with self._condition:
            if self._maintenance:
                raise HistoryPluginError("history_busy")
            self._maintenance = True
            self._block_reads = block_reads
            try:
                while self._active_writes or (block_reads and self._active_reads):
                    cancellation.raise_if_cancelled()
                    self._condition.wait(0.05)
            except BaseException:
                self._maintenance = False
                self._block_reads = False
                self._condition.notify_all()
                raise

    def end(self) -> None:
        with self._condition:
            self._maintenance = False
            self._block_reads = False
            self._condition.notify_all()

    def allow_reads(self) -> None:
        with self._condition:
            if not self._maintenance:
                raise HistoryPluginError("history_busy")
            self._block_reads = False
            self._condition.notify_all()

    def block_reads(self, cancellation: Any) -> None:
        with self._condition:
            if not self._maintenance:
                raise HistoryPluginError("history_busy")
            self._block_reads = True
            while self._active_reads:
                cancellation.raise_if_cancelled()
                self._condition.wait(0.05)
