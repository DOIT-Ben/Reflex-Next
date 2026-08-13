"""Structured events emitted by protocol adapters.

Adapters may expose these through ``stream_events`` while retaining the
legacy text-only ``stream`` method for older plugins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ProviderEventKind = Literal[
    "request_started", "text_delta", "usage", "completed", "error", "cancelled"
]


@dataclass(frozen=True)
class ProviderEvent:
    kind: ProviderEventKind
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed = {"request_started", "text_delta", "usage", "completed", "error", "cancelled"}
        if self.kind not in allowed:
            raise ValueError("invalid provider event kind")
        if not isinstance(self.data, dict):
            raise TypeError("provider event data must be a dict")
        object.__setattr__(self, "data", dict(self.data))

    @classmethod
    def started(
        cls,
        *,
        provider: str,
        model: str,
        protocol: str,
        response_id: str | None = None,
    ) -> "ProviderEvent":
        data: dict[str, Any] = {"provider": provider, "model": model, "protocol": protocol}
        if response_id:
            data["response_id"] = response_id
        return cls("request_started", data)

    @classmethod
    def text(cls, value: str) -> "ProviderEvent":
        return cls("text_delta", {"text": value})

    @classmethod
    def usage(cls, **values: int) -> "ProviderEvent":
        return cls("usage", {key: value for key, value in values.items() if value >= 0})

    @classmethod
    def completed(
        cls,
        *,
        finish_reason: str = "stop",
        response_id: str | None = None,
        **values: Any,
    ) -> "ProviderEvent":
        data: dict[str, Any] = {"finish_reason": finish_reason}
        if response_id:
            data["response_id"] = response_id
        data.update(values)
        return cls("completed", data)

    @classmethod
    def error(
        cls,
        code: str,
        *,
        retryable: bool = False,
        response_id: str | None = None,
    ) -> "ProviderEvent":
        data: dict[str, Any] = {"code": code, "retryable": retryable}
        if response_id:
            data["response_id"] = response_id
        return cls("error", data)

    @classmethod
    def cancelled(cls, reason: str = "user") -> "ProviderEvent":
        return cls("cancelled", {"reason": reason})
