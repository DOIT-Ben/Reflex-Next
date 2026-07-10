"""Runtime context for coordinating command handling and request cancellation."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import fields
from pathlib import Path
from typing import Any, TextIO

from reflex_core import (
    CancellationToken,
    EventEnvelope,
    OperationCancelled,
    OptimizeRequest,
    StatusPhase,
)
from reflex_core.events import error_event, status_event
from reflex_core.scene.detectors import RuleSceneDetector
from reflex_core.template import TemplatePackResolver
from reflex_core.usecases import OptimizeUseCase
from reflex_core.safety import redact_sensitive

from .capability_registry import CapabilityDenied, CapabilityRegistry
from .mock_provider import MockProvider
from .plugin_manager import PluginManager
from .plugin_contracts import (
    CapabilityListEnvelope,
    PluginDescriptor,
    PluginEventEnvelope,
)
from .protocol import CommandEnvelope, ProtocolError
from .provider_errors import ProviderRuntimeError, provider_unconfigured
from .provider_registry import ProviderRegistry
from .task_registry import DuplicateRequestId, TaskRegistry


class RuntimeContext:
    def __init__(
        self,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        *,
        development: bool | None = None,
        template_resolver: Any | None = None,
        capability_registry: CapabilityRegistry | None = None,
        capability_descriptors: tuple[PluginDescriptor, ...] | None = None,
        services: Any | None = None,
        thread_factory: Any = threading.Thread,
    ) -> None:
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._tasks = TaskRegistry()
        self._thread_factory = thread_factory
        self._development = (
            os.environ.get("REFLEX_RUNTIME_DEVELOPMENT") == "1"
            if development is None
            else development
        )
        development_modules = ("reflex_provider_minimax",) if self._development else ()
        plugin_manager = PluginManager(
            development_modules=development_modules
        )
        self._plugin_manager: PluginManager | None = None
        discovery = plugin_manager.discover_provider_factories()
        self._registry = ProviderRegistry(discovery.factories)
        if capability_registry is None:
            self._plugin_manager = plugin_manager
            capability_discovery = plugin_manager.discover_capabilities()
            discovered_descriptors = {
                descriptor.plugin_id: descriptor
                for descriptor in capability_discovery.descriptors
            }
            active_plugins = [
                (discovered_descriptors[plugin_id], instance)
                for plugin_id, instance in capability_discovery.plugins.items()
            ]
            history_descriptor = discovered_descriptors.get("history-sqlite")
            capability_registry = CapabilityRegistry(
                active_plugins,
                enabled_plugins={
                    descriptor.plugin_id
                    for descriptor in capability_discovery.descriptors
                    if descriptor.enabled
                },
                history_unavailable=(
                    history_descriptor is not None
                    and history_descriptor.state == "unavailable"
                ),
                known_descriptors=capability_discovery.descriptors,
            )
            capability_descriptors = capability_discovery.descriptors
        self._capabilities = capability_registry
        self._capability_descriptors = tuple(capability_descriptors or ())
        self._services = {} if services is None else services
        self._mock_provider = MockProvider() if self._development else None
        self._scene_detector = RuleSceneDetector()
        self._template_resolver = template_resolver or _builtin_template_resolver()

    def __repr__(self) -> str:
        return "RuntimeContext(protocol=1)"

    def handle(self, command: CommandEnvelope) -> bool:
        if command.type == "cancel":
            self.cancel(command.request_id)
            return True
        if command.type in {"plugin_call", "plugin_admin_call"}:
            self.start_plugin_call(command, admin=command.type == "plugin_admin_call")
            return True
        if command.type == "optimize":
            self.start_optimize(command)
            return True
        return self._handle_synchronous(command)

    def _handle_synchronous(self, command: CommandEnvelope) -> bool:
        try:
            token = self._tasks.register(command.request_id)
        except DuplicateRequestId:
            self._diagnose_duplicate(command)
            return True
        try:
            if command.type == "ping":
                self.emit_status(command.request_id, StatusPhase.COMPLETED, "pong")
                return True
            if command.type == "shutdown":
                self.cancel_all()
                self.emit_status(command.request_id, StatusPhase.COMPLETED, "shutdown")
                return False
            if command.type == "configure_provider":
                self.configure_provider(command)
                return True
            if command.type == "list_plugins":
                self.emit_runtime(
                    CapabilityListEnvelope(command.request_id, self._listed_descriptors())
                )
                return True
            if command.type == "configure_plugin":
                self.configure_plugin(command)
                return True
            if command.type == "configure_history_keys":
                self.configure_history_keys(command)
                return True
            if command.type == "configure_history_policy":
                self.configure_history_policy(command)
                return True
            raise ProtocolError("unsupported command type")
        finally:
            self._tasks.cleanup(command.request_id, token)

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

    def configure_plugin(self, command: CommandEnvelope) -> None:
        try:
            if self._plugin_manager is None:
                self._capabilities.configure_plugin(
                    command.payload["plugin_id"], command.payload["enabled"]
                )
            else:
                self._plugin_manager.configure_enabled_plugin(
                    command.payload["plugin_id"], command.payload["enabled"]
                )
                discovery = self._plugin_manager.discover_capabilities()
                descriptor_by_id = {
                    descriptor.plugin_id: descriptor
                    for descriptor in discovery.descriptors
                }
                history_descriptor = descriptor_by_id.get("history-sqlite")
                self._capabilities.replace_plugins(
                    [
                        (descriptor_by_id[plugin_id], instance)
                        for plugin_id, instance in discovery.plugins.items()
                    ],
                    enabled_plugins={
                        descriptor.plugin_id
                        for descriptor in discovery.descriptors
                        if descriptor.enabled
                    },
                    history_unavailable=(
                        history_descriptor is not None
                        and history_descriptor.state == "unavailable"
                    ),
                    known_descriptors=discovery.descriptors,
                )
                self._capability_descriptors = discovery.descriptors
        except (CapabilityDenied, ValueError) as error:
            code = getattr(error, "code", "plugin_configuration_denied")
            self.emit_error(command.request_id, code, "Plugin configuration failed.")
            return
        self.emit_status(command.request_id, StatusPhase.COMPLETED, "plugin_configured")

    def configure_history_keys(self, command: CommandEnvelope) -> None:
        try:
            self._capabilities.configure_history_keys(command.payload["keys"])
        except CapabilityDenied as error:
            self.emit_error(command.request_id, error.code, "History keys failed.")
            return
        self.emit_status(command.request_id, StatusPhase.COMPLETED, "history_keys_configured")

    def configure_history_policy(self, command: CommandEnvelope) -> None:
        try:
            self._capabilities.configure_history_policy(**command.payload)
        except CapabilityDenied as error:
            self.emit_error(command.request_id, error.code, "History policy failed.")
            return
        self.emit_status(command.request_id, StatusPhase.COMPLETED, "history_policy_configured")

    def start_optimize(self, command: CommandEnvelope) -> None:
        try:
            token = self._tasks.register(command.request_id)
        except DuplicateRequestId:
            self._diagnose_duplicate(command)
            return

        try:
            thread = self._thread_factory(
                target=self._run_optimize,
                args=(command, token),
                daemon=True,
            )
            self._start_thread(command.request_id, token, thread)
        except Exception as exc:
            self._tasks.cleanup(command.request_id, token)
            self.emit_error(
                command.request_id,
                "runtime_error",
                "Runtime request failed.",
                action="retry",
            )
            self.diagnostic(
                f"thread_start_failed request_id={command.request_id} category={type(exc).__name__}"
            )

    def start_plugin_call(self, command: CommandEnvelope, *, admin: bool) -> None:
        try:
            token = self._tasks.register(command.request_id)
        except DuplicateRequestId:
            self._diagnose_duplicate(command)
            return
        try:
            thread = self._thread_factory(
                target=self._run_plugin_call,
                args=(command, token, admin),
                daemon=True,
            )
            self._start_thread(command.request_id, token, thread)
        except Exception as exc:
            self._tasks.cleanup(command.request_id, token)
            self.emit_plugin_error(command, "thread_start_failed")
            self.diagnostic(
                f"thread_start_failed request_id={command.request_id} category={type(exc).__name__}"
            )

    def _start_thread(
        self, request_id: str, token: CancellationToken, thread: threading.Thread
    ) -> None:
        with self._lock:
            self._threads[request_id] = thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                if self._threads.get(request_id) is thread:
                    self._threads.pop(request_id, None)
            self._tasks.cleanup(request_id, token)
            raise

    def cancel(self, request_id: str) -> None:
        self._tasks.cancel(request_id)

    def cancel_all(self) -> None:
        self._tasks.cancel_all()

    def close(self, timeout: float = 1.0) -> None:
        self.cancel_all()
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            threads = tuple(self._threads.values())
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))

    def has_active_tasks(self) -> bool:
        with self._lock:
            request_ids = tuple(self._threads)
        return any(self._tasks.is_active(request_id) for request_id in request_ids)

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

    def emit_runtime(
        self, envelope: CapabilityListEnvelope | PluginEventEnvelope
    ) -> None:
        with self._lock:
            print(
                json.dumps(envelope.to_dict(), ensure_ascii=False),
                file=self._stdout,
                flush=True,
            )

    def emit_plugin_error(self, command: CommandEnvelope, code: str) -> None:
        self.emit_runtime(
            PluginEventEnvelope(
                request_id=command.request_id,
                plugin_id=command.payload["plugin_id"],
                operation=command.payload["operation"],
                status="error",
                code=code,
            )
        )

    def diagnostic(self, message: str) -> None:
        print(redact_sensitive(message), file=self._stderr, flush=True)

    def _diagnose_duplicate(self, command: CommandEnvelope) -> None:
        self.diagnostic(
            "duplicate_request_id "
            f"request_id={command.request_id} command_type={command.type}"
        )

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
            self._tasks.cleanup(command.request_id, token)
            with self._lock:
                thread = self._threads.get(command.request_id)
                if thread is threading.current_thread():
                    self._threads.pop(command.request_id, None)

    def _run_plugin_call(
        self,
        command: CommandEnvelope,
        token: CancellationToken,
        admin: bool,
    ) -> None:
        plugin_id = command.payload["plugin_id"]
        operation = command.payload["operation"]
        try:
            self.emit_runtime(
                PluginEventEnvelope(
                    command.request_id, plugin_id, operation, "started"
                )
            )
            invoke = (
                self._capabilities.invoke_admin
                if admin
                else self._capabilities.invoke_public
            )
            result = invoke(
                plugin_id,
                operation,
                command.payload["input"],
                self._services,
                token,
            )
            self._emit_plugin_result(command, token, result)
        except OperationCancelled:
            self._emit_plugin_status(command, "cancelled", {})
        except CapabilityDenied as error:
            self.emit_plugin_error(command, error.code)
        except Exception as exc:
            if token.is_cancelled:
                self._emit_plugin_status(command, "cancelled", {})
            else:
                self.emit_plugin_error(command, "plugin_failed")
                self.diagnostic(
                    f"plugin_failed request_id={command.request_id} category={type(exc).__name__}"
                )
        finally:
            self._tasks.cleanup(command.request_id, token)
            with self._lock:
                if self._threads.get(command.request_id) is threading.current_thread():
                    self._threads.pop(command.request_id, None)

    def _emit_plugin_result(
        self,
        command: CommandEnvelope,
        token: CancellationToken,
        result: Any,
    ) -> None:
        if token.is_cancelled:
            self._emit_plugin_status(command, "cancelled", {})
            return
        if isinstance(result, dict):
            self._emit_plugin_status(command, "result", result)
            return
        if not isinstance(result, Iterable) or isinstance(result, (str, bytes)):
            raise CapabilityDenied("plugin_invalid_result")

        terminal = False
        for item in result:
            if token.is_cancelled:
                self._emit_plugin_status(command, "cancelled", {})
                return
            if not isinstance(item, dict):
                raise CapabilityDenied("plugin_invalid_result")
            status = item.get("status")
            if status == "error":
                if set(item) != {"status", "code"}:
                    raise CapabilityDenied("plugin_invalid_result")
                self.emit_runtime(
                    PluginEventEnvelope(
                        command.request_id,
                        command.payload["plugin_id"],
                        command.payload["operation"],
                        "error",
                        code=item.get("code"),
                    )
                )
                return
            if set(item) != {"status", "data"} or status not in {
                "chunk",
                "progress",
                "result",
            }:
                raise CapabilityDenied("plugin_invalid_result")
            data = item.get("data")
            if not isinstance(data, dict):
                raise CapabilityDenied("plugin_invalid_result")
            self._emit_plugin_status(command, status, data)
            terminal = status == "result"
            if terminal:
                return
        if not terminal:
            self._emit_plugin_status(command, "result", {})

    def _emit_plugin_status(
        self, command: CommandEnvelope, status: str, data: dict[str, Any]
    ) -> None:
        self.emit_runtime(
            PluginEventEnvelope(
                command.request_id,
                command.payload["plugin_id"],
                command.payload["operation"],
                status,
                data=data,
            )
        )

    def _listed_descriptors(self) -> tuple[PluginDescriptor, ...]:
        active = {
            descriptor.plugin_id: descriptor
            for descriptor in self._capabilities.descriptors()
        }
        listed = [
            active.pop(descriptor.plugin_id, descriptor)
            for descriptor in self._capability_descriptors
        ]
        listed.extend(active[plugin_id] for plugin_id in sorted(active))
        return tuple(listed)

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
