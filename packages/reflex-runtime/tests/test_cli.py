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
    def __init__(self, *, provider_fixture: bool = False) -> None:
        env = os.environ.copy()
        python_path = [
            str(PACKAGE_ROOT / "src"),
            str(REPO_ROOT / "packages" / "reflex-core" / "src"),
        ]
        if provider_fixture:
            python_path.insert(0, str(PACKAGE_ROOT / "tests" / "fixtures"))
        env["PYTHONPATH"] = os.pathsep.join(python_path)
        env["REFLEX_RUNTIME_DEVELOPMENT"] = "1"
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


def optimize_command(
    request_id: str,
    text: str,
    *,
    provider: str = "mock",
    model: str = "mock-stream",
    **metadata,
):
    return {
        "version": 1,
        "request_id": request_id,
        "type": "optimize",
        "payload": {
            "text": text,
            "style": "concise",
            "provider": provider,
            "model": model,
            "metadata": metadata,
        },
    }


def configure_provider_command(
    request_id: str,
    secret: str,
    *,
    model: str = "fixture-model-a",
):
    return {
        "version": 1,
        "request_id": request_id,
        "type": "configure_provider",
        "payload": {
            "provider_id": "minimax",
            "secret": secret,
            "config": {
                "model": model,
                "base_url": "https://fixture.invalid/v1/chat/completions",
                "tls_verify": True,
                "ca_bundle_path": None,
            },
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
            try:
                envelope = runtime.read_event(timeout=0.5)
            except queue.Empty:
                continue
            request_id = envelope["request_id"]
            if request_id in seen:
                seen[request_id].append(envelope["event"]["type"])

        assert "done" in seen["req-a"]
        assert "done" in seen["req-b"]
    finally:
        runtime.close()


def test_configure_provider_then_optimize_uses_the_selected_fixture_without_secret_leakage():
    runtime = RuntimeProcess(provider_fixture=True)
    secret = "fixture-runtime-private-credential"
    try:
        runtime.send(configure_provider_command("config-1", secret))
        configured = runtime.read_event()

        assert configured["request_id"] == "config-1"
        assert configured["event"]["type"] == "status"
        assert configured["event"]["data"]["phase"] == "completed"

        runtime.send(
            optimize_command(
                "provider-1",
                "待优化内容",
                provider="minimax",
                model="fixture-model-a",
            )
        )
        envelopes = runtime.read_until("provider-1", "done")
        events = [item["event"] for item in envelopes if item["request_id"] == "provider-1"]

        assert events[-1]["data"]["text"] == "fixture-model-a:待优化内容"
        visible = json.dumps([configured, *envelopes], ensure_ascii=False)
        diagnostics = "\n".join(list(runtime.stderr.queue))
        assert secret not in visible
        assert secret not in diagnostics
    finally:
        runtime.close()


def test_builtin_template_pack_reaches_provider_with_manual_scene_and_language():
    runtime = RuntimeProcess(provider_fixture=True)
    try:
        runtime.send(
            configure_provider_command(
                "config-template",
                "fixture-template-private-credential",
            )
        )
        assert runtime.read_event()["event"]["type"] == "status"

        runtime.send(
            {
                "version": 1,
                "request_id": "template-lifecycle",
                "type": "optimize",
                "payload": {
                    "text": "Review this implementation.",
                    "mode": "prompt",
                    "style": "precise",
                    "scene": "code_review",
                    "scene_policy": "manual",
                    "provider": "minimax",
                    "model": "fixture-model-a",
                    "stream": True,
                    "metadata": {
                        "language": "en-US",
                        "fixture_template_contract": True,
                    },
                },
            }
        )
        envelopes = runtime.read_until("template-lifecycle", "done")
        done = next(
            item["event"]
            for item in envelopes
            if item["request_id"] == "template-lifecycle"
            and item["event"]["type"] == "done"
        )

        assert done["data"]["text"] == "template-contract-ok"
        scene = next(
            item["event"]
            for item in envelopes
            if item["request_id"] == "template-lifecycle"
            and item["event"]["type"] == "scene"
        )
        assert scene["data"]["scene"] == "code_review"
        assert scene["data"]["method"] == "manual"
    finally:
        runtime.close()


def test_provider_lifecycle_keeps_private_fixture_values_out_of_stdout_and_stderr():
    runtime = RuntimeProcess(provider_fixture=True)
    secret = "fixture-lifecycle-private-credential"
    auth_request = "fixture-private-auth-request"
    cancelled_response = "fixture-private-late-response"
    captured: list[dict] = []
    try:
        runtime.send(configure_provider_command("config-lifecycle", secret))
        configured = runtime.read_event()
        captured.append(configured)
        assert configured["event"]["type"] == "status"

        runtime.send(
            optimize_command(
                "stream-lifecycle",
                "normal fixture request",
                provider="minimax",
                model="fixture-model-a",
            )
        )
        streamed = runtime.read_until("stream-lifecycle", "done")
        captured.extend(streamed)

        runtime.send(
            optimize_command(
                "cancel-lifecycle",
                "cancel fixture request",
                provider="minimax",
                model="fixture-model-a",
                delay_ms=80,
                chunks=["fixture-visible-first-chunk", cancelled_response],
            )
        )
        first_chunk = runtime.read_until("cancel-lifecycle", "chunk")
        captured.extend(first_chunk)
        runtime.send(
            {
                "version": 1,
                "request_id": "cancel-lifecycle",
                "type": "cancel",
                "payload": {},
            }
        )
        cancelled = runtime.read_until("cancel-lifecycle", "status")
        captured.extend(cancelled)
        assert any(
            item["event"]["data"].get("phase") == "cancelled"
            for item in cancelled
            if item["request_id"] == "cancel-lifecycle"
        )

        runtime.send(
            optimize_command(
                "auth-lifecycle",
                auth_request,
                provider="minimax",
                model="fixture-model-a",
            )
        )
        auth_failed = runtime.read_until("auth-lifecycle", "error")
        captured.extend(auth_failed)
        assert any(
            item["event"]["data"].get("code") == "provider_auth_failed"
            for item in auth_failed
            if item["request_id"] == "auth-lifecycle"
        )

        runtime.send(
            {
                "version": 1,
                "request_id": "shutdown-lifecycle",
                "type": "shutdown",
                "payload": {},
            }
        )
        shutdown = runtime.read_event()
        captured.append(shutdown)
        assert shutdown["request_id"] == "shutdown-lifecycle"
        assert runtime.process.wait(timeout=2) == 0

        visible = json.dumps(captured, ensure_ascii=False)
        diagnostics = "\n".join(list(runtime.stderr.queue))
        combined = f"{visible}\n{diagnostics}"
        for private_value in [
            secret,
            auth_request,
            cancelled_response,
            f"Authorization: Bearer {secret}",
        ]:
            assert private_value not in combined
    finally:
        runtime.close()


def test_reconfiguring_provider_replaces_the_model_for_later_requests():
    runtime = RuntimeProcess(provider_fixture=True)
    try:
        runtime.send(
            configure_provider_command(
                "config-a",
                "fixture-first-private-credential",
                model="fixture-model-a",
            )
        )
        assert runtime.read_event()["event"]["type"] == "status"
        runtime.send(
            configure_provider_command(
                "config-b",
                "fixture-second-private-credential",
                model="fixture-model-b",
            )
        )
        assert runtime.read_event()["event"]["type"] == "status"

        runtime.send(
            optimize_command(
                "provider-b",
                "新请求",
                provider="minimax",
                model="fixture-model-b",
            )
        )
        events = runtime.read_until("provider-b", "done")

        assert any(
            item["event"].get("data", {}).get("text") == "fixture-model-b:新请求"
            for item in events
        )
    finally:
        runtime.close()


def test_unconfigured_provider_returns_a_recoverable_settings_error_without_mock_fallback():
    runtime = RuntimeProcess()
    try:
        runtime.send(
            optimize_command(
                "provider-missing",
                "不能进入 Mock",
                provider="minimax",
                model="MiniMax-M2.7-highspeed",
            )
        )
        envelopes = runtime.read_until("provider-missing", "error")
        error = next(
            item["event"]
            for item in envelopes
            if item["request_id"] == "provider-missing" and item["event"]["type"] == "error"
        )

        assert error["data"]["code"] == "provider_unconfigured"
        assert error["data"]["action"] == "settings"
        assert all(item["event"]["type"] != "done" for item in envelopes)
    finally:
        runtime.close()
