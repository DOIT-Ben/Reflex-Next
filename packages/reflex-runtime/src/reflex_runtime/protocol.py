"""NDJSON command protocol consumed by the runtime sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reflex_core import PROTOCOL_VERSION

COMMAND_TYPES = frozenset({"optimize", "cancel", "ping", "shutdown", "configure_provider"})
CONFIGURE_PROVIDER_FIELDS = frozenset({"provider_id", "secret", "config"})


class ProtocolError(ValueError):
    """Raised when a host command cannot be accepted."""


@dataclass(frozen=True)
class CommandEnvelope:
    version: int
    request_id: str
    type: str
    payload: dict[str, Any]


def parse_command(value: Any) -> CommandEnvelope:
    if not isinstance(value, dict):
        raise ProtocolError("command must be a JSON object")
    if value.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ProtocolError("request_id must be a non-empty string")
    command_type = value.get("type")
    if command_type not in COMMAND_TYPES:
        raise ProtocolError("unsupported command type")
    payload = value.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object")
    if command_type == "configure_provider":
        _validate_provider_configuration(payload)
    return CommandEnvelope(
        version=PROTOCOL_VERSION,
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


def _safe_provider_id(provider_id: str) -> bool:
    normalized = provider_id.strip()
    return bool(normalized) and len(normalized) <= 64 and all(
        character.isascii() and (character.isalnum() or character in "-_.")
        for character in normalized
    )
