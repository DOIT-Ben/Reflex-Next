"""Runtime context for coordinating command handling and request cancellation."""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import fields
from pathlib import Path
from typing import Any, TextIO

from reflex_core import (
    CancellationToken,
    EventEnvelope,
    OptimizeRequest,
    StatusPhase,
)
from reflex_core.events import error_event, status_event
from reflex_core.scene.detectors import RuleSceneDetector
from reflex_core.template import TemplatePackResolver
from reflex_core.usecases import OptimizeUseCase
from reflex_core.safety import redact_sensitive

from .mock_provider import MockProvider
from .plugin_manager import PluginManager
from .protocol import CommandEnvelope, ProtocolError
from .provider_errors import ProviderRuntimeError, provider_unconfigured
from .provider_registry import ProviderRegistry


class RuntimeContext:
    def __init__(
        self,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        development: bool | None = None,
        template_resolver: Any | None = None,
    ) -> None:
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._tokens: dict[str, CancellationToken] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._development = (
            os.environ.get("REFLEX_RUNTIME_DEVELOPMENT") == "1"
            if development is None
            else development
        )
        development_modules = ("reflex_provider_minimax",) if self._development else ()
        discovery = PluginManager(
            development_modules=development_modules
        ).discover_provider_factories()
        self._registry = ProviderRegistry(discovery.factories)
        self._mock_provider = MockProvider() if self._development else None
        self._scene_detector = RuleSceneDetector()
        self._template_resolver = template_resolver or _builtin_template_resolver()

    def handle(self, command: CommandEnvelope) -> bool:
        if command.type == "ping":
            self.emit_status(command.request_id, StatusPhase.COMPLETED, "pong")
            return True
        if command.type == "shutdown":
            self.cancel_all()
            self.emit_status(command.request_id, StatusPhase.COMPLETED, "shutdown")
            return False
        if command.type == "cancel":
            self.cancel(command.request_id)
            return True
        if command.type == "configure_provider":
            self.configure_provider(command)
            return True
        if command.type == "optimize":
            self.start_optimize(command)
            return True
        raise ProtocolError("unsupported command type")

    def configure_provider(self, command: CommandEnvelope) -> None:
        try:
            self._registry.configure(
                command.payload["provider_id"],
                command.payload["secret"],
                command.payload["config"],
            )
        except ProviderRuntimeError as error:
            self.emit_provider_error(command.request_id, error)
            return
        self.emit_status(command.request_id, StatusPhase.COMPLETED, "provider_configured")

    def start_optimize(self, command: CommandEnvelope) -> None:
        token = CancellationToken()
        with self._lock:
            existing = self._tokens.get(command.request_id)
            if existing is not None:
                existing.cancel()
            self._tokens[command.request_id] = token

        thread = threading.Thread(
            target=self._run_optimize,
            args=(command, token),
            daemon=True,
        )
        with self._lock:
            self._threads[command.request_id] = thread
        thread.start()

    def cancel(self, request_id: str) -> None:
        with self._lock:
            token = self._tokens.get(request_id)
        if token is not None:
            token.cancel()

    def cancel_all(self) -> None:
        with self._lock:
            tokens = list(self._tokens.values())
        for token in tokens:
            token.cancel()

    def emit_error(
        self,
        request_id: str,
        code: str,
        message: str,
        action: str | None = None,
        *,
        recoverable: bool = True,
    ) -> None:
        self.emit(
            EventEnvelope(
                request_id,
                error_event(
                    code,
                    redact_sensitive(message),
                    recoverable=recoverable,
                    action=action,
                ),
            )
        )

    def emit_provider_error(self, request_id: str, error: ProviderRuntimeError) -> None:
        self.emit_error(
            request_id,
            error.code,
            error.safe_message,
            action=error.action,
            recoverable=error.recoverable,
        )

    def emit_status(self, request_id: str, phase: StatusPhase, message: str) -> None:
        self.emit(EventEnvelope(request_id, status_event(phase, message)))

    def emit(self, envelope: EventEnvelope) -> None:
        with self._lock:
            print(json.dumps(envelope.to_dict(), ensure_ascii=False), file=self._stdout, flush=True)

    def diagnostic(self, message: str) -> None:
        print(redact_sensitive(message), file=self._stderr, flush=True)

    def _run_optimize(self, command: CommandEnvelope, token: CancellationToken) -> None:
        try:
            request = self._request_from_payload(command.payload)
            provider = self._resolve_provider(request)
            use_case = OptimizeUseCase(
                scene_detector=self._scene_detector,
                template_resolver=self._template_resolver,
                provider=provider,
            )
            for envelope in use_case.optimize(
                request,
                request_id=command.request_id,
                cancellation=token,
            ):
                self.emit(envelope)
        except ProviderRuntimeError as error:
            self.emit_provider_error(command.request_id, error)
        except Exception as exc:
            self.emit_error(command.request_id, "runtime_error", "Runtime request failed.", action="retry")
            self.diagnostic(
                f"runtime_error request_id={command.request_id} category={type(exc).__name__}"
            )
        finally:
            with self._lock:
                current = self._tokens.get(command.request_id)
                if current is token:
                    self._tokens.pop(command.request_id, None)
                thread = self._threads.get(command.request_id)
                if thread is threading.current_thread():
                    self._threads.pop(command.request_id, None)

    def _resolve_provider(self, request: OptimizeRequest):
        provider_id = request.provider
        if provider_id == "mock" and self._mock_provider is not None:
            if request.model not in {None, self._mock_provider.model}:
                raise provider_unconfigured()
            return self._mock_provider
        if provider_id is None:
            raise provider_unconfigured()
        return self._registry.resolve(provider_id, request.model)

    @staticmethod
    def _request_from_payload(payload: dict[str, Any]) -> OptimizeRequest:
        allowed = {field.name for field in fields(OptimizeRequest)}
        data = {key: value for key, value in payload.items() if key in allowed}
        return OptimizeRequest(**data)


def _builtin_template_resolver() -> TemplatePackResolver:
    repository_root = Path(__file__).resolve().parents[4]
    return TemplatePackResolver.from_directory(
        repository_root / "template-packs" / "builtin"
    )
