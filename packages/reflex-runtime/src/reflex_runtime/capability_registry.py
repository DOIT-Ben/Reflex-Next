"""Explicit Runtime dispatch and policy enforcement for capability plugins."""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock
from typing import Any, Iterable

from .plugin_contracts import PluginDescriptor, is_safe_id

PUBLIC_OPERATION_ALLOWLIST = {
    "history-sqlite": frozenset({"list", "detail", "rate", "backups", "scan"}),
    "translator": frozenset({"translate"}),
    "markdown-preview": frozenset({"preview"}),
}
ADMIN_OPERATION_ALLOWLIST = {
    "history-sqlite": frozenset(
        {"delete", "clear", "export", "repair", "restore", "rotate"}
    ),
    "markdown-preview": frozenset({"export"}),
}
INTERNAL_OPERATION_ALLOWLIST = {"history-sqlite": frozenset({"save"})}
HISTORY_STATES = frozenset(
    {"absent", "read_only", "writable", "private", "unavailable"}
)
HISTORY_MUTATING_ADMIN_OPERATIONS = frozenset(
    {"delete", "clear", "repair", "restore", "rotate"}
)
OPTIONAL_PLUGIN_IDS = frozenset({"translator", "markdown-preview"})


@dataclass(frozen=True)
class HistoryPolicySnapshot:
    history_enabled: bool
    privacy_mode: bool
    history_redaction: str


class CapabilityDenied(RuntimeError):
    def __init__(self, code: str) -> None:
        if not is_safe_id(code):
            raise ValueError("invalid capability error code")
        self.code = code
        super().__init__(code)


class CapabilityRegistry:
    def __init__(
        self,
        plugins: Iterable[tuple[PluginDescriptor, Any]] = (),
        *,
        enabled_plugins: set[str] | frozenset[str] | None = None,
        history_unavailable: bool = False,
        known_descriptors: tuple[PluginDescriptor, ...] | None = None,
    ) -> None:
        self._lock = RLock()
        self._plugins = self._validated_plugins(plugins)
        self._known_descriptors = self._validated_descriptors(
            known_descriptors
            if known_descriptors is not None
            else tuple(descriptor for descriptor, _ in self._plugins.values())
        )
        self._enabled_plugins = set(enabled_plugins or ())
        self._history_unavailable = bool(history_unavailable)
        self._history_keys: dict[str, str] = {}
        self._history_policy = HistoryPolicySnapshot(False, False, "secrets")

    @staticmethod
    def _validated_plugins(
        plugins: Iterable[tuple[PluginDescriptor, Any]],
    ) -> dict[str, tuple[PluginDescriptor, Any]]:
        validated: dict[str, tuple[PluginDescriptor, Any]] = {}
        for descriptor, instance in plugins:
            if descriptor.plugin_id in validated:
                raise ValueError("duplicate plugin id")
            if not callable(getattr(instance, "invoke", None)):
                raise ValueError("plugin must provide invoke")
            validated[descriptor.plugin_id] = (descriptor, instance)
        return validated

    @staticmethod
    def _validated_descriptors(
        descriptors: Iterable[PluginDescriptor],
    ) -> dict[str, PluginDescriptor]:
        validated: dict[str, PluginDescriptor] = {}
        for descriptor in descriptors:
            if not isinstance(descriptor, PluginDescriptor):
                raise ValueError("invalid plugin descriptor")
            if descriptor.plugin_id in validated:
                raise ValueError("duplicate plugin descriptor")
            validated[descriptor.plugin_id] = descriptor
        return validated

    @property
    def history_state(self) -> str:
        with self._lock:
            return self._history_state_unlocked()

    @property
    def history_policy(self) -> HistoryPolicySnapshot:
        with self._lock:
            return self._history_policy

    def _history_state_unlocked(self) -> str:
        if self._history_unavailable:
            return "unavailable"
        if not self._history_keys:
            return "absent"
        if "history-sqlite" not in self._plugins:
            return "unavailable"
        if not self._history_policy.history_enabled:
            return "read_only"
        if self._history_policy.privacy_mode:
            return "private"
        return "writable"

    def configure_plugin(self, plugin_id: str, enabled: bool) -> None:
        if plugin_id not in OPTIONAL_PLUGIN_IDS or not isinstance(enabled, bool):
            raise CapabilityDenied("plugin_configuration_denied")
        with self._lock:
            if enabled:
                self._enabled_plugins.add(plugin_id)
            else:
                self._enabled_plugins.discard(plugin_id)

    def configure_history_keys(self, keys: dict[str, str]) -> None:
        if not isinstance(keys, dict) or any(
            not _safe_key_version(version)
            or not isinstance(secret, str)
            or not secret
            or len(secret) > 16_384
            for version, secret in keys.items()
        ):
            with self._lock:
                self._history_unavailable = True
            raise CapabilityDenied("history_keys_invalid")
        with self._lock:
            self._history_keys = dict(keys)

    def configure_history_policy(
        self,
        *,
        history_enabled: bool,
        privacy_mode: bool,
        history_redaction: str,
    ) -> None:
        if (
            not isinstance(history_enabled, bool)
            or not isinstance(privacy_mode, bool)
            or history_redaction not in {"secrets", "none"}
        ):
            with self._lock:
                self._history_unavailable = True
            raise CapabilityDenied("history_policy_invalid")
        snapshot = HistoryPolicySnapshot(
            history_enabled, privacy_mode, history_redaction
        )
        with self._lock:
            self._history_policy = snapshot

    def replace_plugins(
        self,
        plugins: Iterable[tuple[PluginDescriptor, Any]],
        *,
        enabled_plugins: set[str] | frozenset[str],
        history_unavailable: bool,
        known_descriptors: tuple[PluginDescriptor, ...] | None = None,
    ) -> None:
        validated_plugins = self._validated_plugins(plugins)
        validated_descriptors = (
            self._validated_descriptors(known_descriptors)
            if known_descriptors is not None
            else None
        )
        with self._lock:
            self._plugins = validated_plugins
            if validated_descriptors is not None:
                self._known_descriptors = validated_descriptors
            self._enabled_plugins = set(enabled_plugins)
            self._history_unavailable = bool(history_unavailable)

    def descriptors(self) -> tuple[PluginDescriptor, ...]:
        with self._lock:
            descriptors: list[PluginDescriptor] = []
            for plugin_id, descriptor in sorted(self._known_descriptors.items()):
                if plugin_id == "history-sqlite":
                    state = self._history_state_unlocked()
                    descriptors.append(
                        replace(
                            descriptor,
                            enabled=state in {"writable", "private"},
                            state=state,
                            error_code=(
                                "plugin_unavailable"
                                if state == "unavailable"
                                else None
                            ),
                        )
                    )
                elif plugin_id in OPTIONAL_PLUGIN_IDS:
                    if plugin_id in self._plugins:
                        enabled = plugin_id in self._enabled_plugins
                        descriptors.append(
                            replace(
                                descriptor,
                                enabled=enabled,
                                state="available" if enabled else "disabled",
                                error_code=None,
                            )
                        )
                    else:
                        descriptors.append(descriptor)
                else:
                    descriptors.append(descriptor)
            return tuple(descriptors)

    def invoke_public(
        self,
        plugin_id: str,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
    ) -> Any:
        return self._invoke(
            PUBLIC_OPERATION_ALLOWLIST,
            plugin_id,
            operation,
            payload,
            services,
            cancellation,
            channel="public",
        )

    def invoke_admin(
        self,
        plugin_id: str,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
    ) -> Any:
        return self._invoke(
            ADMIN_OPERATION_ALLOWLIST,
            plugin_id,
            operation,
            payload,
            services,
            cancellation,
            channel="admin",
        )

    def invoke_internal(
        self,
        plugin_id: str,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
        *,
        trusted: bool,
    ) -> Any:
        if trusted is not True:
            raise CapabilityDenied("trusted_call_required")
        return self._invoke(
            INTERNAL_OPERATION_ALLOWLIST,
            plugin_id,
            operation,
            payload,
            services,
            cancellation,
            channel="internal",
        )

    def _invoke(
        self,
        allowlist: dict[str, frozenset[str]],
        plugin_id: str,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
        *,
        channel: str,
    ) -> Any:
        with self._lock:
            registered = self._plugins.get(plugin_id)
            if registered is None:
                raise CapabilityDenied("plugin_unavailable")
            descriptor, instance = registered
            if (
                plugin_id in OPTIONAL_PLUGIN_IDS
                and plugin_id not in self._enabled_plugins
            ):
                raise CapabilityDenied("plugin_disabled")
            declared_operations = (
                descriptor.public_operations
                if channel == "public"
                else descriptor.operations
            )
            if operation not in declared_operations or operation not in allowlist.get(
                plugin_id, frozenset()
            ):
                raise CapabilityDenied("operation_not_allowed")
            self._enforce_history_policy_unlocked(descriptor, operation, channel)
            if not isinstance(payload, dict):
                raise CapabilityDenied("plugin_payload_invalid")
        return instance.invoke(operation, payload, services, cancellation)

    def _enforce_history_policy_unlocked(
        self, descriptor: PluginDescriptor, operation: str, channel: str
    ) -> None:
        if descriptor.plugin_id != "history-sqlite":
            return
        state = self._history_state_unlocked()
        if state in {"absent", "unavailable"}:
            raise CapabilityDenied("plugin_unavailable")
        if channel == "internal" and operation == "save":
            if state != "writable" or "storage_write" not in descriptor.permissions:
                raise CapabilityDenied("write_permission_denied")
        if channel == "admin" and operation in HISTORY_MUTATING_ADMIN_OPERATIONS:
            if "storage_write" not in descriptor.permissions:
                raise CapabilityDenied("write_permission_denied")


def _safe_key_version(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 32
        and value[0].isascii()
        and value[0].isalnum()
        and ".." not in value
        and any(character.isdigit() for character in value)
        and all(
            character.isascii()
            and (character.isalnum() or character in "-_.")
            for character in value
        )
    )
