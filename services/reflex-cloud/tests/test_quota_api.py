from __future__ import annotations

from fastapi.testclient import TestClient


def test_quota_starts_empty_with_configured_free_limits(
    client: TestClient, installation_headers: dict[str, str]
) -> None:
    response = client.get("/v1/quota", headers=installation_headers)

    assert response.status_code == 200
    assert response.json() == {
        "usage_date": response.json()["usage_date"],
        "requests_used": 0,
        "requests_limit": 20,
        "input_chars_used": 0,
        "input_chars_limit": 200_000,
        "output_chars_used": 0,
        "output_chars_limit": 200_000,
    }


def test_quota_requires_installation_identity(client: TestClient) -> None:
    assert client.get("/v1/quota").status_code == 422
