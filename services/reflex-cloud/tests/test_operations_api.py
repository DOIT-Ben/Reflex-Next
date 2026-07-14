from __future__ import annotations

from fastapi.testclient import TestClient

from test_optimize_api import _client


def test_live_health_does_not_require_provider(
    client: TestClient,
) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "reflex-cloud"}


def test_ready_health_requires_database_and_provider(tmp_path) -> None:
    client_context = _client(tmp_path)
    client, _ = next(client_context)
    try:
        response = client.get("/health/ready")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "checks": {
                "database": "ok",
                "provider": "configured",
                "budget": "disabled",
            },
        }
    finally:
        client_context.close()


def test_admin_static_assets_use_browser_safe_content_types(client: TestClient) -> None:
    script = client.get("/admin-static/admin.js")
    stylesheet = client.get("/admin-static/admin.css")
    favicon = client.get("/admin-static/favicon.ico")

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert favicon.status_code == 200
