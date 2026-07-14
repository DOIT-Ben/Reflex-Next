from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import feedback_payload


def test_feedback_analytics_compares_categories_and_versions(
    client: TestClient,
    installation_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    first = feedback_payload()
    second = feedback_payload(
        sentiment="positive",
        category="feature",
        context={**first["context"], "app_version": "0.7.0-alpha.2", "elapsed_ms": 2000},
    )
    assert client.post("/v1/feedback", headers=installation_headers, json=first).status_code == 201
    assert client.post("/v1/feedback", headers=installation_headers, json=second).status_code == 201

    response = client.get("/v1/admin/analytics/feedback", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["negative"] == 1
    assert body["negative_rate"] == 0.5
    assert body["by_category"]["quality"]["negative"] == 1
    assert body["by_category"]["feature"]["negative"] == 0
    assert body["by_version"]["0.7.0-alpha.2"]["total"] == 1


def test_usage_analytics_reports_disabled_budget_explicitly(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    response = client.get("/v1/admin/analytics/usage?days=7", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["daily_request_limit"] is None
    assert body["daily_cost_budget_microusd"] is None
    assert body["daily_requests_used"] == 0
    assert body["daily_cost_committed_microusd"] == 0
    assert body["daily_request_usage_ratio"] is None
    assert body["daily_cost_usage_ratio"] is None
    assert body["budget_exceeded"] is False
