"""Framework-independent optimization orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from time import monotonic

from ..cancellation import CancellationToken
from ..events import (
    StatusPhase,
    chunk_event,
    done_event,
    error_event,
    metric_event,
    request_event,
    scene_event,
    status_event,
)
from ..interfaces import Provider, SceneDetector, TemplateResolver
from ..models import OptimizeRequest, SceneDetectionResult
from ..protocol import EventEnvelope, new_request_id
from ..safety import InputValidationError, safe_provider_error, sanitize_text, validate_input


class OptimizeUseCase:
    """Coordinate validation, scene routing, template rendering and provider streaming."""

    def __init__(
        self,
        *,
        scene_detector: SceneDetector,
        template_resolver: TemplateResolver,
        provider: Provider,
    ) -> None:
        self._scene_detector = scene_detector
        self._template_resolver = template_resolver
        self._provider = provider

    def optimize(
        self,
        request: OptimizeRequest,
        *,
        request_id: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[EventEnvelope]:
        current_request_id = request_id or new_request_id()
        token = cancellation or CancellationToken()
        started_at = monotonic()

        try:
            normalized_text = validate_input(request.text)
        except InputValidationError as exc:
            yield self._envelope(
                current_request_id,
                error_event("invalid_input", str(exc), recoverable=True, action="edit"),
            )
            return

        request = OptimizeRequest(
            text=normalized_text,
            mode=request.mode,
            style=request.style,
            scene=request.scene,
            scene_policy=request.scene_policy,
            provider=request.provider,
            model=request.model,
            stream=request.stream,
            metadata=request.metadata,
        )

        yield self._envelope(
            current_request_id,
            status_event(StatusPhase.ANALYZING_SCENE, "Analyzing scene."),
        )

        if token.is_cancelled:
            yield self._cancelled(current_request_id)
            return

        detected_scene = self._resolve_scene(request)
        yield self._envelope(
            current_request_id,
            scene_event(
                detected_scene.scene,
                detected_scene.confidence,
                detected_scene.method,
                detected_scene.reason,
            ),
        )

        if token.is_cancelled:
            yield self._cancelled(current_request_id)
            return

        provider_id = request.provider or getattr(self._provider, "id", None)
        model = request.model or getattr(self._provider, "model", None)

        try:
            rendered = self._template_resolver.render(request, detected_scene)
        except Exception:
            yield self._envelope(
                current_request_id,
                error_event(
                    "template_render_error",
                    "Unable to prepare model request.",
                    recoverable=False,
                ),
            )
            return

        yield self._envelope(current_request_id, request_event(provider_id, model))

        try:
            chunks: list[str] = []
            for raw_chunk in self._provider.stream(rendered, request, token):
                if token.is_cancelled:
                    yield self._cancelled(current_request_id)
                    return
                chunk = sanitize_text(raw_chunk)
                if not chunk:
                    continue
                chunks.append(chunk)
                yield self._envelope(current_request_id, chunk_event(chunk))

            if token.is_cancelled:
                yield self._cancelled(current_request_id)
                return

            final_text = sanitize_text("".join(chunks)).strip()
            if not final_text:
                yield self._envelope(
                    current_request_id,
                    error_event(
                        "empty_result",
                        "Provider returned no usable text.",
                        recoverable=True,
                        action="retry",
                    ),
                )
                return

            yield self._envelope(
                current_request_id,
                done_event(
                    final_text,
                    scene=detected_scene.scene,
                    style=request.style,
                    mode=request.mode,
                    provider=provider_id,
                    model=model,
                ),
            )
            yield self._envelope(
                current_request_id,
                metric_event(elapsed_seconds=max(0.0, monotonic() - started_at)),
            )
        except Exception as exc:
            code, message, recoverable, action = safe_provider_error(exc)
            yield self._envelope(
                current_request_id,
                error_event(code, message, recoverable=recoverable, action=action),
            )

    def _resolve_scene(self, request: OptimizeRequest) -> SceneDetectionResult:
        if request.scene and request.scene_policy in {"manual", "ask"}:
            return SceneDetectionResult(
                scene=request.scene,
                confidence=1.0,
                method="manual",
            )
        try:
            result = self._scene_detector.detect(request.text, request)
            if not result.scene:
                raise ValueError("empty scene")
            return result
        except Exception:
            return SceneDetectionResult(
                scene="general",
                confidence=0.0,
                method="fallback",
                reason="scene_detector_failed",
            )

    @staticmethod
    def _envelope(request_id: str, event) -> EventEnvelope:
        return EventEnvelope(request_id=request_id, event=event)

    @classmethod
    def _cancelled(cls, request_id: str) -> EventEnvelope:
        return cls._envelope(
            request_id,
            status_event(StatusPhase.CANCELLED, "Generation cancelled."),
        )
