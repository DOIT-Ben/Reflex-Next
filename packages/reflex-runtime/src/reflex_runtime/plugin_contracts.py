"""Validated contracts for non-Provider Runtime capability plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .protocol import RUNTIME_PROTOCOL_VERSION
PLUGIN_KINDS = frozenset({"storage", "transformer", "command"})
PLUGIN_EVENT_STATUSES = frozenset(
    {"started", "chunk", "progress", "result", "cancelled", "error"}
)
PLUGIN_STATES = frozenset(
    {
        "available",
        "disabled",
        "absent",
        "read_only",
        "writable",
        "private",
        "unavailable",
    }
)


def is_safe_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0].isascii()
        and value[0].islower()
        and all(
            character.isascii()
            and (character.islower() or character.isdigit() or character in "-_")
            for character in value
        )
    )


def _require_safe_id(value: object, field_name: str) -> str:
    if not is_safe_id(value):
        raise ValueError(f"invalid {field_name}")
    return value


def _require_request_id(value: object) -> str:
    if not (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(
            character.isascii()
            and (character.isalnum() or character in "-_.:")
            for character in value
        )
    ):
        raise ValueError("invalid request id")
    return value


@dataclass(frozen=True)
class PluginDescriptor:
    plugin_id: str
    display_name: str
    version: str
    kind: str
    permissions: tuple[str, ...]
    operations: tuple[str, ...]
    public_operations: tuple[str, ...]
    enabled: bool = True
    state: str = "available"
    error_code: str | None = None

    def __post_init__(self) -> None:
        _require_safe_id(self.plugin_id, "plugin id")
        if not isinstance(self.display_name, str) or not self.display_name.strip():
            raise ValueError("invalid display name")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("invalid version")
        if self.kind not in PLUGIN_KINDS:
            raise ValueError("invalid plugin kind")
        if not isinstance(self.permissions, tuple) or any(
            not is_safe_id(permission) for permission in self.permissions
        ):
            raise ValueError("invalid plugin permissions")
        if not isinstance(self.operations, tuple) or not self.operations or any(
            not is_safe_id(operation) for operation in self.operations
        ):
            raise ValueError("invalid plugin operations")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("duplicate plugin permissions")
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("duplicate plugin operations")
        if not isinstance(self.public_operations, tuple) or any(
            not is_safe_id(operation) for operation in self.public_operations
        ):
            raise ValueError("invalid public plugin operations")
        if len(set(self.public_operations)) != len(self.public_operations):
            raise ValueError("duplicate public plugin operations")
        if not set(self.public_operations).issubset(self.operations):
            raise ValueError("public plugin operations must be declared")
        if not isinstance(self.enabled, bool) or self.state not in PLUGIN_STATES:
            raise ValueError("invalid plugin state")
        if self.error_code is not None and not is_safe_id(self.error_code):
            raise ValueError("invalid plugin error code")
        if self.state == "unavailable" and self.error_code is None:
            raise ValueError("unavailable plugin requires an error code")
        if self.state != "unavailable" and self.error_code is not None:
            raise ValueError("available plugin cannot expose an error code")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.plugin_id,
            "name": self.display_name,
            "version": self.version,
            "kind": self.kind,
            "permissions": list(self.permissions),
            "public_operations": list(self.public_operations),
            "enabled": self.enabled,
            "state": self.state,
        }
        if self.error_code is not None:
            result["error_code"] = self.error_code
        return result


@dataclass(frozen=True)
class PluginFailure:
    plugin_id: str
    code: str = "plugin_unavailable"
    kind: str | None = None

    def __post_init__(self) -> None:
        if not is_safe_id(self.plugin_id) and not _is_safe_dotted_id(self.plugin_id):
            raise ValueError("invalid plugin id")
        _require_safe_id(self.code, "plugin failure code")
        if self.kind is not None and self.kind not in PLUGIN_KINDS:
            raise ValueError("invalid plugin kind")

    @property
    def safe_message(self) -> str:
        """Compatibility view for the existing Provider discovery API."""

        return "Provider plugin unavailable."


@dataclass(frozen=True)
class CapabilityListEnvelope:
    request_id: str
    plugins: tuple[PluginDescriptor, ...]
    version: int = RUNTIME_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_request_id(self.request_id)
        if self.version != RUNTIME_PROTOCOL_VERSION:
            raise ValueError("unsupported runtime protocol version")
        if not isinstance(self.plugins, tuple) or any(
            not isinstance(plugin, PluginDescriptor) for plugin in self.plugins
        ):
            raise ValueError("invalid plugin descriptors")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "type": "capability_list",
            "plugins": [plugin.to_dict() for plugin in self.plugins],
        }


@dataclass(frozen=True)
class PluginEventEnvelope:
    request_id: str
    plugin_id: str
    operation: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    code: str | None = None
    version: int = RUNTIME_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_request_id(self.request_id)
        _require_safe_id(self.plugin_id, "plugin id")
        _require_safe_id(self.operation, "plugin operation")
        if self.status not in PLUGIN_EVENT_STATUSES:
            raise ValueError("invalid plugin event status")
        if not isinstance(self.data, dict):
            raise ValueError("invalid plugin event data")
        if self.version != RUNTIME_PROTOCOL_VERSION:
            raise ValueError("unsupported runtime protocol version")
        if self.status == "error":
            if self.code is None or not is_safe_id(self.code) or self.data:
                raise ValueError("plugin errors only expose a safe code")
        elif self.code is not None:
            raise ValueError("non-error plugin event cannot expose an error code")
        _validate_data(self.data)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "version": self.version,
            "request_id": self.request_id,
            "type": "plugin_event",
            "plugin_id": self.plugin_id,
            "operation": self.operation,
            "status": self.status,
            "data": dict(self.data),
        }
        if self.code is not None:
            result["code"] = self.code
        return result


def _validate_data(value: Any) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_data(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key) > 128
                or any(ord(character) < 32 for character in key)
            ):
                raise ValueError("invalid plugin event data")
            _validate_data(item)
        return
    raise ValueError("invalid plugin event data")


def _is_safe_dotted_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 64
        and value[0].isascii()
        and value[0].islower()
        and value[-1] != "."
        and ".." not in value
        and all(
            character.isascii()
            and (
                character.islower()
                or character.isdigit()
                or character in "-_."
            )
            for character in value
        )
    )
