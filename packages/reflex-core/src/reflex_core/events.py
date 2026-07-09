"""Event primitives for Reflex Core."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    """Host-facing event emitted by the headless core."""

    type: str
    data: dict[str, Any] = field(default_factory=dict)

