import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from reflex_core import CancellationToken, OperationCancelled
import reflex_runtime.cli as runtime_cli
from reflex_runtime.capability_registry import CapabilityRegistry
from reflex_runtime.cli import OsFdAdapter, _ProtocolStreams, _isolate_process_output
from reflex_runtime.context import RuntimeContext
from reflex_runtime.plugin_contracts import PluginDescriptor
from reflex_runtime.protocol import parse_command


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]


class RuntimeProcess:
    def __init__(
        self, *, provider_fixture: bool = False, noisy_fixture: bool = False
    ) -> None:
        env = os.environ.copy()
        python_path = [
            str(PACKAGE_ROOT / "src"),
            str(REPO_ROOT / "packages" / "reflex-core" / "src"),
        ]
        if provider_fixture:
            python_path.insert(0, str(PACKAGE_ROOT / "tests" / "fixtures"))
        env["PYTHONPATH"] = os.pathsep.join(python_path)
        env["REFLEX_RUNTIME_DEVELOPMENT"] = "1"
        if noisy_fixture:
            env["REFLEX_NOISY_FIXTURE"] = "1"
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
        self.protocol_noise: queue.Queue[str] = queue.Queue()
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
                try:
                    self.stdout.put(json.loads(line))
                except json.JSONDecodeError:
                    self.protocol_noise.put(line.strip())

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


class FixtureCapability:
    descriptor = PluginDescriptor(
        plugin_id="translator",
        display_name="Fixture Translator",
        version="fixture-1",
        kind="transformer",
        permissions=(),
        operations=("translate",),
        public_operations=("translate",),
    )

    def invoke(self, operation, payload, services, cancellation):
        assert operation == "translate"
        assert services == {"fixture_service": True}
        assert not cancellation.is_cancelled
        return {"text": payload["text"].upper()}


class StreamingFixtureCapability(FixtureCapability):
    def invoke(self, operation, payload, services, cancellation):
        yield {"status": "chunk", "data": {"text": "A"}}
        yield {"status": "progress", "data": {"percent": 50}}
        yield {"status": "result", "data": {"text": "AB"}}


class GatewayFixtureCapability:
    descriptor = PluginDescriptor(
        plugin_id="translator",
        display_name="Gateway Translator",
        version="fixture-1",
        kind="transformer",
        permissions=("network-via-provider",),
        operations=("translate",),
        public_operations=("translate",),
    )

    def __init__(self):
        self.payload = None
        self.service_keys = None

    def invoke(self, operation, payload, services, cancellation):
        self.payload = payload
        self.service_keys = tuple(services)
        gateway = services["provider_gateway"]
        chunks = []
        for chunk in gateway(
            {
                "messages": [
                    {"role": "system", "content": "Translate only."},
                    {"role": "user", "content": payload["text"]},
                ]
            },
            payload["text"],
            cancellation,
        ):
            chunks.append(chunk)
            yield {"status": "chunk", "data": {"text": chunk}}
        yield {"status": "result", "data": {"text": "".join(chunks)}}


class RecordingGatewayProvider:
    id = "minimax"
    model = "fixture-model-a"

    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def stream(self, rendered, request, cancellation):
        self.calls.append((rendered, request, cancellation))
        if self.error is not None:
            raise self.error
        yield "translated"


class RecordingProviderRegistry:
    def __init__(self, provider=None, error=None):
        self.provider = provider
        self.error = error
        self.calls = []

    def resolve(self, provider_id, model):
        self.calls.append((provider_id, model))
        if self.error is not None:
            raise self.error
        return self.provider


class FixtureHistoryCapability:
    descriptor = PluginDescriptor(
        plugin_id="history-sqlite",
        display_name="Fixture History",
        version="fixture-1",
        kind="storage",
        permissions=("storage_read", "storage_write"),
        operations=(
            "save",
            "list",
            "detail",
            "rate",
            "delete",
            "clear",
            "export",
            "scan",
            "repair",
            "backups",
            "restore",
            "rotate",
        ),
        public_operations=("list", "detail", "rate", "backups", "scan"),
    )

    def invoke(self, operation, payload, services, cancellation):
        return {"ok": True}


class BlockingFixtureCapability(FixtureCapability):
    def __init__(self, entered, release):
        self.entered = entered
        self.release = release

    def invoke(self, operation, payload, services, cancellation):
        self.entered.set()
        self.release.wait(timeout=2)
        return {"released": True}


class CancellingFixtureCapability(FixtureCapability):
    def __init__(self, mode):
        self.mode = mode

    def invoke(self, operation, payload, services, cancellation):
        if self.mode == "generator":
            return self._generate(cancellation)
        cancellation.cancel()
        if self.mode == "generic":
            raise RuntimeError("fixture failure after cancellation")
        cancellation.raise_if_cancelled()

    @staticmethod
    def _generate(cancellation):
        yield {"status": "chunk", "data": {"text": "first"}}
        cancellation.cancel()
        cancellation.raise_if_cancelled()


_MISSING_CODE = object()


def _unreadable_dynamic_failure(class_marker, private_body, code=_MISSING_CODE):
    def refuse_str(self):
        raise AssertionError("Runtime must not stringify plugin exceptions")

    def refuse_repr(self):
        raise AssertionError("Runtime must not repr plugin exceptions")

    attributes = {
        "__str__": refuse_str,
        "__repr__": refuse_repr,
    }
    if code is not _MISSING_CODE:
        attributes["code"] = code
    error_type = type(f"Private{class_marker}", (RuntimeError,), attributes)
    error = error_type()
    error.private_body = private_body
    return error


class FailingHistoryCapability(FixtureHistoryCapability):
    def __init__(self, error):
        self.error = error

    def invoke(self, operation, payload, services, cancellation):
        raise self.error


class FailingFixtureCapability(FixtureCapability):
    def __init__(self, error):
        self.error = error

    def invoke(self, operation, payload, services, cancellation):
        raise self.error


def _runtime_with_capability(capability, output, **kwargs):
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    return RuntimeContext(
        stdout=output,
        development=False,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
        **kwargs,
    )


def test_fd_adapter_closes_first_duplicate_when_second_duplicate_fails():
    class FailingFdAdapter:
        def __init__(self):
            self.closed = []

        def duplicate(self, fd):
            if fd == 1:
                return 101
            raise OSError("fixture duplicate failure")

        def close_fd(self, fd):
            self.closed.append(fd)

    adapter = FailingFdAdapter()

    with pytest.raises(OSError):
        _isolate_process_output(adapter)

    assert adapter.closed == [101]


def test_protocol_streams_close_restores_real_os_fds_and_python_streams():
    original_fd1 = os.dup(1)
    original_fd2 = os.dup(2)
    read_fd, write_fd = os.pipe()
    original_streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    streams = None
    try:
        os.dup2(write_fd, 1)
        os.dup2(write_fd, 2)
        os.close(write_fd)
        write_fd = None

        streams = _isolate_process_output(OsFdAdapter())
        os.write(1, b"fixture-pollution\n")
        streams.close()
        streams = None
        os.write(1, b"fixture-restored\n")
        assert (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__) == original_streams

        os.dup2(original_fd1, 1)
        os.dup2(original_fd2, 2)
        data = os.read(read_fd, 4096)
    finally:
        if streams is not None:
            streams.close()
        os.dup2(original_fd1, 1)
        os.dup2(original_fd2, 2)
        os.close(original_fd1)
        os.close(original_fd2)
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)

    assert b"fixture-restored" in data
    assert b"fixture-pollution" not in data


def test_partial_fd_installation_failure_restores_original_descriptors():
    from io import StringIO

    class FailingInstallAdapter:
        def __init__(self):
            self.next_fd = 100
            self.opens = 0
            self.restored = []
            self.closed = []

        def duplicate(self, fd):
            self.next_fd += 1
            return self.next_fd

        def redirect_outputs_to_sink(self):
            return None

        def open_writer(self, fd):
            self.opens += 1
            if self.opens == 2:
                raise OSError("fixture writer failure")
            return StringIO()

        def restore(self, source_fd, target_fd):
            self.restored.append((source_fd, target_fd))

        def close_fd(self, fd):
            self.closed.append(fd)

    adapter = FailingInstallAdapter()

    with pytest.raises(OSError):
        _isolate_process_output(adapter)

    assert adapter.restored == [(101, 1), (102, 2)]
    assert {101, 102}.issubset(adapter.closed)


def test_second_dup2_failure_restores_fd1_to_original_pipe():
    class SecondRedirectFailsAdapter(OsFdAdapter):
        @staticmethod
        def redirect_outputs_to_sink():
            sink_fd = os.open(os.devnull, os.O_WRONLY)
            try:
                os.dup2(sink_fd, 1)
                raise OSError("fixture fd2 redirect failure")
            finally:
                os.close(sink_fd)

    outer_fd1 = os.dup(1)
    outer_fd2 = os.dup(2)
    read_fd, write_fd = os.pipe()
    try:
        os.dup2(write_fd, 1)
        os.close(write_fd)
        write_fd = None

        with pytest.raises(OSError):
            _isolate_process_output(SecondRedirectFailsAdapter())
        os.write(1, b"fixture-fd1-restored\n")

        os.dup2(outer_fd1, 1)
        data = os.read(read_fd, 4096)
    finally:
        os.dup2(outer_fd1, 1)
        os.dup2(outer_fd2, 2)
        os.close(outer_fd1)
        os.close(outer_fd2)
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)

    assert b"fixture-fd1-restored" in data


def test_one_restore_failure_does_not_block_other_restore_or_fd_closure():
    class RestoreFailureAdapter:
        def __init__(self):
            self.next_fd = 100
            self.restored = []
            self.closed = []

        def duplicate(self, fd):
            self.next_fd += 1
            return self.next_fd

        def redirect_outputs_to_sink(self):
            raise OSError("fixture redirect failure")

        def restore(self, source_fd, target_fd):
            self.restored.append((source_fd, target_fd))
            if target_fd == 1:
                raise OSError("fixture fd1 restore failure")

        def close_fd(self, fd):
            self.closed.append(fd)

    adapter = RestoreFailureAdapter()

    with pytest.raises(OSError):
        _isolate_process_output(adapter)

    assert adapter.restored == [(101, 1), (102, 2)]
    assert set(adapter.closed) == {101, 102, 103, 104}


@pytest.mark.parametrize("failed_target", [1, 2])
def test_protocol_stream_close_finishes_all_cleanup_after_restore_failure(
    failed_target
):
    from io import StringIO

    class FailingRestoreAdapter:
        def __init__(self):
            self.restored = []
            self.closed = []

        def restore(self, source_fd, target_fd):
            self.restored.append((source_fd, target_fd))
            if target_fd == failed_target:
                raise OSError(f"fixture fd{target_fd} restore failure")

        def close_fd(self, fd):
            self.closed.append(fd)

    actual_streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    protocol = StringIO()
    diagnostic = StringIO()
    sink_stdout = StringIO()
    sink_stderr = StringIO()
    adapter = FailingRestoreAdapter()
    streams = _ProtocolStreams(
        fd_adapter=adapter,
        original_fd1=101,
        original_fd2=102,
        protocol=protocol,
        diagnostic=diagnostic,
        sink_stdout=sink_stdout,
        sink_stderr=sink_stderr,
        original_stdout=actual_streams[0],
        original_stderr=actual_streams[1],
        original_dunder_stdout=actual_streams[2],
        original_dunder_stderr=actual_streams[3],
    )
    sys.stdout = sink_stdout
    sys.stderr = sink_stderr
    sys.__stdout__ = sink_stdout
    sys.__stderr__ = sink_stderr
    try:
        with pytest.raises(OSError, match=f"fd{failed_target} restore failure"):
            streams.close()
    finally:
        sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__ = actual_streams

    assert adapter.restored == [(101, 1), (102, 2)]
    assert adapter.closed == [101, 102]
    assert all(
        stream.closed
        for stream in (protocol, diagnostic, sink_stdout, sink_stderr)
    )
    assert streams.closed is True


def test_protocol_stream_close_is_idempotent_after_complete_cleanup():
    from io import StringIO

    class TrackingAdapter:
        def __init__(self):
            self.restored = []
            self.closed = []

        def restore(self, source_fd, target_fd):
            self.restored.append((source_fd, target_fd))

        def close_fd(self, fd):
            self.closed.append(fd)

    actual_streams = (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__)
    wrappers = [StringIO() for _ in range(4)]
    adapter = TrackingAdapter()
    streams = _ProtocolStreams(
        fd_adapter=adapter,
        original_fd1=201,
        original_fd2=202,
        protocol=wrappers[0],
        diagnostic=wrappers[1],
        sink_stdout=wrappers[2],
        sink_stderr=wrappers[3],
        original_stdout=actual_streams[0],
        original_stderr=actual_streams[1],
        original_dunder_stdout=actual_streams[2],
        original_dunder_stderr=actual_streams[3],
    )

    streams.close()
    streams.close()

    assert adapter.restored == [(201, 1), (202, 2)]
    assert adapter.closed == [201, 202]


@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("ping", {}),
        ("list_plugins", {}),
        ("configure_plugin", {"plugin_id": "translator", "enabled": False}),
        ("configure_history_keys", {"keys": {"v1": "11" * 32}}),
        (
            "configure_history_policy",
            {
                "history_enabled": True,
                "privacy_mode": False,
                "history_redaction": "secrets",
            },
        ),
        (
            "configure_provider",
            {"provider_id": "minimax", "secret": "fixture-secret", "config": {}},
        ),
        ("shutdown", {}),
    ],
)
def test_active_plugin_request_id_rejects_every_responding_sync_command(
    command_type, payload
):
    from io import StringIO

    entered = threading.Event()
    release = threading.Event()
    output = StringIO()
    diagnostics = StringIO()
    capability = BlockingFixtureCapability(entered, release)
    runtime = _runtime_with_capability(capability, output, stderr=diagnostics)
    request_id = "shutdown" if command_type == "shutdown" else "cross-id"
    plugin_command = parse_command(
        {
            "version": 1,
            "request_id": request_id,
            "type": "plugin_call",
            "payload": {
                "plugin_id": "translator",
                "operation": "translate",
                "input": {"text": "fixture"},
            },
        }
    )
    runtime.handle(plugin_command)
    assert entered.wait(timeout=1)

    keep_running = runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": request_id,
                "type": command_type,
                "payload": payload,
            }
        )
    )
    assert runtime.has_active_tasks()
    release.set()
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert keep_running is True
    assert [event.get("status") for event in events] == ["started", "result"]
    assert all(event.get("type") == "plugin_event" for event in events)
    diagnostic = diagnostics.getvalue()
    assert "duplicate_request_id" in diagnostic
    assert request_id in diagnostic
    assert "fixture-secret" not in diagnostic


def test_active_plugin_id_silently_rejects_duplicate_async_commands():
    from io import StringIO

    entered = threading.Event()
    release = threading.Event()
    output = StringIO()
    diagnostics = StringIO()
    capability = BlockingFixtureCapability(entered, release)
    runtime = _runtime_with_capability(
        capability, output, stderr=diagnostics
    )
    active = {
        "version": 1,
        "request_id": "plugin-owned",
        "type": "plugin_call",
        "payload": {
            "plugin_id": "translator",
            "operation": "translate",
            "input": {"text": "original-body"},
        },
    }
    runtime.handle(parse_command(active))
    assert entered.wait(timeout=1)

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "plugin-owned",
                "type": "optimize",
                "payload": {"text": "duplicate-sensitive-body"},
            }
        )
    )
    runtime.handle(parse_command(active))
    assert runtime.has_active_tasks()
    release.set()
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert [event.get("status") for event in events] == ["started", "result"]
    assert diagnostics.getvalue().count("duplicate_request_id") == 2
    assert "duplicate-sensitive-body" not in diagnostics.getvalue()


def test_active_optimize_id_silently_rejects_sync_and_async_duplicates():
    from io import StringIO

    output = StringIO()
    diagnostics = StringIO()
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=True,
    )
    active = {
        "version": 1,
        "request_id": "optimize-owned",
        "type": "optimize",
        "payload": {
            "text": "original optimize",
            "provider": "mock",
            "model": "mock-stream",
            "metadata": {"delay_ms": 120, "chunks": ["first", "last"]},
        },
    }
    runtime.handle(parse_command(active))
    deadline = time.monotonic() + 2
    while "\"type\": \"chunk\"" not in output.getvalue() and time.monotonic() < deadline:
        time.sleep(0.01)

    for duplicate in (
        {"version": 1, "request_id": "optimize-owned", "type": "ping", "payload": {}},
        active,
        {
            "version": 1,
            "request_id": "optimize-owned",
            "type": "plugin_call",
            "payload": {
                "plugin_id": "translator",
                "operation": "translate",
                "input": {"text": "duplicate plugin body"},
            },
        },
    ):
        runtime.handle(parse_command(duplicate))
    assert runtime.has_active_tasks()
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    core_types = [event["event"]["type"] for event in events if "event" in event]

    assert core_types.count("done") == 1
    assert "error" not in core_types
    assert all(event.get("type") != "plugin_event" for event in events)
    assert diagnostics.getvalue().count("duplicate_request_id") == 3
    assert "duplicate plugin body" not in diagnostics.getvalue()


def test_optimize_saves_a_private_history_snapshot_and_reports_save_state(tmp_path):
    from io import StringIO

    class RecordingHistoryCapability(FixtureHistoryCapability):
        def __init__(self):
            self.saved = []

        def invoke(self, operation, payload, services, cancellation):
            if operation == "save":
                self.saved.append(dict(payload))
                return {"id": payload["id"]}
            return super().invoke(operation, payload, services, cancellation)

    output = StringIO()
    diagnostics = StringIO()
    capability = RecordingHistoryCapability()
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )
    registry.configure_history_path(tmp_path / "history" / "history.sqlite3")
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=True,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "history-save-optimize",
                "type": "optimize",
                "payload": {
                    "text": "save this result",
                    "provider": "mock",
                    "model": "mock-stream",
                    "mode": "content",
                    "style": "balanced",
                    "scene": None,
                    "scene_policy": "auto",
                    "metadata": {"chunks": ["saved output"]},
                },
            }
        )
    )

    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)

    envelopes = [json.loads(line) for line in output.getvalue().splitlines()]
    done = next(item["event"] for item in envelopes if item["event"]["type"] == "done")
    metric = next(
        item["event"] for item in envelopes if item["event"]["type"] == "metric"
    )

    assert len(capability.saved) == 1
    assert capability.saved[0]["input"] == "save this result"
    assert capability.saved[0]["output"] == "saved output"
    assert done["data"]["history_id"] is None
    assert done["data"]["save_status"] == "saving"
    assert metric["data"]["history_id"] == capability.saved[0]["id"]
    assert metric["data"]["save_status"] == "saved"


@pytest.mark.parametrize(
    ("history_enabled", "privacy_mode", "expected_status"),
    [(False, False, "unsaved"), (True, True, "private")],
)
def test_optimize_never_backfills_history_disabled_or_private_at_start(
    tmp_path, history_enabled, privacy_mode, expected_status
):
    from io import StringIO

    class RecordingHistoryCapability(FixtureHistoryCapability):
        def __init__(self):
            self.saved = []

        def invoke(self, operation, payload, services, cancellation):
            if operation == "save":
                self.saved.append(dict(payload))
            return super().invoke(operation, payload, services, cancellation)

    output = StringIO()
    capability = RecordingHistoryCapability()
    registry = CapabilityRegistry([(capability.descriptor, capability)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=history_enabled,
        privacy_mode=privacy_mode,
        history_redaction="secrets",
    )
    registry.configure_history_path(tmp_path / "history" / "history.sqlite3")
    runtime = RuntimeContext(
        stdout=output,
        development=True,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": f"history-policy-{expected_status}",
                "type": "optimize",
                "payload": {
                    "text": "policy snapshot",
                    "provider": "mock",
                    "model": "mock-stream",
                    "metadata": {"chunks": ["policy result"]},
                },
            }
        )
    )
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)

    events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
    done = next(event for event in events if event["type"] == "done")
    metric = next(event for event in events if event["type"] == "metric")
    assert capability.saved == []
    assert done["data"]["save_status"] == expected_status
    assert metric["data"]["save_status"] == expected_status
    assert metric["data"]["history_id"] is None


def test_history_save_failure_does_not_replace_the_completed_result(tmp_path):
    from io import StringIO

    class FailingSaveCapability(FixtureHistoryCapability):
        def invoke(self, operation, payload, services, cancellation):
            if operation == "save":
                raise RuntimeError("sensitive fixture body")
            return super().invoke(operation, payload, services, cancellation)

    output = StringIO()
    diagnostics = StringIO()
    capability = FailingSaveCapability()
    registry = CapabilityRegistry([(capability.descriptor, capability)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True, privacy_mode=False, history_redaction="secrets"
    )
    registry.configure_history_path(tmp_path / "history" / "history.sqlite3")
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=True,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "history-save-failure",
                "type": "optimize",
                "payload": {
                    "text": "keep the result",
                    "provider": "mock",
                    "model": "mock-stream",
                    "metadata": {"chunks": ["completed output"]},
                },
            }
        )
    )
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)

    events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
    assert next(event for event in events if event["type"] == "done")["data"]["text"] == "completed output"
    metric = next(event for event in events if event["type"] == "metric")
    assert metric["data"]["save_status"] == "unsaved"
    assert all(event["type"] != "error" for event in events)
    assert "history_save_failed" in diagnostics.getvalue()
    assert "sensitive fixture body" not in diagnostics.getvalue()


def test_history_policy_is_frozen_at_generation_start(tmp_path):
    from io import StringIO

    class RecordingHistoryCapability(FixtureHistoryCapability):
        def __init__(self):
            self.saved = []
            self.redaction = None

        def invoke(self, operation, payload, services, cancellation):
            if operation == "save":
                self.saved.append(dict(payload))
                self.redaction = services["history"]["history_redaction"]
                return {"id": payload["id"]}
            return super().invoke(operation, payload, services, cancellation)

    output = StringIO()
    capability = RecordingHistoryCapability()
    registry = CapabilityRegistry([(capability.descriptor, capability)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True, privacy_mode=False, history_redaction="secrets"
    )
    registry.configure_history_path(tmp_path / "history" / "history.sqlite3")
    runtime = RuntimeContext(
        stdout=output,
        development=True,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "history-redaction-frozen",
                "type": "optimize",
                "payload": {
                    "text": "Bearer fixture-input-token",
                    "provider": "mock",
                    "model": "mock-stream",
                    "metadata": {
                        "delay_ms": 80,
                        "chunks": ["Bearer fixture-output-token"],
                    },
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while '"type": "status"' not in output.getvalue() and time.monotonic() < deadline:
        time.sleep(0.01)
    registry.configure_history_policy(
        history_enabled=True, privacy_mode=True, history_redaction="none"
    )
    deadline = time.monotonic() + 3
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert len(capability.saved) == 1
    assert "fixture-input-token" not in capability.saved[0]["input"]
    assert "fixture-output-token" not in capability.saved[0]["output"]
    assert capability.redaction == "secrets"


@pytest.mark.parametrize("mode", ["direct", "generator", "generic"])
def test_plugin_cancellation_emits_exactly_one_cancelled_terminal(mode):
    from io import StringIO

    output = StringIO()
    capability = CancellingFixtureCapability(mode)
    runtime = _runtime_with_capability(capability, output)
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": f"cancel-{mode}",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {"text": "fixture"},
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    statuses = [event.get("status") for event in events if event.get("type") == "plugin_event"]

    assert statuses.count("cancelled") == 1
    assert statuses[-1] == "cancelled"
    assert "error" not in statuses


@pytest.mark.parametrize("command_type", ["optimize", "plugin_call"])
def test_thread_start_failure_rolls_back_request_id_and_close_skips_join(
    command_type
):
    from io import StringIO

    private_marker = "ThreadStartSensitiveMarker"
    private_body = "thread-start-private-body"
    failure = _unreadable_dynamic_failure(private_marker, private_body)

    class FailingThread:
        def start(self):
            raise failure

        def join(self, timeout=None):
            raise AssertionError("unstarted thread must not be joined")

    output = StringIO()
    diagnostics = StringIO()
    capability = FixtureCapability()
    runtime = _runtime_with_capability(
        capability,
        output,
        stderr=diagnostics,
        thread_factory=lambda **kwargs: FailingThread(),
    )
    payload = (
        {"text": "fixture", "provider": "mock", "model": "mock-stream"}
        if command_type == "optimize"
        else {
            "plugin_id": "translator",
            "operation": "translate",
            "input": {"text": "fixture"},
        }
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "start-failed",
                "type": command_type,
                "payload": payload,
            }
        )
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "start-failed",
                "type": "ping",
                "payload": {},
            }
        )
    )
    runtime.close()
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert any(
        event.get("event", {}).get("data", {}).get("message") == "pong"
        for event in events
    )
    assert diagnostics.getvalue() == (
        "thread_start_failed request_id=start-failed category=thread_start_failed\n"
    )
    assert private_marker not in diagnostics.getvalue()
    assert private_body not in diagnostics.getvalue()


def test_runtime_plugin_call_uses_independent_plugin_event_contract():
    from io import StringIO

    output = StringIO()
    capability = FixtureCapability()
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
        services={"fixture_service": True},
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "plugin-fixture",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {"text": "fixture"},
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert [event["status"] for event in events] == ["started", "result"]
    assert events[-1]["data"] == {"text": "FIXTURE"}
    assert all(event["type"] == "plugin_event" for event in events)
    assert all("event" not in event for event in events)


def test_translator_permission_injects_bound_provider_gateway_and_strips_routing_fields():
    from io import StringIO

    output = StringIO()
    capability = GatewayFixtureCapability()
    provider = RecordingGatewayProvider()
    provider_registry = RecordingProviderRegistry(provider)
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        provider_registry=provider_registry,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
        services={"private_service": object()},
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "translation-gateway",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {
                        "text": "source",
                        "target": "auto",
                        "provider": "minimax",
                        "model": "fixture-model-a",
                    },
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert capability.payload == {"text": "source", "target": "auto"}
    assert capability.service_keys == ("provider_gateway",)
    assert provider_registry.calls == [("minimax", "fixture-model-a")]
    rendered, request, cancellation = provider.calls[0]
    assert rendered["messages"][-1] == {"role": "user", "content": "source"}
    assert request.text == "source"
    assert request.mode == "content"
    assert request.style == "precise"
    assert request.scene == "doc_translation"
    assert request.scene_policy == "manual"
    assert request.provider == "minimax"
    assert request.model == "fixture-model-a"
    assert request.metadata == {"capability": "translator"}
    assert cancellation.is_cancelled is False
    assert [event["status"] for event in events] == ["started", "chunk", "result"]


def test_translator_gateway_reuses_the_explicit_development_mock_provider():
    from io import StringIO

    output = StringIO()
    capability = GatewayFixtureCapability()
    provider_registry = RecordingProviderRegistry(
        error=AssertionError("mock must not resolve through the configured Provider registry")
    )
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=True,
        provider_registry=provider_registry,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "translation-mock",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {
                        "text": "source",
                        "target": "auto",
                        "provider": "mock",
                        "model": "mock-stream",
                    },
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert provider_registry.calls == []
    assert [event["status"] for event in events] == ["started", "chunk", "result"]
    assert "source" in events[-1]["data"]["text"]


@pytest.mark.parametrize(
    ("registry_error", "provider_error", "expected_code"),
    [
        (None, type("SafeProviderFailure", (RuntimeError,), {"code": "provider_auth_failed"})("api_key=private"), "provider_auth_failed"),
        (__import__("reflex_runtime.provider_errors", fromlist=["provider_unconfigured"]).provider_unconfigured(), None, "provider_unconfigured"),
    ],
)
def test_translator_gateway_returns_only_safe_provider_error_codes(
    registry_error, provider_error, expected_code
):
    from io import StringIO

    output = StringIO()
    diagnostics = StringIO()
    capability = GatewayFixtureCapability()
    provider = RecordingGatewayProvider(provider_error)
    provider_registry = RecordingProviderRegistry(provider, registry_error)
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=False,
        provider_registry=provider_registry,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": f"translation-{expected_code}",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {
                        "text": "source",
                        "target": "auto",
                        "provider": "minimax",
                        "model": "fixture-model-a",
                    },
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert events[-1]["status"] == "error"
    assert events[-1]["code"] == expected_code
    assert "private" not in output.getvalue()
    assert "private" not in diagnostics.getvalue()


@pytest.mark.parametrize(
    ("operation", "error_code"),
    [
        ("scan", "history_operation_unavailable"),
        ("rate", "history_storage_busy"),
        ("detail", "history_not_found"),
    ],
)
def test_runtime_forwards_only_safe_structured_history_plugin_error_codes(
    operation, error_code
):
    from io import StringIO

    private_body = f"private-{operation}-exception-body"
    private_payload = f"private-{operation}-payload"
    output = StringIO()
    diagnostics = StringIO()
    capability = FailingHistoryCapability(
        _unreadable_dynamic_failure(
            f"Structured{operation.title()}Marker", private_body, error_code
        )
    )
    registry = CapabilityRegistry([(capability.descriptor, capability)])
    registry.configure_history_keys({"v1": "11" * 32})
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=False,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": f"history-error-{operation}",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "history-sqlite",
                    "operation": operation,
                    "input": {"text": private_payload},
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    visible = f"{output.getvalue()}\n{diagnostics.getvalue()}"

    assert [event["status"] for event in events] == ["started", "error"]
    assert events[-1]["code"] == error_code
    assert private_body not in visible
    assert private_payload not in visible


@pytest.mark.parametrize(
    "code",
    [_MISSING_CODE, "unsafe error code", "x" * 65],
    ids=["missing", "invalid-characters", "too-long"],
)
def test_runtime_falls_back_for_untrusted_plugin_errors_without_reading_content(code):
    from io import StringIO

    private_body = "private-plugin-exception-body"
    private_payload = "private-plugin-payload"
    private_marker = "PluginSensitiveMarker"
    output = StringIO()
    diagnostics = StringIO()
    capability = FailingFixtureCapability(
        _unreadable_dynamic_failure(private_marker, private_body, code)
    )
    runtime = _runtime_with_capability(
        capability, output, stderr=diagnostics, services={"fixture_service": True}
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "untrusted-plugin-error",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {"text": private_payload},
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    visible = f"{output.getvalue()}\n{diagnostics.getvalue()}"

    assert [event["status"] for event in events] == ["started", "error"]
    assert events[-1]["code"] == "plugin_failed"
    assert diagnostics.getvalue() == (
        "plugin_failed request_id=untrusted-plugin-error "
        "category=untrusted_plugin_exception\n"
    )
    assert private_marker not in visible
    assert private_body not in visible
    assert private_payload not in visible


def test_provider_fallback_diagnostic_uses_only_a_fixed_category():
    from io import StringIO

    private_marker = "ProviderSensitiveMarker"
    private_body = "provider-private-body"
    output = StringIO()
    diagnostics = StringIO()
    runtime = RuntimeContext(
        stdout=output,
        stderr=diagnostics,
        development=False,
    )
    failure = _unreadable_dynamic_failure(private_marker, private_body)

    def fail_provider_resolution(_request):
        raise failure

    runtime._resolve_provider = fail_provider_resolution
    runtime.handle(parse_command(optimize_command("provider-fallback", "fixture")))
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    visible = f"{output.getvalue()}\n{diagnostics.getvalue()}"

    assert json.loads(output.getvalue().splitlines()[-1])["event"]["data"]["code"] == "runtime_error"
    assert diagnostics.getvalue() == (
        "runtime_error request_id=provider-fallback "
        "category=untrusted_provider_exception\n"
    )
    assert private_marker not in visible
    assert private_body not in visible


def test_cli_generic_fallback_diagnostic_uses_only_a_fixed_category(monkeypatch):
    from io import StringIO

    private_marker = "CliSensitiveMarker"
    private_body = "cli-private-body"
    failure = _unreadable_dynamic_failure(private_marker, private_body)

    class FixtureStreams:
        def __init__(self):
            self.protocol = StringIO()
            self.diagnostic = StringIO()

        def close(self):
            return None

    streams = FixtureStreams()
    monkeypatch.setattr(runtime_cli, "_isolate_process_output", lambda _adapter: streams)
    monkeypatch.setattr(RuntimeContext, "handle", lambda self, command: (_ for _ in ()).throw(failure))
    monkeypatch.setattr(
        sys,
        "stdin",
        StringIO(
            json.dumps(
                {"version": 1, "request_id": "cli-fallback", "type": "ping", "payload": {}}
            )
            + "\n"
        ),
    )

    assert runtime_cli.main(object()) == 0
    visible = f"{streams.protocol.getvalue()}\n{streams.diagnostic.getvalue()}"

    assert streams.diagnostic.getvalue() == (
        "runtime_error request_id=cli-fallback category=runtime_exception\n"
    )
    assert private_marker not in visible
    assert private_body not in visible


def test_runtime_wraps_streamed_plugin_statuses_in_its_own_envelopes():
    from io import StringIO

    output = StringIO()
    capability = StreamingFixtureCapability()
    registry = CapabilityRegistry(
        [(capability.descriptor, capability)], enabled_plugins={"translator"}
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(capability.descriptor,),
        services={"fixture_service": True},
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "plugin-stream",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "translator",
                    "operation": "translate",
                    "input": {"text": "fixture"},
                },
            }
        )
    )
    deadline = time.monotonic() + 2
    while runtime.has_active_tasks() and time.monotonic() < deadline:
        time.sleep(0.01)
    events = [json.loads(line) for line in output.getvalue().splitlines()]

    assert [event["status"] for event in events] == [
        "started",
        "chunk",
        "progress",
        "result",
    ]
    assert all(event["request_id"] == "plugin-stream" for event in events)


def test_list_plugins_emits_capability_list_instead_of_core_event():
    runtime = RuntimeProcess()
    try:
        runtime.send(
            {
                "version": 1,
                "request_id": "plugins-1",
                "type": "list_plugins",
                "payload": {},
            }
        )
        envelope = runtime.read_event()

        assert envelope["type"] == "capability_list"
        assert "event" not in envelope
        assert {plugin["id"] for plugin in envelope["plugins"]} == {
                "history-sqlite",
                "batch-runner",
                "translator",
                "markdown-preview",
                "semantic-detector",
            }
        listed = {plugin["id"]: plugin for plugin in envelope["plugins"]}
        assert listed["history-sqlite"]["public_operations"] == [
            "list",
            "detail",
            "rate",
            "backups",
            "scan",
        ]
        assert listed["markdown-preview"]["public_operations"] == ["preview"]
        assert all("operations" not in plugin for plugin in envelope["plugins"])
    finally:
        runtime.close()


def test_context_list_uses_registry_unavailable_state_for_unloaded_history():
    from io import StringIO

    output = StringIO()
    descriptor = FixtureHistoryCapability.descriptor
    registry = CapabilityRegistry([], known_descriptors=(descriptor,))
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(descriptor,),
    )

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "keys-unloaded",
                "type": "configure_history_keys",
                "payload": {"keys": {"v1": "11" * 32}},
            }
        )
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "list-unloaded",
                "type": "list_plugins",
                "payload": {},
            }
        )
    )
    listed = json.loads(output.getvalue().splitlines()[-1])["plugins"][0]

    assert listed["state"] == "unavailable"
    assert listed["error_code"] == "plugin_unavailable"


def test_context_list_tracks_loaded_history_policy_state_changes():
    from io import StringIO

    output = StringIO()
    plugin = FixtureHistoryCapability()
    descriptor = plugin.descriptor
    registry = CapabilityRegistry(
        [(descriptor, plugin)], known_descriptors=(descriptor,)
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(descriptor,),
    )

    for request_id, command_type, payload in (
        (
            "keys-loaded",
            "configure_history_keys",
            {"keys": {"v1": "11" * 32}},
        ),
        (
            "policy-loaded",
            "configure_history_policy",
            {
                "history_enabled": True,
                "privacy_mode": True,
                "history_redaction": "secrets",
            },
        ),
        ("list-loaded", "list_plugins", {}),
    ):
        runtime.handle(
            parse_command(
                {
                    "version": 1,
                    "request_id": request_id,
                    "type": command_type,
                    "payload": payload,
                }
            )
        )
    listed = json.loads(output.getvalue().splitlines()[-1])["plugins"][0]

    assert listed["state"] == "private"
    assert "error_code" not in listed


def test_context_configures_private_history_path_without_touching_filesystem(tmp_path):
    from io import StringIO

    output = StringIO()
    observed = {}

    class RecordingHistory(FixtureHistoryCapability):
        def invoke(self, operation, payload, services, cancellation):
            observed["services"] = services
            return super().invoke(operation, payload, services, cancellation)

    plugin = RecordingHistory()
    descriptor = plugin.descriptor
    registry = CapabilityRegistry([(descriptor, plugin)])
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(descriptor,),
    )
    database_path = tmp_path / "app-data" / "history" / "history.sqlite3"

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "history-path-private",
                "type": "configure_history_path",
                "payload": {"database_path": str(database_path)},
            }
        )
    )
    registry.configure_history_keys({"v1": "11" * 32})
    registry.invoke_public(
        "history-sqlite", "list", {}, {}, CancellationToken()
    )

    assert observed["services"]["history"]["database_path"] == database_path
    assert not database_path.parent.exists()
    event = json.loads(output.getvalue().splitlines()[-1])
    assert event["event"]["data"]["message"] == "history_path_configured"
    assert str(database_path) not in output.getvalue()


def test_disabled_history_with_keys_is_listed_as_read_only():
    from io import StringIO

    output = StringIO()
    plugin = FixtureHistoryCapability()
    descriptor = plugin.descriptor
    registry = CapabilityRegistry(
        [(descriptor, plugin)], known_descriptors=(descriptor,)
    )
    runtime = RuntimeContext(
        stdout=output,
        stderr=StringIO(),
        development=False,
        capability_registry=registry,
        capability_descriptors=(descriptor,),
    )
    for request_id, command_type, payload in (
        (
            "disabled-history-keys",
            "configure_history_keys",
            {"keys": {"v1": "11" * 32}},
        ),
        (
            "disabled-history-policy",
            "configure_history_policy",
            {
                "history_enabled": False,
                "privacy_mode": False,
                "history_redaction": "secrets",
            },
        ),
        ("disabled-history-list", "list_plugins", {}),
    ):
        runtime.handle(
            parse_command(
                {
                    "version": 1,
                    "request_id": request_id,
                    "type": command_type,
                    "payload": payload,
                }
            )
        )

    listed = json.loads(output.getvalue().splitlines()[-1])["plugins"][0]
    assert listed["state"] == "read_only"


def test_plugin_import_print_dunder_stdout_and_fd_write_do_not_pollute_protocol():
    runtime = RuntimeProcess(provider_fixture=True, noisy_fixture=True)
    try:
        runtime.send(
            {"version": 1, "request_id": "quiet-1", "type": "ping", "payload": {}}
        )
        event = runtime.read_event()

        assert event["request_id"] == "quiet-1"
        time.sleep(0.1)
        assert list(runtime.protocol_noise.queue) == []
    finally:
        runtime.close()


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


def test_cli_accepts_an_initial_utf8_bom():
    runtime = RuntimeProcess()
    try:
        runtime.send(
            "\ufeff"
            + json.dumps(
                {"version": 1, "request_id": "bom-ping", "type": "ping", "payload": {}}
            )
        )
        ping = runtime.read_event()

        assert ping["request_id"] == "bom-ping"
        assert ping["event"]["data"]["message"] == "pong"
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
