"""NDJSON command protocol consumed by the runtime sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

RUNTIME_PROTOCOL_VERSION = 1
COMMAND_TYPES = frozenset(
    {
        "optimize",
        "cancel",
        "ping",
        "shutdown",
        "configure_provider",
        "discover_provider_models",
        "test_provider_connection",
        "list_providers",
        "list_plugins",
        "plugin_call",
        "configure_plugin",
        "configure_history_keys",
        "configure_history_policy",
        "configure_history_path",
        "plugin_admin_call",
        "plugin_admin_call",
    }
)
CONFIGURE_PROVIDER_FIELDS = frozenset({"provider_id", "secret", "config"})
OPTIMIZE_FIELDS = frozenset(
    {
        "text",
        "mode",
        "style",
        "scene",
        "scene_policy",
        "provider",
        "model",
        "stream",
        "metadata",
    }
)
PLUGIN_CALL_FIELDS = frozenset({"plugin_id", "operation", "input"})
CONFIGURE_PLUGIN_FIELDS = frozenset({"plugin_id", "enabled"})
CONFIGURE_HISTORY_KEYS_FIELDS = frozenset({"keys"})
CONFIGURE_HISTORY_POLICY_FIELDS = frozenset(
    {"history_enabled", "privacy_mode", "history_redaction"}
)
CONFIGURE_HISTORY_PATH_FIELDS = frozenset({"database_path"})
EMPTY_PAYLOAD_COMMANDS = frozenset(
    {"cancel", "ping", "shutdown", "list_providers", "list_plugins"}
)
BUILTIN_CAPABILITY_IDS = frozenset(
    {"history-sqlite", "translator", "markdown-preview", "batch-runner", "semantic-detector"}
)
PRIVATE_FIELD_NAMES = frozenset(
    {"key", "keys", "path", "admin", "private", "secret", "token"}
)
SENSITIVE_COMMANDS = frozenset(
    {
        "configure_provider",
        "discover_provider_models",
        "test_provider_connection",
        "configure_history_keys",
        "configure_history_policy",
        "configure_history_path",
    }
)
COMMAND_ENVELOPE_FIELDS = frozenset({"version", "request_id", "type", "payload"})
PUBLIC_PLUGIN_OPERATIONS = {
    "history-sqlite": frozenset({"list", "detail", "rate", "backups", "scan"}),
    "translator": frozenset({"translate"}),
    "markdown-preview": frozenset({"preview"}),
    "batch-runner": frozenset({"parse", "export", "template"}),
    "semantic-detector": frozenset({"status", "download", "delete"}),
}
ADMIN_PLUGIN_OPERATIONS = {
    "history-sqlite": frozenset(
        {"delete", "clear", "export", "repair", "restore", "rotate"}
    ),
    "markdown-preview": frozenset({"export"}),
}


class ProtocolError(ValueError):
    """Raised when a host command cannot be accepted."""


@dataclass(frozen=True)
class CommandEnvelope:
    version: int
    request_id: str
    type: str
    payload: dict[str, Any]

    def __repr__(self) -> str:
        payload = "<redacted>" if self.type in SENSITIVE_COMMANDS else repr(self.payload)
        return (
            "CommandEnvelope("
            f"version={self.version!r}, request_id={self.request_id!r}, "
            f"type={self.type!r}, payload={payload})"
        )


def parse_command(value: Any) -> CommandEnvelope:
    if not isinstance(value, dict):
        raise ProtocolError("command must be a JSON object")
    if set(value) != COMMAND_ENVELOPE_FIELDS:
        raise ProtocolError("invalid command envelope")
    if value.get("version") != RUNTIME_PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not _safe_request_id(request_id.strip()):
        raise ProtocolError("request_id must be a non-empty string")
    command_type = value.get("type")
    if command_type not in COMMAND_TYPES:
        raise ProtocolError("unsupported command type")
    payload = value.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object")
    if command_type in EMPTY_PAYLOAD_COMMANDS:
        _require_fields(payload, frozenset(), "invalid command payload")
    elif command_type == "optimize":
        _validate_optimize(payload)
    elif command_type in {
        "configure_provider",
        "discover_provider_models",
        "test_provider_connection",
    }:
        _validate_provider_configuration(payload)
    elif command_type in {"plugin_call", "plugin_admin_call"}:
        _validate_plugin_call(payload, public=command_type == "plugin_call")
    elif command_type == "configure_plugin":
        _validate_plugin_configuration(payload)
    elif command_type == "configure_history_keys":
        _validate_history_keys(payload)
    elif command_type == "configure_history_policy":
        _validate_history_policy(payload)
    elif command_type == "configure_history_path":
        _validate_history_path(payload)
    return CommandEnvelope(
        version=RUNTIME_PROTOCOL_VERSION,
        request_id=request_id.strip(),
        type=command_type,
        payload=dict(payload),
    )


def _validate_provider_configuration(payload: dict[str, Any]) -> None:
    if set(payload) != CONFIGURE_PROVIDER_FIELDS:
        raise ProtocolError("invalid provider configuration command")
    provider_id = payload.get("provider_id")
    if not isinstance(provider_id, str) or not _safe_provider_id(provider_id):
        raise ProtocolError("invalid provider configuration command")
    secret = payload.get("secret")
    if not isinstance(secret, str) or not secret.strip() or len(secret) > 16_384:
        raise ProtocolError("invalid provider configuration command")
    if not isinstance(payload.get("config"), dict):
        raise ProtocolError("invalid provider configuration command")


def _validate_optimize(payload: dict[str, Any]) -> None:
    if "text" not in payload or not set(payload).issubset(OPTIMIZE_FIELDS):
        raise ProtocolError("invalid optimize command")
    if not isinstance(payload.get("text"), str):
        raise ProtocolError("invalid optimize command")


def _validate_plugin_call(payload: dict[str, Any], *, public: bool) -> None:
    message = "invalid public plugin call" if public else "invalid plugin admin call"
    _require_fields(payload, PLUGIN_CALL_FIELDS, message)
    if payload.get("plugin_id") not in BUILTIN_CAPABILITY_IDS:
        raise ProtocolError(message)
    if not _safe_runtime_id(payload.get("operation")):
        raise ProtocolError(message)
    operation_allowlist = PUBLIC_PLUGIN_OPERATIONS if public else ADMIN_PLUGIN_OPERATIONS
    if payload["operation"] not in operation_allowlist.get(
        payload["plugin_id"], frozenset()
    ):
        raise ProtocolError(message)
    call_input = payload.get("input")
    if not isinstance(call_input, dict):
        raise ProtocolError(message)
    if public and _contains_private_field(call_input):
        raise ProtocolError(message)


def _validate_plugin_configuration(payload: dict[str, Any]) -> None:
    message = "invalid plugin configuration command"
    _require_fields(payload, CONFIGURE_PLUGIN_FIELDS, message)
    if payload.get("plugin_id") not in {
        "translator",
        "markdown-preview",
        "batch-runner",
        "semantic-detector",
    }:
        raise ProtocolError(message)
    if not isinstance(payload.get("enabled"), bool):
        raise ProtocolError(message)


def _validate_history_keys(payload: dict[str, Any]) -> None:
    message = "invalid history key configuration command"
    if set(payload) not in {
        CONFIGURE_HISTORY_KEYS_FIELDS,
        frozenset({"keys", "active_version", "pending_version"}),
    }:
        raise ProtocolError(message)
    keys = payload.get("keys")
    if not isinstance(keys, dict):
        raise ProtocolError(message)
    for key_id, secret in keys.items():
        if not _safe_key_version(key_id):
            raise ProtocolError(message)
        if not _safe_history_key(secret):
            raise ProtocolError(message)
    if set(payload) == CONFIGURE_HISTORY_KEYS_FIELDS:
        return
    active = payload.get("active_version")
    pending = payload.get("pending_version")
    if active is not None and (not _safe_key_version(active) or active not in keys):
        raise ProtocolError(message)
    if pending is not None and (
        not _safe_key_version(pending)
        or pending not in keys
        or active is None
        or int(pending[1:]) <= int(active[1:])
    ):
        raise ProtocolError(message)


def _validate_history_policy(payload: dict[str, Any]) -> None:
    message = "invalid history policy command"
    _require_fields(payload, CONFIGURE_HISTORY_POLICY_FIELDS, message)
    if not isinstance(payload.get("history_enabled"), bool):
        raise ProtocolError(message)
    if not isinstance(payload.get("privacy_mode"), bool):
        raise ProtocolError(message)
    if payload.get("history_redaction") not in {"secrets", "none"}:
        raise ProtocolError(message)


def _validate_history_path(payload: dict[str, Any]) -> None:
    message = "invalid history path command"
    _require_fields(payload, CONFIGURE_HISTORY_PATH_FIELDS, message)
    database_path = payload.get("database_path")
    if (
        not isinstance(database_path, str)
        or len(database_path) > 4096
        or database_path.startswith(("\\\\", "//"))
        or any(ord(character) < 32 for character in database_path)
    ):
        raise ProtocolError(message)
    path = Path(database_path)
    if (
        not path.is_absolute()
        or path.name != "history.sqlite3"
        or path.parent.name != "history"
        or any(part in {".", ".."} for part in path.parts)
        or any(ord(character) < 32 for character in database_path)
    ):
        raise ProtocolError(message)
def _require_fields(
    payload: dict[str, Any], expected: frozenset[str], message: str
) -> None:
    if set(payload) != expected:
        raise ProtocolError(message)


def _contains_private_field(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_private_field(item) for item in value)
    if not isinstance(value, dict):
        return False
    for key, item in value.items():
        if not isinstance(key, str):
            return True
        normalized = key.strip().lower()
        if (
            normalized in PRIVATE_FIELD_NAMES
            or normalized.startswith(("admin_", "private_", "secret_", "token_"))
            or normalized.endswith(("_key", "_keys", "_path", "_secret", "_token"))
        ):
            return True
        if _contains_private_field(item):
            return True
    return False


def _safe_provider_id(provider_id: str) -> bool:
    normalized = provider_id.strip()
    return bool(normalized) and len(normalized) <= 64 and all(
        character.isascii() and (character.isalnum() or character in "-_.")
        for character in normalized
    )


def _safe_runtime_id(value: object) -> bool:
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


def _safe_request_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(
            character.isascii()
            and (character.isalnum() or character in "-_.:")
            for character in value
        )
    )


def _safe_key_version(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("v"):
        return False
    version = value[1:]
    if (
        not version
        or len(version) > 7
        or not version.isascii()
        or not version.isdigit()
    ):
        return False
    version_number = int(version)
    return 1 <= version_number <= 1_000_000 and version == str(version_number)


def _safe_history_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
