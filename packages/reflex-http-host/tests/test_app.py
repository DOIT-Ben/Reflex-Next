"""Contract tests for the FastAPI SSE application.

Routing-level behaviour uses a FakeSession; end-to-end behaviour (SSE
streaming, ping, provider catalog) runs against one real runtime sidecar
subprocess shared at module scope.
"""

from __future__ import annotations

import json
import queue

import pytest
from fastapi.testclient import TestClient

from reflex_http_host.app import create_app
from reflex_http_host.gateway import SidecarGateway

from conftest import FakeSession


@pytest.fixture
def client(fake_session):
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    app = create_app(gateway)
    with TestClient(app) as test_client:
        yield test_client, fake_session


@pytest.fixture(scope="module")
def live_client():
    gateway = SidecarGateway(request_timeout_seconds=10.0)
    app = create_app(gateway)
    with TestClient(app) as test_client:
        yield test_client


def parse_sse(lines: list[str]) -> list[dict]:
    payloads = []
    for line in lines:
        line = line.strip()
        if line.startswith("data: "):
            payloads.append(json.loads(line[6:]))
    return payloads


def test_health_reports_runtime_alive(client):
    test_client, _ = client
    response = test_client.get("/v1/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_ping_sends_ping_command(client):
    test_client, fake_session = client
    response = test_client.post("/v1/ping")
    assert response.status_code == 504
    assert fake_session.sent[-1]["type"] == "ping"


def test_cancel_endpoint_sends_cancel_command(client):
    test_client, fake_session = client
    response = test_client.post("/v1/requests/req-9/cancel")
    assert response.status_code == 200
    assert response.json() == {"cancelled": True, "request_id": "req-9"}
    assert fake_session.sent[-1] == {
        "version": 1,
        "request_id": "req-9",
        "type": "cancel",
        "payload": {},
    }


def test_optimize_requires_text(client):
    test_client, _ = client
    response = test_client.post("/v1/optimize", json={})
    assert response.status_code == 422


def test_optimize_request_timeout_sends_cancel_and_error_event(fake_session):
    gateway = SidecarGateway(
        session_factory=lambda _: fake_session,
        request_timeout_seconds=0.2,
    )
    app = create_app(gateway)
    with TestClient(app) as test_client:
        with test_client.stream(
            "POST",
            "/v1/optimize",
            json={"text": "hello", "provider": "mock", "model": "mock-stream"},
        ) as response:
            lines = list(response.iter_lines())

    envelopes = parse_sse(lines)
    assert envelopes[-1]["event"]["type"] == "error"
    assert envelopes[-1]["event"]["data"]["code"] == "request_timeout"
    cancels = [command for command in fake_session.sent if command["type"] == "cancel"]
    assert len(cancels) >= 1


def test_auth_required_when_token_configured(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setenv("REFLEX_HTTP_TOKEN", "fixture-token")

    denied = test_client.get("/v1/health")
    assert denied.status_code == 401

    allowed = test_client.get("/v1/health", headers={"Authorization": "Bearer fixture-token"})
    assert allowed.status_code == 200


def test_auth_optional_without_token(client):
    test_client, _ = client
    assert test_client.get("/v1/health").status_code == 200


def test_live_ping_returns_pong(live_client):
    response = live_client.post("/v1/ping")
    assert response.status_code == 200
    body = response.json()
    assert body["pong"] is True
    assert body["request_id"]


def test_live_providers_returns_catalog(live_client):
    response = live_client.get("/v1/providers")
    assert response.status_code == 200
    assert "providers" in response.json()


def test_live_optimize_streams_full_event_sequence(live_client):
    with live_client.stream(
        "POST",
        "/v1/optimize",
        json={"text": "hello", "provider": "mock", "model": "mock-stream"},
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = list(response.iter_lines())

    envelopes = parse_sse(lines)
    event_types = [envelope["event"]["type"] for envelope in envelopes]
    assert "chunk" in event_types
    assert event_types[-1] == "metric"
    assert all(envelope["request_id"] for envelope in envelopes)


def test_live_optimize_without_provider_reports_unconfigured(live_client):
    with live_client.stream(
        "POST",
        "/v1/optimize",
        json={"text": "hello"},
    ) as response:
        lines = list(response.iter_lines())

    envelopes = parse_sse(lines)
    assert envelopes[-1]["event"]["type"] == "error"
    assert envelopes[-1]["event"]["data"]["code"] == "provider_unconfigured"
