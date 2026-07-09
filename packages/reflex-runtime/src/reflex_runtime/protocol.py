"""NDJSON command protocol consumed by the runtime sidecar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reflex_core import PROTOCOL_VERSION

COMMAND_TYPES = frozenset({"optimize", "cancel", "ping", "shutdown"})


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
    return CommandEnvelope(
        version=PROTOCOL_VERSION,
        request_id=request_id.strip(),
        type=command_type,
        payload=dict(payload),
    )
