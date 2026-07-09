"""Runtime context for coordinating command handling and request cancellation."""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import fields
from typing import Any, TextIO

from reflex_core import (
    CancellationToken,
    EventEnvelope,
    OptimizeRequest,
    StatusPhase,
)
from reflex_core.events import error_event, status_event
from reflex_core.scene.detectors import RuleSceneDetector
from reflex_core.template.resolver import PassthroughTemplateResolver
from reflex_core.usecases import OptimizeUseCase
from reflex_core.safety import redact_sensitive

from .mock_provider import MockProvider
from .protocol import CommandEnvelope, ProtocolError


class RuntimeContext:
    def __init__(self, stdout: TextIO | None = None, stderr: TextIO | None = None) -> None:
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._tokens: dict[str, CancellationToken] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._use_case = OptimizeUseCase(
            scene_detector=RuleSceneDetector(),
            template_resolver=PassthroughTemplateResolver(),
            provider=MockProvider(),
        )

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
        if command.type == "optimize":
            self.start_optimize(command)
            return True
        raise ProtocolError("unsupported command type")

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

    def emit_error(self, request_id: str, code: str, message: str, action: str | None = None) -> None:
        self.emit(
            EventEnvelope(
                request_id,
                error_event(code, redact_sensitive(message), recoverable=True, action=action),
            )
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
            for envelope in self._use_case.optimize(
                request,
                request_id=command.request_id,
                cancellation=token,
            ):
                self.emit(envelope)
        except Exception as exc:
            self.emit_error(command.request_id, "runtime_error", "Runtime request failed.", action="retry")
            self.diagnostic(f"runtime_error request_id={command.request_id}: {exc}")
        finally:
            with self._lock:
                current = self._tokens.get(command.request_id)
                if current is token:
                    self._tokens.pop(command.request_id, None)
                thread = self._threads.get(command.request_id)
                if thread is threading.current_thread():
                    self._threads.pop(command.request_id, None)

    @staticmethod
    def _request_from_payload(payload: dict[str, Any]) -> OptimizeRequest:
        allowed = {field.name for field in fields(OptimizeRequest)}
        data = {key: value for key, value in payload.items() if key in allowed}
        return OptimizeRequest(**data)
