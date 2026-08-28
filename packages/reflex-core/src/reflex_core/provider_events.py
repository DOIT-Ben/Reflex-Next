"""Structured events emitted by provider protocol adapters.

``ProviderEvent`` is the Core-facing stream contract.  The iterator helper
keeps the legacy text-only provider shape at one compatibility boundary while
all optimization orchestration consumes the same event model.
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


def iter_provider_events(
    provider: Any,
    rendered_request: Any,
    request: Any,
    cancellation: Any,
):
    """Yield the single Core provider event stream.

    First-party adapters implement ``stream_events``.  Older third-party
    adapters may still expose ``stream``; conversion is deliberately kept
    here so the use case does not carry two provider protocols.
    """

    event_stream = getattr(provider, "stream_events", None)
    if callable(event_stream):
        yield from event_stream(rendered_request, request, cancellation)
        return

    provider_id = getattr(provider, "id", "legacy")
    model = getattr(provider, "model", "legacy") or "legacy"
    protocol = getattr(provider, "protocol", "legacy") or "legacy"
    yield ProviderEvent.started(
        provider=str(provider_id),
        model=str(model),
        protocol=str(protocol),
    )
    for chunk in provider.stream(rendered_request, request, cancellation):
        yield ProviderEvent.text(chunk)
    yield ProviderEvent.completed(finish_reason="stop")
