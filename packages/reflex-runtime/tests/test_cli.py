import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


class RuntimeProcess:
    def __init__(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(PACKAGE_ROOT / "src"),
                str(REPO_ROOT / "packages" / "reflex-core" / "src"),
            ]
        )
        self.process = subprocess.Popen(
            [sys.executable, "-m", "reflex_runtime.cli"],
            cwd=PACKAGE_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.stdout: queue.Queue[dict] = queue.Queue()
        self.stderr: queue.Queue[str] = queue.Queue()
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def send(self, message: dict | str) -> None:
        assert self.process.stdin is not None
        line = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def read_event(self, timeout: float = 2.0) -> dict:
        return self.stdout.get(timeout=timeout)

    def read_until(self, request_id: str, event_type: str, timeout: float = 3.0) -> list[dict]:
        deadline = time.monotonic() + timeout
        events: list[dict] = []
        while time.monotonic() < deadline:
            try:
                envelope = self.stdout.get(timeout=0.1)
            except queue.Empty:
                continue
            events.append(envelope)
            if envelope.get("request_id") == request_id and envelope.get("event", {}).get("type") == event_type:
                return events
        raise AssertionError(f"did not receive {event_type} for {request_id}: {events}")

    def close(self) -> None:
        if self.process.poll() is None:
            self.send({"version": 1, "request_id": "shutdown", "type": "shutdown", "payload": {}})
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            if line.strip():
                self.stdout.put(json.loads(line))

    def _read_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            if line.strip():
                self.stderr.put(line.strip())


def optimize_command(request_id: str, text: str, **metadata):
    return {
        "version": 1,
        "request_id": request_id,
        "type": "optimize",
        "payload": {
            "text": text,
            "style": "concise",
            "metadata": metadata,
        },
    }


def test_ping_and_shutdown_use_versioned_event_envelopes():
    runtime = RuntimeProcess()
    try:
        runtime.send({"version": 1, "request_id": "ping-1", "type": "ping", "payload": {}})
        ping = runtime.read_event()

        assert ping["version"] == 1
        assert ping["request_id"] == "ping-1"
        assert ping["event"]["type"] == "status"
        assert ping["event"]["data"]["phase"] == "completed"

        runtime.send({"version": 1, "request_id": "stop-1", "type": "shutdown", "payload": {}})
        shutdown = runtime.read_event()
        assert shutdown["request_id"] == "stop-1"
        assert shutdown["event"]["type"] == "status"
        assert runtime.process.wait(timeout=2) == 0
    finally:
        runtime.close()


def test_optimize_streams_complete_mock_event_chain():
    runtime = RuntimeProcess()
    try:
        runtime.send(optimize_command("req-1", "请写一封商务邮件确认会议时间。"))
        envelopes = runtime.read_until("req-1", "metric")
        events = [item["event"] for item in envelopes if item["request_id"] == "req-1"]

        assert [event["type"] for event in events] == [
            "status",
            "scene",
            "request",
            "chunk",
            "done",
            "metric",
        ]
        assert events[1]["data"]["scene"] == "email"
        assert events[4]["data"]["text"]
    finally:
        runtime.close()


def test_cancel_stops_running_request_without_done():
    runtime = RuntimeProcess()
    try:
        runtime.send(optimize_command("req-cancel", "写一封邮件", delay_ms=80, chunks=["first", "late"]))
        runtime.read_until("req-cancel", "chunk")
        runtime.send({"version": 1, "request_id": "req-cancel", "type": "cancel", "payload": {}})
        envelopes = runtime.read_until("req-cancel", "status")
        events = [item["event"] for item in envelopes if item["request_id"] == "req-cancel"]

        assert any(event["data"].get("phase") == "cancelled" for event in events)
        assert all(event["type"] != "done" for event in events)
    finally:
        runtime.close()


def test_invalid_json_returns_protocol_error_on_stdout_and_redacted_diagnostic_on_stderr():
    runtime = RuntimeProcess()
    try:
        runtime.send('{"version":1,"request_id":"bad","type":"ping","payload":{"api_key":"sk-test-1234567890abcdef"}')
        envelope = runtime.read_event()

        assert envelope["request_id"] == "runtime"
        assert envelope["event"]["type"] == "error"
        assert "sk-test-1234567890abcdef" not in envelope["event"]["data"]["message"]
        assert "Traceback" not in "\n".join(list(runtime.stderr.queue))
    finally:
        runtime.close()


def test_parallel_requests_keep_request_ids_isolated():
    runtime = RuntimeProcess()
    try:
        runtime.send(optimize_command("req-a", "请写一封邮件", delay_ms=20, chunks=["A"]))
        runtime.send(optimize_command("req-b", "总结这份报告", delay_ms=10, chunks=["B"]))
        seen: dict[str, list[str]] = {"req-a": [], "req-b": []}
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and not all("done" in values for values in seen.values()):
            envelope = runtime.read_event(timeout=0.5)
            request_id = envelope["request_id"]
            if request_id in seen:
                seen[request_id].append(envelope["event"]["type"])

        assert "done" in seen["req-a"]
        assert "done" in seen["req-b"]
    finally:
        runtime.close()
