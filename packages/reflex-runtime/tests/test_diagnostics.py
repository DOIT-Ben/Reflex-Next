from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from reflex_runtime.diagnostics import DiagnosticWriter


def _records(directory: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in sorted(directory.glob("runtime-diagnostics*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            records.append(json.loads(line))
    return records


def test_diagnostics_are_disabled_by_default_without_touching_disk(tmp_path):
    directory = tmp_path / "diagnostics"

    writer = DiagnosticWriter(directory)

    assert writer.enabled is False
    assert writer.emit("runtime_started", status="ready") is False
    assert not directory.exists()


def test_only_literal_true_enables_disk_writes(tmp_path):
    directory = tmp_path / "diagnostics"

    writer = DiagnosticWriter(directory, enabled="true")  # type: ignore[arg-type]

    assert writer.enabled is False
    assert writer.emit("runtime_started") is False
    assert not directory.exists()


def test_event_name_cannot_be_used_as_free_form_body(tmp_path):
    directory = tmp_path / "diagnostics"
    writer = DiagnosticWriter(directory, enabled=True)

    assert writer.emit("complete private request body") is False
    writer.close()

    assert _records(directory) == []


def test_allowed_fields_are_structured_and_sensitive_content_is_removed(tmp_path):
    directory = tmp_path / "diagnostics"
    writer = DiagnosticWriter(directory, enabled=True)

    assert writer.emit(
        "provider_failed",
        level="warning",
        provider_id="minimax",
        code="provider_authentication_failed",
        model="api_key=model-secret",
        url="https://user:password@example.test/v1/chat?token=query-secret&q=private-text#fragment",
        message=(
            "Authorization: Basic header-secret api_key=message-secret "
            "key=generic-secret"
        ),
        body="complete private request body",
        output="complete private response body",
        api_key="field-secret",
        arbitrary_field="must-be-dropped",
    )
    writer.close()

    records = _records(directory)
    assert len(records) == 1
    record = records[0]
    assert set(record) == {
        "timestamp",
        "event",
        "level",
        "provider_id",
        "code",
        "model",
    }
    assert record["model"] == "api_key=[REDACTED]"
    serialized = json.dumps(record, ensure_ascii=False)
    for secret in (
        "password",
        "query-secret",
        "private-text",
        "header-secret",
        "message-secret",
        "model-secret",
        "generic-secret",
        "complete private",
        "field-secret",
        "must-be-dropped",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in serialized


def test_files_rotate_with_count_size_and_total_budgets(tmp_path):
    directory = tmp_path / "diagnostics"
    writer = DiagnosticWriter(
        directory,
        enabled=True,
        max_file_bytes=512,
        max_files=3,
        max_total_bytes=1_200,
    )

    for index in range(80):
        writer.emit(
            "provider_metric",
            request_id=f"request-{index:03d}",
            status="complete",
            duration_ms=index,
        )
    writer.close()

    files = list(directory.glob("runtime-diagnostics*.jsonl"))
    assert 1 < len(files) <= 3
    assert all(path.stat().st_size <= 512 for path in files)
    assert sum(path.stat().st_size for path in files) <= 1_200
    assert _records(directory)


def test_concurrent_writes_produce_complete_json_lines(tmp_path):
    directory = tmp_path / "diagnostics"
    writer = DiagnosticWriter(
        directory,
        enabled=True,
        max_file_bytes=256_000,
        max_total_bytes=256_000,
    )

    def write(index: int) -> bool:
        return writer.emit(
            "request_finished",
            request_id=f"request-{index}",
            duration_ms=index,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(write, range(400)))
    writer.close()

    records = _records(directory)
    assert all(results)
    assert len(records) == 400
    assert {record["request_id"] for record in records} == {
        f"request-{index}" for index in range(400)
    }


def test_storage_failures_do_not_escape_or_create_partial_state(tmp_path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("occupied", encoding="utf-8")

    writer = DiagnosticWriter(blocker / "diagnostics", enabled=True)

    assert writer.enabled is True
    assert writer.available is False
    assert writer.emit("runtime_started", status="ready") is False
    writer.close()


def test_corrupt_active_file_is_discarded_without_blocking_new_records(tmp_path):
    directory = tmp_path / "diagnostics"
    directory.mkdir()
    active = directory / "runtime-diagnostics.jsonl"
    active.write_bytes(b"not-json\xff\n")

    writer = DiagnosticWriter(directory, enabled=True)

    assert writer.available is True
    assert writer.emit("runtime_recovered", status="ready") is True
    writer.close()
    assert json.loads(active.read_text(encoding="utf-8").strip())["event"] == "runtime_recovered"
    assert not (directory / "runtime-diagnostics.1.jsonl").exists()


def test_close_is_idempotent_and_stops_future_writes(tmp_path):
    writer = DiagnosticWriter(tmp_path / "diagnostics", enabled=True)
    assert writer.emit("runtime_started") is True

    writer.close()
    writer.close()

    assert writer.closed is True
    assert writer.emit("must_not_be_written") is False
    assert all(record["event"] != "must_not_be_written" for record in _records(tmp_path / "diagnostics"))


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("max_file_bytes", 0),
        ("max_file_bytes", 10_000_001),
        ("max_files", 0),
        ("max_files", 11),
        ("max_total_bytes", 0),
        ("max_total_bytes", 50_000_001),
    ],
)
def test_configuration_has_hard_resource_limits(tmp_path, option, value):
    kwargs = {option: value}
    with pytest.raises(ValueError):
        DiagnosticWriter(tmp_path / "diagnostics", enabled=True, **kwargs)


def test_total_budget_must_cover_one_file(tmp_path):
    with pytest.raises(ValueError):
        DiagnosticWriter(
            tmp_path / "diagnostics",
            enabled=True,
            max_file_bytes=2_000,
            max_total_bytes=1_000,
        )
