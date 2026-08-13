"""Contract tests for the SidecarGateway routing layer (no subprocess)."""

from __future__ import annotations

import queue

import pytest

from reflex_http_host.gateway import (
    GatewayError,
    SidecarGateway,
    is_terminal_event,
    runtime_environment,
)

from conftest import FakeSession


def make_gateway(**kwargs) -> tuple[SidecarGateway, FakeSession]:
    session = FakeSession(timeout_seconds=kwargs.pop("session_timeout_seconds", 5.0))
    gateway = SidecarGateway(
        session_factory=lambda _: session,
        session_timeout_seconds=5.0,
        **kwargs,
    )
    return gateway, session


def wait_for_envelope(subscription, timeout: float = 1.0) -> dict:
    return subscription.queue.get(timeout=timeout)


def test_send_command_builds_protocol_envelope():
    gateway, session = make_gateway()
    gateway.start()
    request_id = gateway.send_command("optimize", {"text": "hello"})

    assert len(session.sent) == 1
    command = session.sent[0]
    assert command["version"] == 1
    assert command["request_id"] == request_id
    assert command["type"] == "optimize"
    assert command["payload"] == {"text": "hello"}
    assert request_id


def test_send_command_requires_started_gateway():
    gateway, _ = make_gateway()
    with pytest.raises(GatewayError) as exc:
        gateway.send_command("ping")
    assert exc.value.code == "runtime_unavailable"


def test_dispatch_routes_events_by_request_id():
    gateway, session = make_gateway()
    gateway.start()
    request_id = "req-1"
    subscription = gateway.subscribe(request_id)

    session.emit({"version": 1, "request_id": request_id, "event": {"type": "chunk", "data": {}}})
    envelope = wait_for_envelope(subscription)
    assert envelope["event"]["type"] == "chunk"
    assert subscription.terminal is False


def test_dispatch_marks_terminal_and_ignores_later_events():
    gateway, session = make_gateway()
    gateway.start()
    subscription = gateway.subscribe("req-2")

    session.emit({"version": 1, "request_id": "req-2", "event": {"type": "metric", "data": {}}})
    wait_for_envelope(subscription)
    assert subscription.terminal is True

    session.emit({"version": 1, "request_id": "req-2", "event": {"type": "chunk", "data": {}}})
    assert subscription.queue.empty()


def test_unsubscribe_stops_routing():
    gateway, session = make_gateway()
    gateway.start()
    subscription = gateway.subscribe("req-3")
    gateway.unsubscribe("req-3")

    session.emit({"version": 1, "request_id": "req-3", "event": {"type": "chunk", "data": {}}})
    assert subscription.queue.empty()


def test_close_cancels_active_subscriptions_and_closes_session():
    gateway, session = make_gateway()
    gateway.start()
    gateway.subscribe("req-4")
    gateway.subscribe("req-5")

    assert gateway.close() is True
    assert session.closed is True
    cancelled = [command for command in session.sent if command["type"] == "cancel"]
    assert {command["request_id"] for command in cancelled} == {"req-4", "req-5"}


def test_close_is_idempotent():
    gateway, session = make_gateway()
    gateway.start()
    assert gateway.close() is True
    assert gateway.close() is True
    assert session.closed is True


def test_is_terminal_event_status_phases():
    for phase in ("completed", "cancelled", "error"):
        envelope = {"version": 1, "request_id": "r", "event": {"type": "status", "data": {"phase": phase}}}
        assert is_terminal_event(envelope) is True
    envelope = {"version": 1, "request_id": "r", "event": {"type": "status", "data": {"phase": "streaming"}}}
    assert is_terminal_event(envelope) is False


def test_is_terminal_event_types():
    for event_type in ("metric", "error"):
        envelope = {"version": 1, "request_id": "r", "event": {"type": event_type, "data": {}}}
        assert is_terminal_event(envelope) is True
    for event_type in ("chunk", "done", "scene", "request"):
        envelope = {"version": 1, "request_id": "r", "event": {"type": event_type, "data": {}}}
        assert is_terminal_event(envelope) is False


def test_is_terminal_event_flat_runtime_envelopes():
    for envelope_type in (
        "provider_catalog",
        "provider_models",
        "provider_connection_result",
        "capability_list",
        "plugin_event",
    ):
        envelope = {"version": 1, "request_id": "r", "type": envelope_type}
        assert is_terminal_event(envelope) is True


def test_runtime_environment_does_not_inherit_credentials(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "fixture-private-value")
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-private-value")
    monkeypatch.setenv("REFLEX_RUNTIME_DEVELOPMENT", "1")
    child_environment = runtime_environment()

    assert child_environment["REFLEX_RUNTIME_DEVELOPMENT"] == "1"
    assert "MINIMAX_API_KEY" not in child_environment
    assert "OPENAI_API_KEY" not in child_environment


def test_runtime_environment_development_can_be_disabled(monkeypatch):
    monkeypatch.setenv("REFLEX_RUNTIME_DEVELOPMENT", "0")
    child_environment = runtime_environment()
    assert "REFLEX_RUNTIME_DEVELOPMENT" not in child_environment
