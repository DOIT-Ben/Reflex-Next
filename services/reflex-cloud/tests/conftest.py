from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from reflex_cloud.app import create_app
from reflex_cloud.config import CloudSettings


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    settings = CloudSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
        upload_directory=tmp_path / "uploads",
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
        feedback_limit_per_hour=3,
    )
    with TestClient(create_app(settings)) as current:
        yield current


@pytest.fixture
def installation(client: TestClient) -> dict[str, str]:
    response = client.post("/v1/installations")
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def installation_headers(installation: dict[str, str]) -> dict[str, str]:
    return {"X-Reflex-Installation-Token": installation["token"]}


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {'a' * 32}"}


def feedback_payload(**overrides):
    payload = {
        "sentiment": "negative",
        "category": "quality",
        "message": "结果没有保留关键约束",
        "expected_output": "保留关键约束并缩短表达",
        "contact": "",
        "context": {
            "app_version": "0.7.0-alpha.1",
            "os_version": "Windows 11",
            "provider": "minimax",
            "model": "MiniMax-M2.7-highspeed",
            "mode": "content",
            "style": "balanced",
            "scene": "general",
            "request_id": "request-1",
            "diagnostic_id": "diag-1",
            "error_code": "",
            "elapsed_ms": 1234,
        },
        "include_prompt": False,
        "include_result": False,
        "include_screenshot": False,
        "prompt_text": None,
        "result_text": None,
        "screenshot": None,
        "consent_version": "2026-07-14",
    }
    payload.update(overrides)
    return payload
