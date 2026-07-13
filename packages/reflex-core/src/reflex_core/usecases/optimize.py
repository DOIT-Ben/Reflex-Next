"""Framework-independent optimization orchestration."""

from __future__ import annotations

from collections.abc import Iterator
from threading import Event, Lock, Timer
from time import monotonic
from typing import Any, Callable

from ..cancellation import CancellationToken, OperationCancelled
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


_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_OUTPUT_CHUNKS = 50_000
_MAX_REQUEST_SECONDS = 120.0


class _RequestDeadline:
    def __init__(
        self,
        token: CancellationToken,
        timer_factory: Callable[[float, Callable[[], None]], Any],
    ) -> None:
        self._token = token
        self._expired = Event()
        self._lock = Lock()
        self._closed = False
        self._timer = timer_factory(_MAX_REQUEST_SECONDS, self.expire)

    @property
    def expired(self) -> bool:
        return self._expired.is_set()

    def start(self) -> None:
        if hasattr(self._timer, "daemon"):
            self._timer.daemon = True
        self._timer.start()

    def expire(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._expired.set()
        self._token.cancel()

    def try_complete(self) -> bool:
        with self._lock:
            if self._expired.is_set():
                return False
            self._closed = True
        self._timer.cancel()
        return True

    def close(self) -> None:
        with self._lock:
            self._closed = True
        self._timer.cancel()


class OptimizeUseCase:
    """Coordinate validation, scene routing, template rendering and provider streaming."""

    def __init__(
        self,
        *,
        scene_detector: SceneDetector,
        template_resolver: TemplateResolver,
        provider: Provider,
        clock: Callable[[], float] = monotonic,
        timer_factory: Callable[[float, Callable[[], None]], Any] = Timer,
    ) -> None:
        self._scene_detector = scene_detector
        self._template_resolver = template_resolver
        self._provider = provider
        self._clock = clock
        self._timer_factory = timer_factory

    def optimize(
        self,
        request: OptimizeRequest,
        *,
        request_id: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> Iterator[EventEnvelope]:
        current_request_id = request_id or new_request_id()
        token = cancellation or CancellationToken()
        deadline = _RequestDeadline(token, self._timer_factory)
        deadline.start()
        try:
            yield from self._run_optimize(
                request,
                current_request_id=current_request_id,
                token=token,
                deadline=deadline,
            )
        finally:
            deadline.close()

    def _run_optimize(
        self,
        request: OptimizeRequest,
        *,
        current_request_id: str,
        token: CancellationToken,
        deadline: _RequestDeadline,
    ) -> Iterator[EventEnvelope]:
        started_at = self._clock()

        try:
            normalized_text = validate_input(request.text)
        except InputValidationError as exc:
            if not deadline.try_complete():
                yield self._request_timeout(current_request_id)
                return
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
            yield self._cancellation_terminal(current_request_id, deadline)
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
            yield self._cancellation_terminal(current_request_id, deadline)
            return
        if self._deadline_exceeded(started_at):
            deadline.expire()
            yield self._request_timeout(current_request_id)
            return

        provider_id = request.provider or getattr(self._provider, "id", None)
        model = request.model or getattr(self._provider, "model", None)

        try:
            rendered = self._template_resolver.render(request, detected_scene)
        except Exception:
            if not deadline.try_complete():
                yield self._request_timeout(current_request_id)
                return
            yield self._envelope(
                current_request_id,
                error_event(
                    "template_render_error",
                    "Unable to prepare model request.",
                    recoverable=False,
                ),
            )
            return

        if token.is_cancelled:
            yield self._cancellation_terminal(current_request_id, deadline)
            return
        if self._deadline_exceeded(started_at):
            deadline.expire()
            yield self._request_timeout(current_request_id)
            return

        yield self._envelope(current_request_id, request_event(provider_id, model))

        try:
            chunks: list[str] = []
            output_bytes = 0
            output_chunks = 0
            for raw_chunk in self._provider.stream(rendered, request, token):
                if token.is_cancelled:
                    yield self._cancellation_terminal(current_request_id, deadline)
                    return
                if self._deadline_exceeded(started_at):
                    deadline.expire()
                    yield self._request_timeout(current_request_id)
                    return
                chunk = sanitize_text(raw_chunk)
                if not chunk:
                    continue
                next_output_bytes = output_bytes + len(chunk.encode("utf-8"))
                next_output_chunks = output_chunks + 1
                if (
                    next_output_bytes > _MAX_OUTPUT_BYTES
                    or next_output_chunks > _MAX_OUTPUT_CHUNKS
                ):
                    if not deadline.try_complete():
                        yield self._request_timeout(current_request_id)
                        return
                    yield self._output_too_large(current_request_id)
                    return
                output_bytes = next_output_bytes
                output_chunks = next_output_chunks
                chunks.append(chunk)
                yield self._envelope(current_request_id, chunk_event(chunk))

            if token.is_cancelled:
                yield self._cancellation_terminal(current_request_id, deadline)
                return
            if self._deadline_exceeded(started_at):
                deadline.expire()
                yield self._request_timeout(current_request_id)
                return

            final_text = sanitize_text("".join(chunks)).strip()
            if not final_text:
                if not deadline.try_complete():
                    yield self._request_timeout(current_request_id)
                    return
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

            if not deadline.try_complete():
                yield self._request_timeout(current_request_id)
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
                metric_event(elapsed_seconds=max(0.0, self._clock() - started_at)),
            )
        except OperationCancelled:
            yield self._cancellation_terminal(current_request_id, deadline)
        except Exception as exc:
            if not deadline.try_complete():
                yield self._request_timeout(current_request_id)
                return
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

    @classmethod
    def _output_too_large(cls, request_id: str) -> EventEnvelope:
        return cls._envelope(
            request_id,
            error_event(
                "output_too_large",
                "Provider output exceeded the allowed limit.",
                recoverable=False,
            ),
        )

    def _deadline_exceeded(self, started_at: float) -> bool:
        return self._clock() - started_at >= _MAX_REQUEST_SECONDS

    @classmethod
    def _cancellation_terminal(
        cls, request_id: str, deadline: _RequestDeadline
    ) -> EventEnvelope:
        if not deadline.try_complete():
            return cls._request_timeout(request_id)
        return cls._cancelled(request_id)

    @classmethod
    def _request_timeout(cls, request_id: str) -> EventEnvelope:
        return cls._envelope(
            request_id,
            error_event(
                "request_timeout",
                "Request exceeded the 120 second time limit.",
                recoverable=True,
                action="retry",
            ),
        )
