from __future__ import annotations

import base64
from collections.abc import Iterator
from datetime import timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr

from conftest import feedback_payload
from reflex_cloud.app import create_app
from reflex_cloud.config import CloudSettings
from reflex_cloud.models import ClientAbuseUsage, HourlyIpUsage, utc_now


def _client(
    tmp_path, *, peer: tuple[str, int] = ("testclient", 50000), **overrides
) -> Iterator[TestClient]:
    values = {
        "environment": "test",
        "database_url": f"sqlite:///{tmp_path / 'cloud.db'}",
        "upload_directory": tmp_path / "uploads",
        "admin_token": SecretStr("a" * 32),
        "token_pepper": SecretStr("p" * 32),
        "installation_limit_per_ip_per_hour": 20,
        "feedback_limit_per_ip_per_hour": 20,
        "feedback_attachment_bytes_per_ip_per_day": 10 * 1024 * 1024,
        "global_daily_feedback_limit": 10_000,
        "global_daily_feedback_attachment_bytes": 1024 * 1024 * 1024,
    }
    values.update(overrides)
    settings = CloudSettings(**values)
    return TestClient(create_app(settings), client=peer)


def _identity(client: TestClient, **request_kwargs) -> dict[str, str]:
    response = client.post("/v1/installations", **request_kwargs)
    assert response.status_code == 201
    return {"X-Reflex-Installation-Token": response.json()["token"]}


def _proxied_identity(client: TestClient, address: str) -> dict[str, str]:
    forwarded = {"X-Forwarded-For": address}
    return {**_identity(client, headers=forwarded), **forwarded}


def test_installation_creation_is_limited_per_client_ip(tmp_path) -> None:
    with _client(tmp_path, installation_limit_per_ip_per_hour=2) as client:
        assert client.post("/v1/installations").status_code == 201
        assert client.post("/v1/installations").status_code == 201

        blocked = client.post("/v1/installations")

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "installation_rate_limited"


def test_feedback_ip_limit_applies_across_installation_tokens(tmp_path) -> None:
    with _client(tmp_path, feedback_limit_per_ip_per_hour=1) as client:
        first = _identity(client)
        second = _identity(client)
        assert client.post(
            "/v1/feedback", headers=first, json=feedback_payload()
        ).status_code == 201

        blocked = client.post(
            "/v1/feedback", headers=second, json=feedback_payload()
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "feedback_rate_limited"


def test_attachment_byte_limit_applies_across_installation_tokens(tmp_path) -> None:
    raw = b"\x89PNG\r\n\x1a\n" + (b"x" * 592)
    screenshot = {
        "media_type": "image/png",
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }
    with _client(
        tmp_path,
        max_screenshot_bytes=1024,
        feedback_attachment_bytes_per_ip_per_day=1024,
    ) as client:
        first = _identity(client)
        second = _identity(client)
        assert client.post(
            "/v1/feedback",
            headers=first,
            json=feedback_payload(include_screenshot=True, screenshot=screenshot),
        ).status_code == 201

        blocked = client.post(
            "/v1/feedback",
            headers=second,
            json=feedback_payload(include_screenshot=True, screenshot=screenshot),
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "feedback_attachment_rate_limited"


def test_untrusted_peer_cannot_spoof_forwarded_client_ip(tmp_path) -> None:
    with _client(
        tmp_path,
        peer=("203.0.113.10", 50000),
        installation_limit_per_ip_per_hour=1,
        trusted_proxy_cidrs="10.0.0.0/8",
    ) as client:
        assert client.post(
            "/v1/installations", headers={"X-Forwarded-For": "198.51.100.1"}
        ).status_code == 201
        blocked = client.post(
            "/v1/installations", headers={"X-Forwarded-For": "198.51.100.2"}
        )

    assert blocked.status_code == 429


def test_trusted_proxy_uses_forwarded_client_ip(tmp_path) -> None:
    with _client(
        tmp_path,
        peer=("10.0.0.2", 50000),
        installation_limit_per_ip_per_hour=1,
        trusted_proxy_cidrs="10.0.0.0/8",
    ) as client:
        first = client.post(
            "/v1/installations", headers={"X-Forwarded-For": "198.51.100.1"}
        )
        second = client.post(
            "/v1/installations", headers={"X-Forwarded-For": "198.51.100.2"}
        )

    assert first.status_code == 201
    assert second.status_code == 201


def test_unknown_client_ip_uses_a_stable_rate_limit_bucket(tmp_path) -> None:
    with _client(tmp_path, installation_limit_per_ip_per_hour=1) as client:
        assert client.post("/v1/installations").status_code == 201
        blocked = client.post("/v1/installations")

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "installation_rate_limited"


def test_global_feedback_limit_applies_across_client_ips(tmp_path) -> None:
    with _client(
        tmp_path,
        peer=("10.0.0.2", 50000),
        trusted_proxy_cidrs="10.0.0.0/8",
        global_daily_feedback_limit=1,
    ) as client:
        first = _proxied_identity(client, "198.51.100.1")
        second = _proxied_identity(client, "198.51.100.2")
        assert client.post(
            "/v1/feedback", headers=first, json=feedback_payload()
        ).status_code == 201

        blocked = client.post(
            "/v1/feedback", headers=second, json=feedback_payload()
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "feedback_rate_limited"


def test_ipv6_addresses_share_a_64_bit_feedback_bucket(tmp_path) -> None:
    with _client(
        tmp_path,
        peer=("10.0.0.2", 50000),
        trusted_proxy_cidrs="10.0.0.0/8",
        feedback_limit_per_ip_per_hour=1,
    ) as client:
        first = _proxied_identity(client, "2001:db8:abcd:1::1")
        second = _proxied_identity(client, "2001:db8:abcd:1::2")
        assert client.post(
            "/v1/feedback", headers=first, json=feedback_payload()
        ).status_code == 201

        blocked = client.post(
            "/v1/feedback", headers=second, json=feedback_payload()
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "feedback_rate_limited"


def test_global_attachment_budget_applies_across_client_ips(tmp_path) -> None:
    raw = b"\x89PNG\r\n\x1a\n" + (b"x" * 592)
    screenshot = {
        "media_type": "image/png",
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }
    with _client(
        tmp_path,
        peer=("10.0.0.2", 50000),
        trusted_proxy_cidrs="10.0.0.0/8",
        max_screenshot_bytes=1024,
        global_daily_feedback_attachment_bytes=1024,
    ) as client:
        first = _proxied_identity(client, "198.51.100.1")
        second = _proxied_identity(client, "198.51.100.2")
        assert client.post(
            "/v1/feedback",
            headers=first,
            json=feedback_payload(include_screenshot=True, screenshot=screenshot),
        ).status_code == 201

        blocked = client.post(
            "/v1/feedback",
            headers=second,
            json=feedback_payload(include_screenshot=True, screenshot=screenshot),
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "feedback_attachment_rate_limited"


def test_attachment_submission_fails_closed_below_disk_watermark(tmp_path) -> None:
    raw = b"\x89PNG\r\n\x1a\nfixture"
    screenshot = {
        "media_type": "image/png",
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }
    with _client(
        tmp_path,
        feedback_attachment_min_free_bytes=10 * 1024**4,
    ) as client:
        identity = _identity(client)
        blocked = client.post(
            "/v1/feedback",
            headers=identity,
            json=feedback_payload(include_screenshot=True, screenshot=screenshot),
        )

    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "feedback_storage_unavailable"


def test_retention_cleanup_removes_expired_abuse_buckets(tmp_path) -> None:
    with _client(tmp_path) as client:
        database = client.app.state.database
        service = client.app.state.cloud_service
        old_window = utc_now() - timedelta(days=3)
        current_window = utc_now().replace(minute=0, second=0, microsecond=0)
        with database.sessions() as session:
            session.add_all(
                [
                    ClientAbuseUsage(
                        ip_hash="a" * 64,
                        scope="feedback_hour",
                        window_start=old_window,
                    ),
                    HourlyIpUsage(ip_hash="b" * 64, window_start=old_window),
                    ClientAbuseUsage(
                        ip_hash="c" * 64,
                        scope="feedback_hour",
                        window_start=current_window,
                    ),
                ]
            )
            session.commit()

            removed = service.purge_expired_abuse_usage(session)
            abuse_count = session.query(ClientAbuseUsage).count()
            hourly_count = session.query(HourlyIpUsage).count()

    assert removed == 2
    assert abuse_count == 1
    assert hourly_count == 0
