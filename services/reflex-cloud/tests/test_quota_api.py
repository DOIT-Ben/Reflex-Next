from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import date

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from reflex_cloud.service import CloudService
from reflex_cloud.models import DailyCostAggregate, Installation
from reflex_cloud.service import CloudServiceError
from reflex_cloud.storage import AttachmentStore


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


def test_output_settlement_rejects_atomic_daily_overage(
    client: TestClient, installation: dict[str, str]
) -> None:
    database = client.app.state.database
    service = client.app.state.cloud_service
    installation_id = installation["installation_id"]

    with database.sessions() as session:
        installation_row = session.scalar(
            select(Installation).where(Installation.id == installation_id)
        )
        assert installation_row is not None
        service.reserve_quota(session, installation_row, input_chars=1)

    with database.sessions() as session:
        with pytest.raises(CloudServiceError) as error:
            service.record_output_usage(
                session, installation_id, output_chars=200_001
            )
        assert error.value.code == "quota_exhausted"

    quota = client.get(
        "/v1/quota",
        headers={"X-Reflex-Installation-Token": installation["token"]},
    ).json()
    assert quota["output_chars_used"] == 0


def test_output_settlement_is_bounded_across_independent_service_instances(
    client: TestClient, installation: dict[str, str]
) -> None:
    database = client.app.state.database
    settings = client.app.state.settings
    with database.sessions() as session:
        installation_row = session.scalar(
            select(Installation).where(Installation.id == installation["installation_id"])
        )
        assert installation_row is not None
        client.app.state.cloud_service.reserve_quota(
            session, installation_row, input_chars=1
        )

    services = [
        CloudService(
            settings,
            AttachmentStore(settings.upload_directory, settings.max_screenshot_bytes),
        )
        for _ in range(2)
    ]
    barrier = Barrier(2)

    def settle(service: CloudService) -> str:
        barrier.wait()
        try:
            with database.sessions() as session:
                service.record_output_usage(
                    session,
                    installation["installation_id"],
                    output_chars=120_000,
                )
            return "ok"
        except CloudServiceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(settle, services))

    assert sorted(results) == ["ok", "quota_exhausted"]
    quota = client.get(
        "/v1/quota",
        headers={"X-Reflex-Installation-Token": installation["token"]},
    ).json()
    assert quota["output_chars_used"] == 120_000


def test_provider_usage_aggregate_is_shared_by_independent_service_instances(
    client: TestClient, installation: dict[str, str]
) -> None:
    database = client.app.state.database
    settings = client.app.state.settings
    services = [
        CloudService(
            settings,
            AttachmentStore(settings.upload_directory, settings.max_screenshot_bytes),
        )
        for _ in range(2)
    ]

    for service in services:
        with database.sessions() as session:
            service.record_provider_usage(
                session,
                input_chars=10,
                output_chars=20,
                completed=True,
            )

    with database.sessions() as session:
        rows = list(
            session.scalars(
                select(DailyCostAggregate).where(
                    DailyCostAggregate.usage_date == date.today()
                )
            )
        )

    assert len(rows) == 1
    assert rows[0].request_count == 2
    assert rows[0].completed_count == 2
    assert rows[0].input_chars == 20
    assert rows[0].output_chars == 40


def test_provider_usage_existing_aggregate_increments_are_atomic(
    client: TestClient, installation: dict[str, str]
) -> None:
    database = client.app.state.database
    settings = client.app.state.settings
    services = [
        CloudService(
            settings,
            AttachmentStore(settings.upload_directory, settings.max_screenshot_bytes),
        )
        for _ in range(2)
    ]

    with database.sessions() as session:
        services[0].record_provider_usage(
            session,
            input_chars=0,
            output_chars=0,
            completed=False,
        )

    barrier = Barrier(2)

    def settle(service: CloudService) -> None:
        barrier.wait()
        with database.sessions() as session:
            service.record_provider_usage(
                session,
                input_chars=10,
                output_chars=20,
                completed=True,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(settle, services))

    with database.sessions() as session:
        row = session.scalar(
            select(DailyCostAggregate).where(
                DailyCostAggregate.usage_date == date.today()
            )
        )

    assert row is not None
    assert row.request_count == 3
    assert row.completed_count == 2
    assert row.input_chars == 20
    assert row.output_chars == 40
