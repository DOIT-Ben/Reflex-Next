"""Minimal template resolver used before template packs are implemented."""

from __future__ import annotations

from ..models import OptimizeRequest, SceneDetectionResult


class PassthroughTemplateResolver:
    """Return a structured, provider-neutral request without provider logic."""

    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> dict[str, object]:
        return {
            "text": request.text,
            "mode": request.mode,
            "style": request.style,
            "scene": scene.scene,
            "metadata": dict(request.metadata),
        }
