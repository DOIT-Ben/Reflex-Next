"""Shared fixtures for reflex-http-host tests (no subprocess)."""

from __future__ import annotations

import queue

import pytest

from reflex_http_host.gateway import GatewayError, SidecarGateway


class FakeSession:
    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self.sent: list[dict] = []
        self.closed = False
        self._events: queue.Queue[dict] = queue.Queue()
        self.returncode: int | None = None

    def events(self):
        return self._events

    def poll(self):
        return self.returncode

    def send(self, command: dict) -> None:
        if self.returncode is not None:
            raise GatewayError("runtime_exited", "Runtime process is not running.")
        self.sent.append(command)

    def close(self) -> bool:
        self.closed = True
        return True

    def emit(self, envelope: dict) -> None:
        self._events.put(envelope)


@pytest.fixture
def fake_session():
    return FakeSession(timeout_seconds=5.0)


@pytest.fixture
def gateway(fake_session):
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    return gateway, fake_session
