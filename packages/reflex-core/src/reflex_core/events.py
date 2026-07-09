"""Stable event primitives and constructors for Reflex Core."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    STATUS = "status"
    SCENE = "scene"
    REQUEST = "request"
    CHUNK = "chunk"
    DONE = "done"
    ERROR = "error"
    METRIC = "metric"


class StatusPhase(str, Enum):
    ANALYZING_SCENE = "analyzing_scene"
    CONNECTING_PROVIDER = "connecting_provider"
    STREAMING = "streaming"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


@dataclass(frozen=True)
class Event:
    """Host-facing event emitted by the headless core."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        event_type = self.type if isinstance(self.type, EventType) else EventType(self.type)
        object.__setattr__(self, "type", event_type)
        object.__setattr__(self, "data", dict(self.data))

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type.value, "data": dict(self.data)}


def status_event(phase: StatusPhase, message: str) -> Event:
    return Event(EventType.STATUS, {"phase": phase.value, "message": message})


def scene_event(scene: str, confidence: float, method: str, reason: str = "") -> Event:
    return Event(
        EventType.SCENE,
        {"scene": scene, "confidence": float(confidence), "method": method, "reason": reason},
    )


def request_event(provider: str | None, model: str | None) -> Event:
    return Event(EventType.REQUEST, {"provider": provider, "model": model})


def chunk_event(text: str) -> Event:
    return Event(EventType.CHUNK, {"text": text})


def done_event(
    text: str,
    *,
    scene: str,
    style: str,
    mode: str,
    provider: str | None,
    model: str | None,
) -> Event:
    return Event(
        EventType.DONE,
        {
            "text": text,
            "scene": scene,
            "style": style,
            "mode": mode,
            "provider": provider,
            "model": model,
        },
    )


def error_event(
    code: str,
    message: str,
    *,
    recoverable: bool,
    action: str | None = None,
) -> Event:
    return Event(
        EventType.ERROR,
        {
            "code": code,
            "message": message,
            "recoverable": bool(recoverable),
            "action": action,
        },
    )


def metric_event(**metrics: Any) -> Event:
    return Event(EventType.METRIC, metrics)
