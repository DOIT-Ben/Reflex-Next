"""Deterministic fakes for contract and host integration tests."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .cancellation import CancellationToken
from .models import OptimizeRequest, SceneDetectionResult


class FakeSceneDetector:
    def __init__(
        self,
        result: SceneDetectionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.result = result or SceneDetectionResult("general", 0.5, "fake")
        self.error = error

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        if self.error is not None:
            raise self.error
        return self.result


class FakeTemplateResolver:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error

    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> dict[str, Any]:
        if self.error is not None:
            raise self.error
        return {"text": request.text, "scene": scene.scene}


class FakeProvider:
    id = "fake"
    model = "fake-model"

    def __init__(
        self,
        chunks: Iterable[str] = ("ok",),
        *,
        error: BaseException | None = None,
        on_chunk: Callable[[int, CancellationToken], None] | None = None,
        ignore_cancellation: bool = False,
    ) -> None:
        self._chunks = tuple(chunks)
        self._error = error
        self._on_chunk = on_chunk
        self._ignore_cancellation = ignore_cancellation

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        if self._error is not None:
            raise self._error
        for index, chunk in enumerate(self._chunks):
            if self._on_chunk is not None:
                self._on_chunk(index, cancellation)
            if cancellation.is_cancelled and not self._ignore_cancellation:
                return
            yield chunk
