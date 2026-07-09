import json
import os
import subprocess
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def run_sidecar(payload):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "reflex_core.sidecar",
            "--request-id",
            "req-sidecar",
            "--request-json",
            json.dumps(payload, ensure_ascii=False),
        ],
        cwd=PACKAGE_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )


def test_sidecar_writes_ndjson_event_envelopes():
    result = run_sidecar({"text": "请写一封商务邮件确认会议时间。", "style": "concise"})

    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    events = [envelope["event"] for envelope in envelopes]

    assert {envelope["request_id"] for envelope in envelopes} == {"req-sidecar"}
    assert [event["type"] for event in events] == ["status", "scene", "request", "chunk", "done", "metric"]
    assert events[1]["data"]["scene"] == "email"
    assert events[4]["data"]["text"]
    assert result.stderr == ""


def test_sidecar_bad_json_returns_redacted_error_envelope():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT / "src")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "reflex_core.sidecar",
            "--request-json",
            "{bad json sk-test-1234567890abcdef",
        ],
        cwd=PACKAGE_ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    envelopes = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    event = envelopes[0]["event"]
    assert result.returncode == 1
    assert event["type"] == "error"
    assert "sk-test-1234567890abcdef" not in event["data"]["message"]
