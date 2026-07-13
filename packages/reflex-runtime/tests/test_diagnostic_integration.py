from __future__ import annotations

import json
import time
from io import StringIO

from reflex_runtime.context import RuntimeContext
from reflex_runtime.diagnostics import DiagnosticWriter
from reflex_runtime.protocol import parse_command


def _records(directory):
    records = []
    for path in sorted(directory.glob("runtime-diagnostics*.jsonl")):
        records.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return records


def test_enabled_runtime_errors_share_one_diagnostic_id_with_the_safe_record(tmp_path):
    protocol = StringIO()
    writer = DiagnosticWriter(tmp_path / "diagnostics", enabled=True)
    runtime = RuntimeContext(
        stdout=protocol,
        stderr=StringIO(),
        development=True,
        diagnostics=writer,
    )

    runtime.emit_error(
        "request-1",
        "provider_unavailable",
        "Provider unavailable.",
        action="retry",
    )
    runtime.close()

    envelope = json.loads(protocol.getvalue().splitlines()[-1])
    diagnostic_id = envelope["event"]["data"]["diagnostic_id"]
    records = _records(tmp_path / "diagnostics")
    failed = next(record for record in records if record["event"] == "request_failed")
    assert diagnostic_id.startswith("diag-")
    assert failed["diagnostic_id"] == diagnostic_id
    assert failed["code"] == "provider_unavailable"


def test_runtime_records_only_bounded_optimize_metadata_and_terminal_metrics(tmp_path):
    protocol = StringIO()
    private_body = "private-runtime-body-must-not-enter-diagnostics"
    private_chunk = "private-runtime-output-must-not-enter-diagnostics"
    writer = DiagnosticWriter(tmp_path / "diagnostics", enabled=True)
    runtime = RuntimeContext(
        stdout=protocol,
        stderr=StringIO(),
        development=True,
        diagnostics=writer,
    )
    command = parse_command(
        {
            "version": 1,
            "request_id": "request-2",
            "type": "optimize",
            "payload": {
                "text": private_body,
                "provider": "mock",
                "model": "mock-stream",
                "metadata": {"chunks": [private_chunk, private_chunk]},
            },
        }
    )

    assert runtime.handle(command) is True
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert runtime.has_active_tasks() is False
    runtime.close()

    records = _records(tmp_path / "diagnostics")
    started = next(record for record in records if record["event"] == "request_started")
    completed = next(record for record in records if record["event"] == "request_completed")
    assert started["provider_id"] == "mock"
    assert started["model"] == "mock-stream"
    assert completed["status"] == "completed"
    assert completed["chunk_count"] == 2
    assert completed["duration_ms"] >= 0
    serialized = json.dumps(records, ensure_ascii=False)
    assert private_body not in serialized
    assert private_chunk not in serialized


def test_provider_setup_failures_keep_safe_provider_metadata_and_matching_id(tmp_path):
    protocol = StringIO()
    writer = DiagnosticWriter(tmp_path / "diagnostics", enabled=True)
    runtime = RuntimeContext(
        stdout=protocol,
        stderr=StringIO(),
        development=True,
        diagnostics=writer,
    )
    command = parse_command(
        {
            "version": 1,
            "request_id": "request-3",
            "type": "optimize",
            "payload": {
                "text": "private-provider-input",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed",
            },
        }
    )

    assert runtime.handle(command) is True
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    runtime.close()

    error_envelope = next(
        json.loads(line)
        for line in protocol.getvalue().splitlines()
        if json.loads(line)["event"]["type"] == "error"
    )
    failed = next(
        record
        for record in _records(tmp_path / "diagnostics")
        if record["event"] == "request_failed"
    )
    assert failed["provider_id"] == "minimax"
    assert failed["model"] == "MiniMax-M2.7-highspeed"
    assert failed["code"] == "provider_unconfigured"
    assert failed["diagnostic_id"] == error_envelope["event"]["data"]["diagnostic_id"]
    assert "private-provider-input" not in json.dumps(failed, ensure_ascii=False)
