from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from reflex_core import OptimizeUseCase
from reflex_core.testing import FakeProvider, FakeSceneDetector, FakeTemplateResolver

from reflex_cloud.app import create_app
from reflex_cloud.config import CloudSettings
from reflex_cloud.models import HourlyIpUsage, ImprovementSample
from reflex_cloud.optimizer import CloudOptimizer, CloudOptimizerError


def _client(
    tmp_path, *, request_limit: int = 2, ip_limit: int = 60
) -> Iterator[tuple[TestClient, CloudOptimizer]]:
    settings = CloudSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
        upload_directory=tmp_path / "uploads",
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
        free_requests_per_day=request_limit,
        free_ip_requests_per_hour=ip_limit,
        provider_model="MiniMax-M2.7-highspeed",
        provider_pricing_version="minimax-2026-07-14",
        provider_input_usd_per_million_tokens=1.0,
        provider_output_usd_per_million_tokens=2.0,
    )
    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(),
        template_resolver=FakeTemplateResolver(),
        provider=FakeProvider(("优化", "结果")),
    )
    optimizer = CloudOptimizer(settings, use_case)
    with TestClient(create_app(settings, optimizer)) as client:
        yield client, optimizer


def _identity(client: TestClient) -> tuple[str, dict[str, str]]:
    installation = client.post("/v1/installations").json()
    return installation["installation_id"], {
        "X-Reflex-Installation-Token": installation["token"]
    }


def _payload(request_id: str, text: str = "请优化这段文字") -> dict[str, object]:
    return {
        "request_id": request_id,
        "text": text,
        "mode": "content",
        "style": "balanced",
        "scene_policy": "auto",
        "language": "zh-CN",
    }


def _events(response) -> list[dict[str, object]]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_optimize_streams_core_events_and_settles_quota(tmp_path) -> None:
    client_context = _client(tmp_path)
    client, _ = next(client_context)
    try:
        _, headers = _identity(client)
        text = "请优化这段文字"

        response = client.post("/v1/optimize", headers=headers, json=_payload("request-001", text))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _events(response)
        assert [event["event"]["type"] for event in events][-2:] == ["done", "metric"]
        assert "".join(
            event["event"]["data"]["text"]
            for event in events
            if event["event"]["type"] == "chunk"
        ) == "优化结果"
        quota = client.get("/v1/quota", headers=headers).json()
        assert quota["requests_used"] == 1
        assert quota["input_chars_used"] == len(text)
        assert quota["output_chars_used"] == len("优化结果")
    finally:
        client_context.close()


def test_optimize_records_anonymous_cost_analytics_without_request_text(tmp_path) -> None:
    client_context = _client(tmp_path)
    client, _ = next(client_context)
    try:
        _, headers = _identity(client)
        response = client.post(
            "/v1/optimize",
            headers=headers,
            json=_payload("request-cost-1", "请优化这段文字"),
        )

        assert response.status_code == 200
        analytics = client.get(
            "/v1/admin/analytics/usage?days=7",
            headers={"Authorization": f"Bearer {'a' * 32}"},
        )

        assert analytics.status_code == 200
        body = analytics.json()
        assert body["pricing_configured"] is True
        assert body["requests"] == 1
        assert body["completed_requests"] == 1
        assert body["input_chars"] == len("请优化这段文字")
        assert body["output_chars"] == len("优化结果")
        assert body["estimated_cost_microusd"] == 8
        assert "请优化这段文字" not in analytics.text
        assert "优化结果" not in analytics.text
    finally:
        client_context.close()


def test_quota_exhaustion_stops_before_a_second_stream(tmp_path) -> None:
    client_context = _client(tmp_path, request_limit=1)
    client, _ = next(client_context)
    try:
        _, headers = _identity(client)
        assert client.post("/v1/optimize", headers=headers, json=_payload("request-101")).status_code == 200
        blocked = client.post("/v1/optimize", headers=headers, json=_payload("request-102"))
        assert blocked.status_code == 429
        assert blocked.json() == {"error": {"code": "quota_exhausted"}}
    finally:
        client_context.close()


def test_ip_rate_limit_applies_across_new_installation_tokens_without_storing_raw_ip(
    tmp_path,
) -> None:
    client_context = _client(tmp_path, request_limit=5, ip_limit=1)
    client, _ = next(client_context)
    try:
        _, first_headers = _identity(client)
        _, second_headers = _identity(client)
        assert client.post(
            "/v1/optimize", headers=first_headers, json=_payload("request-151")
        ).status_code == 200
        blocked = client.post(
            "/v1/optimize", headers=second_headers, json=_payload("request-152")
        )
        assert blocked.status_code == 429
        assert blocked.json() == {"error": {"code": "ip_rate_limited"}}
        with client.app.state.database.sessions() as session:
            usage = session.query(HourlyIpUsage).one()
            assert usage.ip_hash != "testclient"
            assert len(usage.ip_hash) == 64
    finally:
        client_context.close()


def test_cancel_is_scoped_to_the_installation_identity(tmp_path) -> None:
    client_context = _client(tmp_path)
    client, optimizer = next(client_context)
    try:
        first_id, first_headers = _identity(client)
        _, second_headers = _identity(client)
        optimizer.claim("request-201", first_id)

        denied = client.post(
            "/v1/optimize/cancel", headers=second_headers, json={"request_id": "request-201"}
        )
        allowed = client.post(
            "/v1/optimize/cancel", headers=first_headers, json={"request_id": "request-201"}
        )

        assert denied.json() == {"cancelled": False}
        assert allowed.json() == {"cancelled": True}
        optimizer.release("request-201")
    finally:
        client_context.close()


def test_per_installation_concurrency_is_bounded(tmp_path) -> None:
    client_context = _client(tmp_path)
    _, optimizer = next(client_context)
    try:
        optimizer.claim("request-211", "installation-1")
        optimizer.claim("request-212", "installation-1")
        with pytest.raises(CloudOptimizerError) as caught:
            optimizer.claim("request-213", "installation-1")
        assert caught.value.code == "installation_concurrency_reached"
    finally:
        optimizer.release("request-211")
        optimizer.release("request-212")
        client_context.close()


def test_unconfigured_provider_fails_without_consuming_quota(client: TestClient) -> None:
    _, headers = _identity(client)
    response = client.post("/v1/optimize", headers=headers, json=_payload("request-301"))

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "cloud_provider_unconfigured"}}
    assert client.get("/v1/quota", headers=headers).json()["requests_used"] == 0


def test_improvement_samples_require_opt_in_and_are_deleted_with_cloud_data(tmp_path) -> None:
    client_context = _client(tmp_path)
    client, _ = next(client_context)
    try:
        _, headers = _identity(client)
        client.post("/v1/optimize", headers=headers, json=_payload("request-401"))
        with client.app.state.database.sessions() as session:
            assert session.query(ImprovementSample).count() == 0

        consent = client.put(
            "/v1/privacy/consent",
            headers=headers,
            json={
                "usage_metrics": False,
                "improvement_data": True,
                "feedback_attachments": False,
                "policy_version": "2026-07-14",
            },
        )
        assert consent.status_code == 200
        client.post("/v1/optimize", headers=headers, json=_payload("request-402"))
        with client.app.state.database.sessions() as session:
            sample = session.query(ImprovementSample).one()
            assert sample.prompt_text == "请优化这段文字"
            assert sample.result_text == "优化结果"
            assert sample.policy_version == "2026-07-14"

        assert client.delete("/v1/privacy/data", headers=headers).status_code == 200
        with client.app.state.database.sessions() as session:
            assert session.query(ImprovementSample).count() == 0
    finally:
        client_context.close()
