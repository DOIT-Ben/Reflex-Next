from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from conftest import feedback_payload


def test_installation_starts_with_all_optional_collection_disabled(
    client: TestClient, installation_headers: dict[str, str]
):
    response = client.get("/v1/privacy/consent", headers=installation_headers)

    assert response.status_code == 200
    assert response.json() == {
        "usage_metrics": False,
        "improvement_data": False,
        "feedback_attachments": False,
        "policy_version": "2026-07-14",
        "updated_at": response.json()["updated_at"],
    }
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_consent_updates_are_versioned_without_implicit_opt_in(
    client: TestClient, installation_headers: dict[str, str]
):
    response = client.put(
        "/v1/privacy/consent",
        headers=installation_headers,
        json={
            "usage_metrics": True,
            "improvement_data": False,
            "feedback_attachments": True,
            "policy_version": "2026-07-14",
        },
    )

    assert response.status_code == 200
    assert response.json()["usage_metrics"] is True
    assert response.json()["improvement_data"] is False
    assert response.json()["feedback_attachments"] is True


def test_feedback_requires_installation_identity(client: TestClient):
    response = client.post("/v1/feedback", json=feedback_payload())

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "request_invalid"}}


def test_feedback_is_persisted_and_admin_list_hides_sensitive_detail(
    client: TestClient,
    installation_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    create = client.post(
        "/v1/feedback", headers=installation_headers, json=feedback_payload()
    )
    feedback_id = create.json()["id"]

    listing = client.get("/v1/admin/feedback", headers=admin_headers)
    detail = client.get(f"/v1/admin/feedback/{feedback_id}", headers=admin_headers)

    assert create.status_code == 201
    assert listing.status_code == 200
    assert listing.headers["cache-control"] == "no-store"
    assert listing.json()["total"] == 1
    assert "message" not in listing.json()["items"][0]
    assert "prompt_text" not in listing.json()["items"][0]
    assert detail.json()["message"] == "结果没有保留关键约束"
    assert detail.json()["context"]["request_id"] == "request-1"


def test_prompt_result_and_screenshot_require_matching_per_submission_consent(
    client: TestClient, installation_headers: dict[str, str]
):
    for changes in (
        {"prompt_text": "private prompt"},
        {"include_prompt": True},
        {"result_text": "private result"},
        {"include_screenshot": True},
    ):
        response = client.post(
            "/v1/feedback",
            headers=installation_headers,
            json=feedback_payload(**changes),
        )
        assert response.status_code == 422
        assert response.json() == {"error": {"code": "request_invalid"}}


def test_authorized_attachments_are_redacted_and_validated(
    client: TestClient,
    installation_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    screenshot = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode("ascii")
    create = client.post(
        "/v1/feedback",
        headers=installation_headers,
        json=feedback_payload(
            include_prompt=True,
            prompt_text="api_key=private-provider-secret-1234567890\n保留这句",
            include_result=True,
            result_text="结果",
            include_screenshot=True,
            screenshot={"media_type": "image/png", "data_base64": screenshot},
        ),
    )
    feedback_id = create.json()["id"]
    detail = client.get(f"/v1/admin/feedback/{feedback_id}", headers=admin_headers)
    image = client.get(
        f"/v1/admin/feedback/{feedback_id}/screenshot", headers=admin_headers
    )

    assert create.status_code == 201
    assert "private-provider-secret" not in detail.text
    assert "<redacted>" in detail.json()["prompt_text"]
    assert image.status_code == 200
    assert image.content.startswith(b"\x89PNG")

    invalid = client.post(
        "/v1/feedback",
        headers=installation_headers,
        json=feedback_payload(
            include_screenshot=True,
            screenshot={
                "media_type": "image/png",
                "data_base64": base64.b64encode(b"not-a-png").decode("ascii"),
            },
        ),
    )
    assert invalid.status_code == 422


def test_feedback_rate_limit_is_per_installation(
    client: TestClient, installation_headers: dict[str, str]
):
    for _ in range(3):
        assert (
            client.post(
                "/v1/feedback", headers=installation_headers, json=feedback_payload()
            ).status_code
            == 201
        )

    blocked = client.post(
        "/v1/feedback", headers=installation_headers, json=feedback_payload()
    )

    assert blocked.status_code == 429
    assert blocked.json() == {"error": {"code": "feedback_rate_limited"}}


def test_admin_auth_and_status_transition(
    client: TestClient,
    installation_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    created = client.post(
        "/v1/feedback", headers=installation_headers, json=feedback_payload()
    ).json()

    assert client.get("/v1/admin/feedback").status_code == 401
    updated = client.patch(
        f"/v1/admin/feedback/{created['id']}",
        headers=admin_headers,
        json={"status": "triaged", "category": "bug"},
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == "triaged"
    assert updated.json()["category"] == "bug"


def test_deleting_cloud_data_removes_identity_feedback_and_attachment(
    client: TestClient,
    installation_headers: dict[str, str],
    admin_headers: dict[str, str],
):
    screenshot = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode("ascii")
    feedback_id = client.post(
        "/v1/feedback",
        headers=installation_headers,
        json=feedback_payload(
            include_screenshot=True,
            screenshot={"media_type": "image/png", "data_base64": screenshot},
        ),
    ).json()["id"]

    deleted = client.delete("/v1/privacy/data", headers=installation_headers)

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get("/v1/privacy/consent", headers=installation_headers).status_code == 401
    assert (
        client.get(f"/v1/admin/feedback/{feedback_id}", headers=admin_headers).status_code
        == 404
    )
