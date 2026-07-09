"""Dependency inversion protocols for the optimization use case."""

from __future__ import annotations

from typing import Any, Iterable, Protocol

from .cancellation import CancellationToken
from .models import OptimizeRequest, SceneDetectionResult


class SceneDetector(Protocol):
    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        ...


class TemplateResolver(Protocol):
    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> Any:
        ...


class Provider(Protocol):
    id: str
    model: str | None

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        ...
