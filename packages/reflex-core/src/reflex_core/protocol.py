"""Versioned host/runtime protocol envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .events import Event

PROTOCOL_VERSION = 1


def new_request_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class EventEnvelope:
    """Versioned event envelope used across process boundaries."""

    request_id: str
    event: Event
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported protocol version: {self.version}")
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(self.event, Event):
            raise TypeError("event must be an Event")
        object.__setattr__(self, "request_id", self.request_id.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "event": self.event.to_dict(),
        }
