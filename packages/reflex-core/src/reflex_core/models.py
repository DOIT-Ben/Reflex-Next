"""Core data models for Reflex Next."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_ALLOWED_MODES = frozenset({"content", "prompt"})
_ALLOWED_STYLES = frozenset({"concise", "balanced", "detailed", "creative", "precise"})
_ALLOWED_SCENE_POLICIES = frozenset({"auto", "manual", "ask"})


def _normalize_optional(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    normalized = value.strip()
    return normalized or None


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

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")
        if not isinstance(self.mode, str):
            raise TypeError("mode must be a string")
        if not isinstance(self.style, str):
            raise TypeError("style must be a string")
        if not isinstance(self.scene_policy, str):
            raise TypeError("scene_policy must be a string")
        if not isinstance(self.stream, bool):
            raise TypeError("stream must be a bool")
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dict")

        text = self.text.strip()
        mode = self.mode.strip().lower()
        style = self.style.strip().lower()
        scene_policy = self.scene_policy.strip().lower()

        if mode not in _ALLOWED_MODES:
            raise ValueError(f"unsupported mode: {mode}")
        if style not in _ALLOWED_STYLES:
            raise ValueError(f"unsupported style: {style}")
        if scene_policy not in _ALLOWED_SCENE_POLICIES:
            raise ValueError(f"unsupported scene_policy: {scene_policy}")

        object.__setattr__(self, "text", text)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "style", style)
        object.__setattr__(self, "scene_policy", scene_policy)
        object.__setattr__(self, "scene", _normalize_optional(self.scene, "scene"))
        object.__setattr__(self, "provider", _normalize_optional(self.provider, "provider"))
        object.__setattr__(self, "model", _normalize_optional(self.model, "model"))
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class SceneDetectionResult:
    """Scene router result."""

    scene: str
    confidence: float
    method: str
    reason: str = ""
    category: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scene, str) or not self.scene.strip():
            raise ValueError("scene must be a non-empty string")
        if not isinstance(self.method, str) or not self.method.strip():
            raise ValueError("method must be a non-empty string")
        if not isinstance(self.confidence, (int, float)):
            raise TypeError("confidence must be numeric")
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "scene", self.scene.strip())
        object.__setattr__(self, "method", self.method.strip())
        object.__setattr__(self, "confidence", confidence)
        if self.category is not None:
            if not isinstance(self.category, str) or not self.category.strip():
                raise ValueError("category must be a non-empty string")
            object.__setattr__(self, "category", self.category.strip())


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
