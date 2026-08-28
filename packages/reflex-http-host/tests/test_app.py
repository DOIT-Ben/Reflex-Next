"""Contract tests for the FastAPI SSE application.

Routing-level behaviour uses a FakeSession; end-to-end behaviour (SSE
streaming, ping, provider catalog) runs against one real runtime sidecar
subprocess shared at module scope.
"""

from __future__ import annotations

import json
import os
import queue

import pytest
from fastapi.testclient import TestClient

from reflex_http_host.app import create_app
from reflex_http_host.app import validate_bind_security
from reflex_http_host.gateway import SidecarGateway

from conftest import FakeSession


@pytest.fixture
def client(fake_session):
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    app = create_app(gateway, bind_host="127.0.0.1")
    with TestClient(app) as test_client:
        yield test_client, fake_session


@pytest.fixture(scope="module")
def live_client():
    previous_development = os.environ.get("REFLEX_RUNTIME_DEVELOPMENT")
    try:
        os.environ["REFLEX_RUNTIME_DEVELOPMENT"] = "1"
        gateway = SidecarGateway(request_timeout_seconds=10.0)
        app = create_app(gateway, bind_host="127.0.0.1")
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if previous_development is None:
            os.environ.pop("REFLEX_RUNTIME_DEVELOPMENT", None)
        else:
            os.environ["REFLEX_RUNTIME_DEVELOPMENT"] = previous_development


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


def test_optimize_rejects_active_request_id_with_conflict(client):
    test_client, _ = client
    gateway = test_client.app.state.gateway
    gateway.subscribe("req-active")
    try:
        response = test_client.post(
            "/v1/optimize",
            json={"text": "hello", "request_id": "req-active"},
        )
    finally:
        gateway.unsubscribe("req-active")
    assert response.status_code == 409
    assert response.json()["detail"] == "Request id is already active."


def test_optimize_without_provider_reports_unconfigured(client):
    test_client, _ = client
    with test_client.stream(
        "POST", "/v1/optimize", json={"text": "hello"}
    ) as response:
        envelopes = parse_sse(list(response.iter_lines()))
    assert envelopes[-1]["event"]["data"]["code"] == "provider_unconfigured"


def test_optimize_passes_scene_and_mode_fields(client):
    test_client, fake_session = client
    with test_client.stream(
        "POST",
        "/v1/optimize",
        json={
            "text": "hello",
            "mode": "prompt",
            "scene": "marketing:headline",
            "scene_policy": "manual",
            "stream": False,
            "style": "creative",
        },
    ):
        pass
    optimize = [command for command in fake_session.sent if command["type"] == "optimize"][-1]
    assert optimize["payload"]["mode"] == "prompt"
    assert optimize["payload"]["scene"] == "marketing:headline"
    assert optimize["payload"]["scene_policy"] == "manual"
    assert optimize["payload"]["stream"] is False
    assert optimize["payload"]["style"] == "creative"


def test_optimize_request_timeout_sends_cancel_and_error_event(fake_session):
    gateway = SidecarGateway(
        session_factory=lambda _: fake_session,
        request_timeout_seconds=0.2,
    )
    app = create_app(gateway, bind_host="127.0.0.1")
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


def test_auth_required_when_token_configured(fake_session, monkeypatch):
    monkeypatch.setenv("REFLEX_HTTP_TOKEN", "fixture-token")
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    with TestClient(create_app(gateway, bind_host="127.0.0.1")) as test_client:
        denied = test_client.get("/v1/health")
        assert denied.status_code == 401

        allowed = test_client.get(
            "/v1/health", headers={"Authorization": "Bearer fixture-token"}
        )
        assert allowed.status_code == 200


def test_auth_optional_without_token(client):
    test_client, _ = client
    assert test_client.get("/v1/health").status_code == 200


def test_non_loopback_host_requires_token(monkeypatch):
    monkeypatch.delenv("REFLEX_HTTP_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="REFLEX_HTTP_TOKEN is required"):
        validate_bind_security("0.0.0.0")


def test_non_loopback_host_accepts_explicit_token(monkeypatch):
    monkeypatch.delenv("REFLEX_HTTP_TOKEN", raising=False)
    validate_bind_security("0.0.0.0", token="fixture-token")


def test_create_app_validates_explicit_bind_host(monkeypatch, fake_session):
    monkeypatch.delenv("REFLEX_HTTP_TOKEN", raising=False)
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    with pytest.raises(RuntimeError, match="REFLEX_HTTP_TOKEN is required"):
        create_app(gateway, bind_host="0.0.0.0")


def test_create_app_cannot_be_used_as_an_unvalidated_uvicorn_factory():
    with pytest.raises(TypeError, match="bind_host"):
        create_app()


def test_create_app_records_validated_bind_host(monkeypatch, fake_session):
    monkeypatch.setenv("REFLEX_HTTP_TOKEN", "fixture-token")
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    app = create_app(gateway, bind_host="192.0.2.10")
    assert app.state.bind_host == "192.0.2.10"


def test_create_app_freezes_token_for_request_authorization(monkeypatch, fake_session):
    monkeypatch.setenv("REFLEX_HTTP_TOKEN", "fixture-token")
    gateway = SidecarGateway(session_factory=lambda _: fake_session)
    app = create_app(gateway, bind_host="192.0.2.10")
    monkeypatch.delenv("REFLEX_HTTP_TOKEN")

    with TestClient(app) as test_client:
        assert test_client.get("/v1/health").status_code == 401
        assert (
            test_client.get(
                "/v1/health", headers={"Authorization": "Bearer fixture-token"}
            ).status_code
            == 200
        )


def test_scene_catalog_returns_grouped_library(client):
    test_client, _ = client
    response = test_client.get("/v1/scenes")
    assert response.status_code == 200
    body = response.json()

    assert len(body["categories"]) == 10
    business = next(category for category in body["categories"] if category["id"] == "business")
    assert "email" in business["scenes"]
    assert "resume" in business["scenes"]
    marketing = next(category for category in body["categories"] if category["id"] == "marketing")
    assert "headline" in marketing["scenes"]

    scene_ids = {scene["id"] for scene in body["scenes"]}
    assert len(scene_ids) >= 49
    assert {"email", "resume", "prd", "general"}.issubset(scene_ids)
    assert body["unclassified"] == ["general"]


def test_optimize_rejects_unknown_manual_scene(client):
    test_client, _ = client
    response = test_client.post(
        "/v1/optimize",
        json={
            "text": "hello",
            "scene": "no_such_scene_xyz",
            "scene_policy": "manual",
        },
    )
    assert response.status_code == 422
    assert "GET /v1/scenes" in response.json()["detail"]


def test_optimize_accepts_known_category_and_subscene(client):
    test_client, _ = client
    for scene_value in ("business:email", "business", "email", "marketing:headline"):
        with test_client.stream(
            "POST",
            "/v1/optimize",
            json={
                "text": "hello",
                "scene": scene_value,
                "scene_policy": "manual",
            },
        ) as response:
            assert response.status_code == 200, scene_value


def test_optimize_ignores_scene_under_auto_policy(client):
    """scene is ignored under the default auto policy (no 422, no rejection)."""
    test_client, _ = client
    with test_client.stream(
        "POST",
        "/v1/optimize",
        json={"text": "hello", "scene": "no_such_scene_xyz"},
    ) as response:
        assert response.status_code == 200


def test_optimize_rejects_unknown_scene_policy(client):
    test_client, _ = client
    response = test_client.post(
        "/v1/optimize",
        json={"text": "hello", "scene_policy": "unsupported"},
    )
    assert response.status_code == 422


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


def test_live_optimize_manual_scene_returns_scene_event(live_client):
    with live_client.stream(
        "POST",
        "/v1/optimize",
        json={
            "text": "hello",
            "provider": "mock",
            "model": "mock-stream",
            "scene": "marketing:headline",
            "scene_policy": "manual",
        },
    ) as response:
        lines = list(response.iter_lines())

    envelopes = parse_sse(lines)
    scene_envelopes = [
        envelope for envelope in envelopes
        if envelope.get("event", {}).get("type") == "scene"
    ]
    assert len(scene_envelopes) == 1
    assert scene_envelopes[0]["event"]["data"]["scene"] == "headline"
    assert scene_envelopes[0]["event"]["data"]["category"] == "marketing"
    assert scene_envelopes[0]["event"]["data"]["method"] == "manual"


def test_live_optimize_category_colon_scene_reports_category(live_client):
    with live_client.stream(
        "POST",
        "/v1/optimize",
        json={
            "text": "hello",
            "provider": "mock",
            "model": "mock-stream",
            "scene": "business:email",
            "scene_policy": "manual",
        },
    ) as response:
        lines = list(response.iter_lines())

    envelopes = parse_sse(lines)
    scene_envelopes = [
        envelope for envelope in envelopes
        if envelope.get("event", {}).get("type") == "scene"
    ]
    assert len(scene_envelopes) == 1
    assert scene_envelopes[0]["event"]["data"]["scene"] == "email"
    assert scene_envelopes[0]["event"]["data"]["category"] == "business"
    assert scene_envelopes[0]["event"]["data"]["method"] == "manual"
