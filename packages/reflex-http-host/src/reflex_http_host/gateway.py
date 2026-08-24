"""Sidecar gateway: bridge HTTP requests to the runtime sidecar NDJSON stream.

The gateway owns one ``reflex_runtime.cli`` subprocess (the same shape the
Tauri host uses) and routes protocol events back to per-request SSE
subscriptions by ``request_id``.  No provider credentials are inherited by
the child process; the environment is a fixed allowlist.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from reflex_core.protocol import new_request_id

RUNTIME_PROTOCOL_VERSION = 1
MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_BUFFERED_EVENTS = 64
MAX_QUEUED_EVENTS = 4_096
MAX_STDERR_BYTES = 8 * 1024 * 1024
DEFAULT_SESSION_TIMEOUT_SECONDS = 5.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0

TERMINAL_STATUS_PHASES = frozenset({"completed", "cancelled", "error"})
TERMINAL_EVENT_TYPES = frozenset(
    {
        "metric",
        "error",
        "provider_catalog",
        "provider_models",
        "provider_connection_result",
        "capability_list",
        "plugin_event",
    }
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = _PACKAGE_ROOT / "reflex-runtime"
RUNTIME_SOURCE = RUNTIME_ROOT / "src"
CORE_SOURCE = _PACKAGE_ROOT / "reflex-core" / "src"

_ALLOWED_ENV_NAMES = (
    "SYSTEMROOT",
    "WINDIR",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
)


class GatewayError(RuntimeError):
    """Carry only a stable code and a safe message across the HTTP boundary."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


def is_terminal_event(envelope: dict[str, Any]) -> bool:
    """True when an envelope carries a terminal event for its request."""
    event = envelope.get("event")
    if isinstance(event, dict):
        event_type = event.get("type")
        if event_type in TERMINAL_EVENT_TYPES:
            return True
        if event_type == "status":
            return event.get("data", {}).get("phase") in TERMINAL_STATUS_PHASES
        return False
    return envelope.get("type") in TERMINAL_EVENT_TYPES


def runtime_environment() -> dict[str, str]:
    """Allowlisted environment for the child runtime; never inherits secrets."""
    env = {name: os.environ[name] for name in _ALLOWED_ENV_NAMES if name in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join((str(RUNTIME_SOURCE), str(CORE_SOURCE)))
    if os.environ.get("REFLEX_RUNTIME_DEVELOPMENT") == "0":
        env.pop("REFLEX_RUNTIME_DEVELOPMENT", None)
    else:
        env["REFLEX_RUNTIME_DEVELOPMENT"] = "1"
    return env


class _Subscription:
    """Per-request event buffer with a bounded size and a terminal flag."""

    def __init__(self) -> None:
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_BUFFERED_EVENTS)
        self.terminal = False
        self.dropped = 0

    def dispatch(self, envelope: dict[str, Any]) -> None:
        if self.terminal:
            return
        if is_terminal_event(envelope):
            self.terminal = True
        try:
            self.queue.put_nowait(envelope)
        except queue.Full:
            self.dropped += 1


class RuntimeSession:
    """One bounded ``reflex_runtime.cli`` subprocess with an event queue."""

    def __init__(self, timeout_seconds: float) -> None:
        self.timeout_seconds = timeout_seconds
        self._events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=MAX_QUEUED_EVENTS)
        self._reader_failure = threading.Event()
        self._diagnostic_overflow = threading.Event()
        self._process = subprocess.Popen(
            [sys.executable, "-m", "reflex_runtime.cli"],
            cwd=RUNTIME_ROOT,
            env=runtime_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(
            target=self._read_protocol,
            name="http-host-protocol",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_diagnostics,
            name="http-host-diagnostics",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    def events(self) -> queue.Queue[dict[str, Any]]:
        return self._events

    def poll(self) -> int | None:
        return self._process.poll()

    def send(self, command: dict[str, Any]) -> None:
        if self._process.poll() is not None or self._process.stdin is None:
            raise GatewayError("runtime_exited", "Runtime process is not running.")
        try:
            self._process.stdin.write(json.dumps(command, ensure_ascii=True) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as error:
            raise GatewayError("runtime_command_failed", "Could not send command.") from error

    def close(self) -> bool:
        graceful = False
        if self._process.poll() is None:
            try:
                self.send(
                    {
                        "version": RUNTIME_PROTOCOL_VERSION,
                        "request_id": "http-host-shutdown",
                        "type": "shutdown",
                        "payload": {},
                    }
                )
                self._process.wait(timeout=min(2.0, self.timeout_seconds))
                graceful = self._process.returncode == 0
            except (GatewayError, OSError, subprocess.TimeoutExpired):
                self._terminate_hard()
        else:
            graceful = self._process.returncode == 0
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        self._stdout_thread.join(timeout=1.0)
        self._stderr_thread.join(timeout=1.0)
        return (
            graceful
            and not self._reader_failure.is_set()
            and not self._diagnostic_overflow.is_set()
            and self._process.poll() is not None
        )

    def _terminate_hard(self) -> None:
        try:
            self._process.terminate()
            self._process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=1.0)

    def _read_protocol(self) -> None:
        stream = self._process.stdout
        if stream is None:
            self._reader_failure.set()
            return
        try:
            for line in stream:
                if not line.strip():
                    continue
                if len(line.encode("utf-8", errors="replace")) > MAX_EVENT_BYTES:
                    self._reader_failure.set()
                    return
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    self._reader_failure.set()
                    return
                try:
                    self._events.put_nowait(envelope)
                except queue.Full:
                    pass
        except (json.JSONDecodeError, ValueError):
            self._reader_failure.set()

    def _drain_diagnostics(self) -> None:
        stream = self._process.stderr
        if stream is None:
            return
        total = 0
        for line in stream:
            total += len(line.encode("utf-8", errors="replace"))
            if total > MAX_STDERR_BYTES:
                self._diagnostic_overflow.set()
                return


class SidecarGateway:
    """Route commands and events between HTTP requests and one runtime sidecar."""

    def __init__(
        self,
        *,
        session_factory: Callable[[float], RuntimeSession] = RuntimeSession,
        environment_factory: Callable[[], dict[str, str]] = runtime_environment,
        session_timeout_seconds: float = DEFAULT_SESSION_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._session_factory = session_factory
        self._environment_factory = environment_factory
        self._session_timeout_seconds = session_timeout_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._lock = threading.Lock()
        self._subscriptions: dict[str, _Subscription] = {}
        self._session: RuntimeSession | None = None
        self._dispatch_thread: threading.Thread | None = None
        self._closed = False

    def start(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            session = self._session_factory(self._session_timeout_seconds)
            self._session = session
            self._dispatch_thread = threading.Thread(
                target=self._dispatch,
                name="http-host-dispatch",
                daemon=True,
            )
            self._dispatch_thread.start()

    def is_alive(self) -> bool:
        session = self._session
        return session is not None and session.poll() is None

    def send_command(
        self,
        command_type: str,
        payload: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
    ) -> str:
        session = self._session
        if session is None:
            raise GatewayError("runtime_unavailable", "Runtime is not started.")
        request_id = request_id or new_request_id()
        session.send(
            {
                "version": RUNTIME_PROTOCOL_VERSION,
                "request_id": request_id,
                "type": command_type,
                "payload": dict(payload or {}),
            }
        )
        return request_id

    def subscribe(self, request_id: str) -> _Subscription:
        subscription = _Subscription()
        with self._lock:
            self._subscriptions[request_id] = subscription
        return subscription

    def unsubscribe(self, request_id: str) -> None:
        with self._lock:
            self._subscriptions.pop(request_id, None)

    def cancel(self, request_id: str) -> None:
        self.send_command("cancel", request_id=request_id)

    def close(self) -> bool:
        with self._lock:
            if self._closed:
                return True
            self._closed = True
            session = self._session
            subscriptions = dict(self._subscriptions)
            self._subscriptions.clear()
        for request_id in subscriptions:
            try:
                self.cancel(request_id)
            except GatewayError:
                pass
        if session is not None:
            return bool(session.close())
        return True

    def _dispatch(self) -> None:
        session = self._session
        if session is None:
            return
        events = session.events()
        while True:
            try:
                envelope = events.get(timeout=0.2)
            except queue.Empty:
                if session.poll() is not None and events.empty():
                    return
                continue
            request_id = envelope.get("request_id")
            if not isinstance(request_id, str):
                continue
            with self._lock:
                subscription = self._subscriptions.get(request_id)
            if subscription is not None:
                subscription.dispatch(envelope)
