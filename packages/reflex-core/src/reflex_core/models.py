"""Core data models for Reflex Next."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class OptimizeRequest:
    """User request normalized before scene routing and provider execution."""

    text: str
    mode: str = "content"
    style: str = "balanced"
    scene: str | None = None
    scene_policy: str = "auto"
    provider: str | None = None
    model: str | None = None
    stream: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SceneDetectionResult:
    """Scene router result."""

    scene: str
    confidence: float
    method: str
    reason: str = ""


@dataclass(frozen=True)
class OptimizeResult:
    """Final optimization result."""

    text: str
    scene: str
    style: str
    mode: str
    provider: str | None = None
    model: str | None = None
    elapsed_seconds: float | None = None

