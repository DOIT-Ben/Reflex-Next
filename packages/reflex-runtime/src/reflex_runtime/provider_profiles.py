"""Provider protocol and model capability profiles.

Profiles are deliberately data-only.  They describe transport capabilities and
model preferences without coupling the Core to a vendor SDK or prompt template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_PROTOCOLS = frozenset(
    {
        "openai_chat_completions",
        "openai_responses",
        "anthropic_messages",
        "gemini_generate_content",
    }
)


@dataclass(frozen=True)
class ProtocolProfile:
    """Wire protocol used by a Provider adapter."""

    id: str
    supports_stream: bool = True
    supports_system_message: bool = True
    supports_cancel: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or self.id not in SUPPORTED_PROTOCOLS:
            raise ValueError("unsupported provider protocol")
        for name in ("supports_stream", "supports_system_message", "supports_cancel"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")


@dataclass(frozen=True)
class ModelCapabilityProfile:
    """Model-level capabilities and optimization preferences.

    ``preferences`` is intentionally opaque to the protocol adapter.  Template
    packs may use it to tune wording for a model family, while adapters only
    consume transport fields such as JSON/tool/vision support.
    """

    context_window: int | None = None
    supports_json: bool = False
    supports_reasoning: bool = False
    supports_vision: bool = False
    supports_tools: bool = False
    preferences: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.context_window is not None and (
            isinstance(self.context_window, bool)
            or not isinstance(self.context_window, int)
            or self.context_window <= 0
        ):
            raise ValueError("context_window must be a positive integer")
        for name in (
            "supports_json",
            "supports_reasoning",
            "supports_vision",
            "supports_tools",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a bool")
        if not isinstance(self.preferences, dict):
            raise TypeError("preferences must be a dict")
        object.__setattr__(self, "preferences", dict(self.preferences))

