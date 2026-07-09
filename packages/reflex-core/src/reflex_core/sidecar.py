"""Command-line sidecar for host processes that consume Reflex Core events."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from dataclasses import fields
from typing import Any

from .cancellation import CancellationToken
from .events import Event, EventType, error_event
from .models import OptimizeRequest
from .protocol import EventEnvelope, new_request_id
from .safety import redact_sensitive
from .scene.detectors import RuleSceneDetector
from .template.resolver import PassthroughTemplateResolver
from .usecases import OptimizeUseCase


class PreviewProvider:
    """Local deterministic provider used until runtime loads real provider plugins."""

    id = "local-preview"
    model = "deterministic-preview"

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        del cancellation
        text = rendered_request.get("text", request.text) if isinstance(rendered_request, dict) else request.text
        scene = rendered_request.get("scene", request.scene or "general") if isinstance(rendered_request, dict) else "general"
        yield f"优化结果（{scene}，{request.style}）：{text}"


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = argparse.ArgumentParser(prog="python -m reflex_core.sidecar")
    parser.add_argument("--request-json", required=True)
    parser.add_argument("--request-id", default=None)
    args = parser.parse_args(argv)
    request_id = args.request_id or new_request_id()

    try:
        payload = json.loads(args.request_json)
        request = _request_from_payload(payload)
    except Exception as exc:
        _write_envelope(
            EventEnvelope(
                request_id,
                error_event(
                    "invalid_request",
                    redact_sensitive(f"请求格式无效：{exc}"),
                    recoverable=True,
                    action="edit",
                ),
            )
        )
        return 1

    use_case = OptimizeUseCase(
        scene_detector=RuleSceneDetector(),
        template_resolver=PassthroughTemplateResolver(),
        provider=PreviewProvider(),
    )
    exit_code = 0
    for envelope in use_case.optimize(request, request_id=request_id):
        _write_envelope(envelope)
        if envelope.event.type is EventType.ERROR:
            exit_code = 1
    return exit_code


def _request_from_payload(payload: Any) -> OptimizeRequest:
    if not isinstance(payload, dict):
        raise ValueError("请求必须是 JSON 对象")
    allowed = {field.name for field in fields(OptimizeRequest)}
    data = {key: value for key, value in payload.items() if key in allowed}
    return OptimizeRequest(**data)


def _write_envelope(envelope: EventEnvelope) -> None:
    print(json.dumps(envelope.to_dict(), ensure_ascii=False), flush=True)


def _configure_stdio() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
