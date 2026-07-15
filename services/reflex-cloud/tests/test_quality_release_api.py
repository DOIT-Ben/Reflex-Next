from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from pydantic import SecretStr

from conftest import feedback_payload
from reflex_core import OptimizeRequest, OptimizeUseCase, SceneDetectionResult
from reflex_core.testing import FakeProvider, FakeSceneDetector
from reflex_cloud.app import create_app
from reflex_cloud.config import CloudSettings
from reflex_cloud.models import QualityExposure
from reflex_cloud.optimizer import CloudOptimizer, _QualityReleaseTemplateResolver


ADMIN_HEADERS = {"Authorization": f"Bearer {'a' * 32}"}


def _fixed_feedback(
    client: TestClient,
    installation_headers: dict[str, str],
    *,
    request_id: str,
) -> str:
    payload = feedback_payload()
    payload["context"] = {**payload["context"], "request_id": request_id}
    created = client.post(
        "/v1/feedback", headers=installation_headers, json=payload
    )
    assert created.status_code == 201
    feedback_id = created.json()["id"]
    fixed = client.patch(
        f"/v1/admin/feedback/{feedback_id}",
        headers=ADMIN_HEADERS,
        json={"status": "fixed"},
    )
    assert fixed.status_code == 200
    return feedback_id


def _release_payload(
    source_feedback_ids: list[str],
    *,
    release_version: str = "1.0.1",
) -> dict[str, object]:
    return {
        "release_version": release_version,
        "template_pack_version": "1.0.0",
        "title": "约束保留改进",
        "summary": "提高数字、日期和明确限制的保留率。",
        "global_guidance": "保留用户给出的明确约束，不删除数字、日期和专有名词。",
        "scene_guidance": {"general": "优先检查原文中的数字和时间范围。"},
        "source_feedback_ids": source_feedback_ids,
    }


def _create_draft(
    client: TestClient,
    source_feedback_ids: list[str],
    *,
    release_version: str = "1.0.1",
):
    return client.post(
        "/v1/admin/quality-releases",
        headers=ADMIN_HEADERS,
        json=_release_payload(
            source_feedback_ids,
            release_version=release_version,
        ),
    )


def test_quality_release_draft_is_admin_only_and_not_public(
    client: TestClient,
    installation_headers: dict[str, str],
) -> None:
    feedback_id = _fixed_feedback(
        client, installation_headers, request_id="quality-draft-1"
    )

    unauthorized = client.post(
        "/v1/admin/quality-releases", json=_release_payload([feedback_id])
    )
    created = _create_draft(client, [feedback_id])
    public = client.get("/v1/quality-release", headers=installation_headers)
    listing = client.get("/v1/admin/quality-releases", headers=ADMIN_HEADERS)
    detail = client.get(
        f"/v1/admin/quality-releases/{created.json()['id']}",
        headers=ADMIN_HEADERS,
    )

    assert unauthorized.status_code == 401
    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["source_feedback_ids"] == [feedback_id]
    assert public.status_code == 200
    assert public.json() is None
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert "global_guidance" not in listing.json()["items"][0]
    assert detail.json()["scene_guidance"] == {
        "general": "优先检查原文中的数字和时间范围。"
    }


def test_publishing_requires_fixed_sources_and_exposes_only_safe_metadata(
    client: TestClient,
    installation_headers: dict[str, str],
) -> None:
    created_feedback = client.post(
        "/v1/feedback",
        headers=installation_headers,
        json=feedback_payload(),
    )
    feedback_id = created_feedback.json()["id"]
    draft = _create_draft(client, [feedback_id])
    release_id = draft.json()["id"]

    not_ready = client.post(
        f"/v1/admin/quality-releases/{release_id}/publish",
        headers=ADMIN_HEADERS,
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["error"]["code"] == "quality_release_sources_not_ready"

    assert (
        client.patch(
            f"/v1/admin/feedback/{feedback_id}",
            headers=ADMIN_HEADERS,
            json={"status": "fixed"},
        ).status_code
        == 200
    )
    published = client.post(
        f"/v1/admin/quality-releases/{release_id}/publish",
        headers=ADMIN_HEADERS,
    )
    public = client.get("/v1/quality-release", headers=installation_headers)
    feedback = client.get(
        f"/v1/admin/feedback/{feedback_id}", headers=ADMIN_HEADERS
    )

    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["published_at"] is not None
    assert public.status_code == 200
    assert public.json()["release_version"] == "1.0.1"
    assert public.json()["template_pack_version"] == "1.0.0"
    assert public.json()["source_feedback_count"] == 1
    assert "global_guidance" not in public.json()
    assert "source_feedback_ids" not in public.json()
    assert feedback.json()["status"] == "released"

    duplicate = _create_draft(client, [feedback_id])
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "quality_release_version_conflict"


def test_quality_release_rejects_sensitive_guidance(
    client: TestClient,
    installation_headers: dict[str, str],
) -> None:
    feedback_id = _fixed_feedback(
        client, installation_headers, request_id="quality-secret-1"
    )
    payload = _release_payload([feedback_id])
    secret = "sk-" + "privatevalue1234567890"
    payload["global_guidance"] = f"api_key={secret}"

    response = client.post(
        "/v1/admin/quality-releases", headers=ADMIN_HEADERS, json=payload
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "quality_release_sensitive_content"
    assert secret not in response.text


def test_new_release_supersedes_current_and_rollback_restores_previous(
    client: TestClient,
    installation_headers: dict[str, str],
) -> None:
    first_feedback = _fixed_feedback(
        client, installation_headers, request_id="quality-release-1"
    )
    first = _create_draft(client, [first_feedback], release_version="1.0.1").json()
    assert (
        client.post(
            f"/v1/admin/quality-releases/{first['id']}/publish",
            headers=ADMIN_HEADERS,
        ).status_code
        == 200
    )

    second_feedback = _fixed_feedback(
        client, installation_headers, request_id="quality-release-2"
    )
    second = _create_draft(client, [second_feedback], release_version="1.0.2").json()
    assert (
        client.post(
            f"/v1/admin/quality-releases/{second['id']}/publish",
            headers=ADMIN_HEADERS,
        ).status_code
        == 200
    )
    assert (
        client.get("/v1/quality-release", headers=installation_headers).json()[
            "release_version"
        ]
        == "1.0.2"
    )

    rolled_back = client.post(
        f"/v1/admin/quality-releases/{second['id']}/rollback",
        headers=ADMIN_HEADERS,
    )
    restored = client.get("/v1/quality-release", headers=installation_headers)
    first_detail = client.get(
        f"/v1/admin/quality-releases/{first['id']}", headers=ADMIN_HEADERS
    )
    second_detail = client.get(
        f"/v1/admin/quality-releases/{second['id']}", headers=ADMIN_HEADERS
    )

    assert rolled_back.status_code == 200
    assert rolled_back.json()["release_version"] == "1.0.1"
    assert restored.json()["release_version"] == "1.0.1"
    assert first_detail.json()["status"] == "published"
    assert second_detail.json()["status"] == "rolled_back"


class _RecordingResolver:
    def __init__(self) -> None:
        self.metadata: list[dict[str, object]] = []

    def render(
        self, request: OptimizeRequest, scene: SceneDetectionResult
    ) -> dict[str, object]:
        self.metadata.append(dict(request.metadata))
        return {
            "messages": [{"role": "system", "content": "base"}],
            "text": request.text,
            "scene": scene.scene,
        }


def _optimized_client(
    tmp_path,
) -> Iterator[tuple[TestClient, _RecordingResolver]]:
    settings = CloudSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'quality-cloud.db'}",
        upload_directory=tmp_path / "quality-uploads",
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
        provider_model="MiniMax-M2.7-highspeed",
    )
    resolver = _RecordingResolver()
    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(),
        template_resolver=resolver,
        provider=FakeProvider(("优化结果",)),
    )
    optimizer = CloudOptimizer(settings, use_case)
    with TestClient(create_app(settings, optimizer)) as client:
        yield client, resolver


def _identity(client: TestClient) -> tuple[str, dict[str, str]]:
    installation = client.post("/v1/installations").json()
    return installation["installation_id"], {
        "X-Reflex-Installation-Token": installation["token"]
    }


def _optimize_payload(request_id: str) -> dict[str, object]:
    return {
        "request_id": request_id,
        "text": "请优化这段文字",
        "mode": "content",
        "style": "balanced",
        "scene_policy": "auto",
        "language": "zh-CN",
    }


def test_published_guidance_reaches_cloud_requests_and_metrics_require_consent(
    tmp_path,
) -> None:
    context = _optimized_client(tmp_path)
    client, resolver = next(context)
    try:
        _, headers = _identity(client)
        feedback_id = _fixed_feedback(
            client, headers, request_id="quality-source-request"
        )
        draft = _create_draft(client, [feedback_id]).json()
        assert (
            client.post(
                f"/v1/admin/quality-releases/{draft['id']}/publish",
                headers=ADMIN_HEADERS,
            ).status_code
            == 200
        )

        consent = client.get("/v1/privacy/consent", headers=headers).json()
        assert (
            client.put(
                "/v1/privacy/consent",
                headers=headers,
                json={
                    "usage_metrics": True,
                    "improvement_data": False,
                    "feedback_attachments": False,
                    "policy_version": consent["policy_version"],
                },
            ).status_code
            == 200
        )
        optimized = client.post(
            "/v1/optimize",
            headers=headers,
            json=_optimize_payload("quality-request-1"),
        )

        assert optimized.status_code == 200
        assert optimized.headers["x-reflex-quality-release"] == "1.0.1"
        assert resolver.metadata[-1]["quality_release_version"] == "1.0.1"
        assert "明确约束" in str(resolver.metadata[-1]["quality_global_guidance"])
        assert resolver.metadata[-1]["quality_scene_guidance"] == {
            "general": "优先检查原文中的数字和时间范围。"
        }
        with client.app.state.database.sessions() as session:
            exposure = session.query(QualityExposure).one()
            assert exposure.release_version == "1.0.1"
            assert exposure.request_id == "quality-request-1"

        payload = feedback_payload()
        payload["context"] = {
            **payload["context"],
            "request_id": "quality-request-1",
        }
        assert (
            client.post("/v1/feedback", headers=headers, json=payload).status_code
            == 201
        )

        _, opted_out_headers = _identity(client)
        assert (
            client.post(
                "/v1/optimize",
                headers=opted_out_headers,
                json=_optimize_payload("quality-request-2"),
            ).status_code
            == 200
        )
        opted_out_payload = feedback_payload()
        opted_out_payload["context"] = {
            **opted_out_payload["context"],
            "request_id": "quality-request-2",
        }
        assert (
            client.post(
                "/v1/feedback",
                headers=opted_out_headers,
                json=opted_out_payload,
            ).status_code
            == 201
        )

        analytics = client.get(
            "/v1/admin/analytics/feedback", headers=ADMIN_HEADERS
        ).json()
        assert analytics["by_quality_release"]["1.0.1"]["total"] == 1
        with client.app.state.database.sessions() as session:
            assert session.query(QualityExposure).count() == 1
    finally:
        context.close()


def test_baseline_quality_exposure_is_attributed_and_deleted_with_installation_data(
    tmp_path,
) -> None:
    context = _optimized_client(tmp_path)
    client, _ = next(context)
    try:
        installation_id, headers = _identity(client)
        consent = client.get("/v1/privacy/consent", headers=headers).json()
        enabled = client.put(
            "/v1/privacy/consent",
            headers=headers,
            json={
                "usage_metrics": True,
                "improvement_data": False,
                "feedback_attachments": False,
                "policy_version": consent["policy_version"],
            },
        )
        assert enabled.status_code == 200

        optimized = client.post(
            "/v1/optimize",
            headers=headers,
            json=_optimize_payload("baseline-request-1"),
        )
        assert optimized.status_code == 200
        assert "x-reflex-quality-release" not in optimized.headers

        with client.app.state.database.sessions() as session:
            exposure = session.query(QualityExposure).one()
            assert exposure.installation_id == installation_id
            assert exposure.release_version == "baseline"

        feedback = feedback_payload()
        feedback["context"] = {
            **feedback["context"],
            "request_id": "baseline-request-1",
        }
        assert client.post("/v1/feedback", headers=headers, json=feedback).status_code == 201
        analytics = client.get(
            "/v1/admin/analytics/feedback", headers=ADMIN_HEADERS
        ).json()
        assert analytics["by_quality_release"]["baseline"]["total"] == 1

        assert client.delete("/v1/privacy/data", headers=headers).status_code == 200
        with client.app.state.database.sessions() as session:
            assert session.query(QualityExposure).count() == 0
    finally:
        context.close()


def test_quality_exposure_is_idempotent_for_same_installation_request(tmp_path) -> None:
    context = _optimized_client(tmp_path)
    client, _ = next(context)
    try:
        installation_id, headers = _identity(client)
        consent = client.get("/v1/privacy/consent", headers=headers).json()
        assert (
            client.put(
                "/v1/privacy/consent",
                headers=headers,
                json={
                    "usage_metrics": True,
                    "improvement_data": False,
                    "feedback_attachments": False,
                    "policy_version": consent["policy_version"],
                },
            ).status_code
            == 200
        )

        service = client.app.state.cloud_service
        with client.app.state.database.sessions() as session:
            assert service.record_quality_exposure(
                session, installation_id, "same-request-id", None
            )
            assert service.record_quality_exposure(
                session, installation_id, "same-request-id", None
            )
            assert session.query(QualityExposure).count() == 1
    finally:
        context.close()


def test_rollback_without_previous_release_removes_active_guidance(
    client: TestClient,
    installation_headers: dict[str, str],
) -> None:
    feedback_id = _fixed_feedback(
        client, installation_headers, request_id="quality-rollback-only"
    )
    draft = _create_draft(client, [feedback_id]).json()
    assert (
        client.post(
            f"/v1/admin/quality-releases/{draft['id']}/publish",
            headers=ADMIN_HEADERS,
        ).status_code
        == 200
    )

    rolled_back = client.post(
        f"/v1/admin/quality-releases/{draft['id']}/rollback",
        headers=ADMIN_HEADERS,
    )
    assert rolled_back.status_code == 200
    assert rolled_back.json() is None
    assert client.get("/v1/quality-release", headers=installation_headers).json() is None


def test_quality_release_template_resolver_appends_bounded_curated_guidance() -> None:
    base = _RecordingResolver()
    resolver = _QualityReleaseTemplateResolver(base)
    request = OptimizeRequest(
        "原文",
        metadata={
            "quality_release_version": "1.0.1",
            "quality_global_guidance": "保留数字。",
            "quality_scene_guidance": {"general": "保留日期。"},
        },
    )

    rendered = resolver.render(
        request, SceneDetectionResult("general", 1.0, "manual")
    )

    system = rendered["messages"][0]["content"]
    assert "base" in system
    assert "保留数字" in system
    assert "保留日期" in system
    assert "1.0.1" not in system
