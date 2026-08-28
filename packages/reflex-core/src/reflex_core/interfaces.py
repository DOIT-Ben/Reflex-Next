"""Dependency inversion protocols for the optimization use case."""

from __future__ import annotations

from typing import Any, Iterable, Protocol

from .cancellation import CancellationToken
from .models import OptimizeRequest, SceneDetectionResult
from .provider_events import ProviderEvent


class SceneDetector(Protocol):
    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        ...


class TemplateResolver(Protocol):
    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> Any:
        ...


class TemplatePack(Protocol):
    manifest: Any

    @property
    def scene_ids(self) -> tuple[str, ...]:
        ...

    @property
    def style_ids(self) -> tuple[str, ...]:
        ...

    def read_system(self) -> str:
        ...

    def read_scene(self, scene_id: str) -> str:
        ...

    def read_style(self, style_id: str) -> str:
        ...


class Provider(Protocol):
    id: str
    model: str | None

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[ProviderEvent]:
        ...
