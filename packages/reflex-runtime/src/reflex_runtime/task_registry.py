"""Thread-safe ownership of globally unique Runtime request IDs."""

from __future__ import annotations

from contextlib import contextmanager
from threading import RLock
from typing import Iterator

from reflex_core import CancellationToken


class DuplicateRequestId(RuntimeError):
    code = "duplicate_request_id"

    def __init__(self) -> None:
        super().__init__(self.code)


class TaskRegistry:
    def __init__(self) -> None:
        self._tokens: dict[str, CancellationToken] = {}
        self._lock = RLock()

    def register(self, request_id: str) -> CancellationToken:
        token = CancellationToken()
        with self._lock:
            if request_id in self._tokens:
                raise DuplicateRequestId()
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
