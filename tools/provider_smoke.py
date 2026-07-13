"""Redacted smoke checks for the Reflex Runtime NDJSON provider protocol."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_CANCEL_AFTER_MS = 250
FIXTURE_SECRET = "fixture-smoke-private-credential"
PROVIDER_ID_PATTERN = re.compile(r"^[a-z0-9_.-]{1,64}$")
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
OUTPUT_FIELDS = (
    "operation",
    "provider_id",
    "model_id",
    "classification",
    "first_status_ms",
    "first_chunk_ms",
    "total_ms",
    "chunk_count",
    "cancel_latency_ms",
    "error_code",
)


class SmokeFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code if ERROR_CODE_PATTERN.fullmatch(code) else "smoke_failed"
        super().__init__(self.code)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SmokeFailure("invalid_arguments")


@dataclass(frozen=True)
class ProviderSelection:
    provider_id: str
    model_id: str


def _record(
    operation: str,
    provider_id: str,
    model_id: str,
    classification: str,
    *,
    first_status_ms: int | None = None,
    first_chunk_ms: int | None = None,
    total_ms: int | None = None,
    chunk_count: int = 0,
    cancel_latency_ms: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    value = {
        "operation": operation,
        "provider_id": provider_id if PROVIDER_ID_PATTERN.fullmatch(provider_id) else "unknown",
        "model_id": model_id if MODEL_ID_PATTERN.fullmatch(model_id) else "unknown",
        "classification": classification,
        "first_status_ms": first_status_ms,
        "first_chunk_ms": first_chunk_ms,
        "total_ms": total_ms,
        "chunk_count": chunk_count,
        "cancel_latency_ms": cancel_latency_ms,
        "error_code": error_code if error_code and ERROR_CODE_PATTERN.fullmatch(error_code) else None,
    }
    return {field: value[field] for field in OUTPUT_FIELDS}


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=True, separators=(",", ":")), flush=True)


class RuntimeProcess:
    def __init__(self, command: list[str], *, cwd: Path) -> None:
        self._events: queue.Queue[dict[str, Any] | SmokeFailure] = queue.Queue()
        self._process = subprocess.Popen(
            command,
            cwd=cwd,
            env=_safe_process_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    self._events.put(SmokeFailure("invalid_runtime_output"))
                    continue
                if not isinstance(value, dict):
                    self._events.put(SmokeFailure("invalid_runtime_output"))
                    continue
                self._events.put(value)
        finally:
            self._events.put(SmokeFailure("runtime_closed"))

    def send(self, request_id: str, command_type: str, payload: dict[str, Any]) -> None:
        if self._process.poll() is not None or self._process.stdin is None:
            raise SmokeFailure("runtime_closed")
        command = {
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "type": command_type,
            "payload": payload,
        }
        try:
            self._process.stdin.write(json.dumps(command, ensure_ascii=False) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise SmokeFailure("runtime_closed") from exc

    def receive(self, request_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SmokeFailure("smoke_timeout")
            try:
                value = self._events.get(timeout=min(remaining, 0.2))
            except queue.Empty:
                if self._process.poll() is not None:
                    raise SmokeFailure("runtime_closed")
                continue
            if isinstance(value, SmokeFailure):
                raise value
            if value.get("request_id") == request_id:
                return value

    def receive_optional(self, request_id: str, timeout: float) -> dict[str, Any] | None:
        try:
            return self.receive(request_id, timeout)
        except SmokeFailure as failure:
            if failure.code == "smoke_timeout":
                return None
            raise

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                self.send("smoke-shutdown", "shutdown", {})
                self._process.wait(timeout=2)
            except (SmokeFailure, subprocess.TimeoutExpired):
                self._process.kill()
                self._process.wait(timeout=2)


def _safe_process_environment() -> dict[str, str]:
    blocked_fragments = ("KEY", "TOKEN", "SECRET", "CREDENTIAL", "AUTH", "ENDPOINT")
    return {
        name: value
        for name, value in os.environ.items()
        if not any(fragment in name.upper() for fragment in blocked_fragments)
        and name.upper() != "REFLEX_RUNTIME_DEVELOPMENT"
    }


def _command_for(args: argparse.Namespace, root: Path) -> list[str]:
    if args.fixture_runtime:
        fixture = Path(args.fixture_runtime).resolve()
        if not fixture.is_file():
            raise SmokeFailure("fixture_unavailable")
        return [sys.executable, str(fixture)]
    runtime = Path(args.runtime).resolve() if args.runtime else (
        root / "apps" / "tauri-host" / "src-tauri" / "resources" / "runtime" / "reflex-runtime.exe"
    )
    if os.name != "nt":
        raise SmokeFailure("credential_store_unavailable")
    if not runtime.is_file():
        raise SmokeFailure("runtime_unavailable")
    return [str(runtime)]


def _list_catalog(runtime: RuntimeProcess, timeout: float) -> list[dict[str, Any]]:
    request_id = "smoke-list-providers"
    runtime.send(request_id, "list_providers", {})
    envelope = runtime.receive(request_id, timeout)
    event = envelope.get("event")
    if isinstance(event, dict) and event.get("type") == "error":
        code = _safe_error_code(event)
        raise SmokeFailure(
            "runtime_contract_outdated" if code == "protocol_error" else code
        )
    if set(envelope) != {"version", "request_id", "type", "providers"}:
        raise SmokeFailure("invalid_provider_catalog")
    if envelope.get("version") != PROTOCOL_VERSION or envelope.get("type") != "provider_catalog":
        raise SmokeFailure("invalid_provider_catalog")
    providers = envelope.get("providers")
    if not isinstance(providers, list) or not providers or len(providers) > 64:
        raise SmokeFailure("invalid_provider_catalog")
    required_fields = {
        "id", "name", "models", "default_model", "release_status", "session_configured"
    }
    trusted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for provider in providers:
        if not isinstance(provider, dict) or set(provider) != required_fields:
            raise SmokeFailure("invalid_provider_catalog")
        provider_id = provider.get("id")
        models = provider.get("models")
        default_model = provider.get("default_model")
        if (
            not isinstance(provider_id, str)
            or not PROVIDER_ID_PATTERN.fullmatch(provider_id)
            or provider_id in seen
            or not isinstance(models, list)
            or not 1 <= len(models) <= 256
            or not all(isinstance(model, str) and MODEL_ID_PATTERN.fullmatch(model) for model in models)
            or len(set(models)) != len(models)
            or default_model not in models
            or provider.get("release_status") not in {"supported", "experimental"}
            or not isinstance(provider.get("session_configured"), bool)
        ):
            raise SmokeFailure("invalid_provider_catalog")
        seen.add(provider_id)
        trusted.append(provider)
    if [provider["id"] for provider in trusted] != sorted(seen):
        raise SmokeFailure("invalid_provider_catalog")
    return trusted


def _select_provider(
    providers: list[dict[str, Any]], provider_id: str | None, model_id: str | None
) -> ProviderSelection:
    if provider_id is None:
        provider = next(
            (item for item in providers if item["release_status"] == "supported"),
            providers[0],
        )
    else:
        provider = next((item for item in providers if item["id"] == provider_id), None)
        if provider is None:
            raise SmokeFailure("provider_not_trusted")
    selected_model = model_id or provider["default_model"]
    if selected_model not in provider["models"]:
        raise SmokeFailure("model_not_trusted")
    return ProviderSelection(provider["id"], selected_model)


def _read_windows_credential(provider_id: str) -> str:
    if os.name != "nt":
        raise SmokeFailure("credential_store_unavailable")

    from ctypes import wintypes

    class Credential(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    credential_pointer = ctypes.POINTER(Credential)()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(Credential)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    target = f"provider:{provider_id}.com.reflex-next.provider"
    if not advapi32.CredReadW(target, 1, 0, ctypes.byref(credential_pointer)):
        error = ctypes.get_last_error()
        raise SmokeFailure("credential_not_configured" if error == 1168 else "credential_store_unavailable")
    try:
        credential = credential_pointer.contents
        size = int(credential.CredentialBlobSize)
        if size <= 0 or size > 32_768 or size % 2:
            raise SmokeFailure("credential_store_unavailable")
        secret = ctypes.string_at(credential.CredentialBlob, size).decode("utf-16-le")
        if not secret.strip() or len(secret) > 16_384:
            raise SmokeFailure("credential_store_unavailable")
        return secret
    except (UnicodeDecodeError, ValueError) as exc:
        raise SmokeFailure("credential_store_unavailable") from exc
    finally:
        advapi32.CredFree(credential_pointer)


def _configure(
    runtime: RuntimeProcess,
    selection: ProviderSelection,
    timeout: float,
    fixture: bool,
) -> None:
    secret = FIXTURE_SECRET if fixture else _read_windows_credential(selection.provider_id)
    request_id = "smoke-configure-provider"
    runtime.send(
        request_id,
        "configure_provider",
        {
            "provider_id": selection.provider_id,
            "secret": secret,
            "config": {
                "model": selection.model_id,
                "tls_verify": True,
                "ca_bundle_path": None,
            },
        },
    )
    envelope = runtime.receive(request_id, timeout)
    event = envelope.get("event")
    if not isinstance(event, dict):
        raise SmokeFailure("provider_configuration_failed")
    if event.get("type") == "error":
        raise SmokeFailure(_safe_error_code(event))
    if event.get("type") != "status" or event.get("data", {}).get("phase") != "completed":
        raise SmokeFailure("provider_configuration_failed")


def _safe_error_code(event: dict[str, Any]) -> str:
    data = event.get("data")
    code = data.get("code") if isinstance(data, dict) else None
    return code if isinstance(code, str) and ERROR_CODE_PATTERN.fullmatch(code) else "runtime_error"


def _run_optimize(
    runtime: RuntimeProcess,
    selection: ProviderSelection,
    operation: str,
    timeout: float,
    cancel_after_ms: int,
) -> dict[str, Any]:
    request_id = f"smoke-{operation}"
    started = time.monotonic_ns()
    cancel_sent: list[int | None] = [None]
    timer: threading.Timer | None = None
    runtime.send(
        request_id,
        "optimize",
        {
            "text": "Please rewrite this sentence more clearly: The meeting starts at three.",
            "mode": "content",
            "style": "balanced",
            "scene": "general",
            "scene_policy": "manual",
            "provider": selection.provider_id,
            "model": selection.model_id,
            "stream": True,
            "metadata": {"smoke_operation": operation},
        },
    )
    if operation == "cancel":
        def cancel() -> None:
            cancel_sent[0] = time.monotonic_ns()
            try:
                runtime.send(request_id, "cancel", {})
            except SmokeFailure:
                pass

        timer = threading.Timer(cancel_after_ms / 1000.0, cancel)
        timer.daemon = True
        timer.start()

    first_status_ms = None
    first_chunk_ms = None
    chunk_count = 0
    classification = "tool_error"
    error_code = None
    terminal_ns = None
    try:
        while terminal_ns is None:
            envelope = runtime.receive(request_id, timeout)
            event = envelope.get("event")
            if not isinstance(event, dict) or not isinstance(event.get("data"), dict):
                raise SmokeFailure("invalid_runtime_output")
            event_type = event.get("type")
            now = time.monotonic_ns()
            if event_type == "status":
                if first_status_ms is None:
                    first_status_ms = _elapsed_ms(started, now)
                phase = event["data"].get("phase")
                if phase == "cancelled":
                    classification = "cancelled"
                    terminal_ns = now
            elif event_type == "chunk":
                chunk_count += 1
                if first_chunk_ms is None:
                    first_chunk_ms = _elapsed_ms(started, now)
            elif event_type == "done":
                classification = "success"
                terminal_ns = now
            elif event_type == "error":
                classification = "error"
                error_code = _safe_error_code(event)
                terminal_ns = now
        if operation == "cancel":
            if classification != "cancelled" or cancel_sent[0] is None:
                raise SmokeFailure("cancel_not_observed")
            late = runtime.receive_optional(request_id, 0.2)
            if late and late.get("event", {}).get("type") == "done":
                raise SmokeFailure("late_completion_after_cancel")
        elif classification != "success":
            if classification != "error":
                raise SmokeFailure("stream_not_completed")
    finally:
        if timer is not None:
            timer.cancel()

    assert terminal_ns is not None
    cancel_latency = (
        _elapsed_ms(cancel_sent[0], terminal_ns)
        if cancel_sent[0] is not None and classification == "cancelled"
        else None
    )
    return _record(
        operation,
        selection.provider_id,
        selection.model_id,
        classification,
        first_status_ms=first_status_ms,
        first_chunk_ms=first_chunk_ms,
        total_ms=_elapsed_ms(started, terminal_ns),
        chunk_count=chunk_count,
        cancel_latency_ms=cancel_latency,
        error_code=error_code,
    )


def _elapsed_ms(started_ns: int, ended_ns: int) -> int:
    return max(0, round((ended_ns - started_ns) / 1_000_000))


def _parser() -> SafeArgumentParser:
    parser = SafeArgumentParser(description="Run redacted Provider smoke checks.")
    parser.add_argument("--operation", choices=("list", "stream", "cancel", "all"), default="all")
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--runtime", help="Path to the packaged Reflex Runtime executable.")
    parser.add_argument("--fixture-runtime", help=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--cancel-after-ms", type=int, default=DEFAULT_CANCEL_AFTER_MS)
    return parser


def main(argv: list[str] | None = None) -> int:
    provider_id = "unknown"
    model_id = "unknown"
    operation = "startup"
    runtime: RuntimeProcess | None = None
    try:
        args = _parser().parse_args(argv)
        operation = args.operation
        if not 1.0 <= args.timeout_seconds <= 120.0 or not 10 <= args.cancel_after_ms <= 10_000:
            raise SmokeFailure("invalid_arguments")
        if args.provider and not PROVIDER_ID_PATTERN.fullmatch(args.provider):
            raise SmokeFailure("invalid_arguments")
        if args.model and not MODEL_ID_PATTERN.fullmatch(args.model):
            raise SmokeFailure("invalid_arguments")
        root = Path(__file__).resolve().parents[1]
        runtime = RuntimeProcess(_command_for(args, root), cwd=root)
        providers = _list_catalog(runtime, args.timeout_seconds)
        selection = _select_provider(providers, args.provider, args.model)
        provider_id, model_id = selection.provider_id, selection.model_id
        _emit(_record("list", provider_id, model_id, "catalog_ok"))
        if args.operation == "list":
            return 0
        _configure(runtime, selection, args.timeout_seconds, bool(args.fixture_runtime))
        operations = ("stream", "cancel") if args.operation == "all" else (args.operation,)
        for selected_operation in operations:
            record = _run_optimize(
                runtime,
                selection,
                selected_operation,
                args.timeout_seconds,
                args.cancel_after_ms,
            )
            _emit(record)
            if record["classification"] == "error":
                return 1
        return 0
    except SmokeFailure as failure:
        _emit(_record(operation, provider_id, model_id, "tool_error", error_code=failure.code))
        return 2
    except Exception:
        _emit(_record(operation, provider_id, model_id, "tool_error", error_code="unexpected_failure"))
        return 2
    finally:
        if runtime is not None:
            runtime.close()


if __name__ == "__main__":
    raise SystemExit(main())
