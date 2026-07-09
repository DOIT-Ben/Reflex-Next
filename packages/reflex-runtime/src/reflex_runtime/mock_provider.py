"""Mock provider used by Runtime Stage 2 without network access."""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

from reflex_core import CancellationToken, OptimizeRequest


class MockProvider:
    id = "mock"
    model = "mock-stream"

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        metadata = request.metadata
        if metadata.get("mock_error") == "unconfigured":
            raise PermissionError("api_key=mock-secret is missing")
        if metadata.get("mock_error") == "unavailable":
            raise ConnectionError("mock provider unavailable")
        if metadata.get("mock_error") == "timeout":
            raise TimeoutError("mock provider timeout")

        chunks = metadata.get("chunks")
        if chunks is None:
            text = rendered_request.get("text", request.text) if isinstance(rendered_request, dict) else request.text
            scene = rendered_request.get("scene", request.scene or "general") if isinstance(rendered_request, dict) else "general"
            chunks = [f"优化结果（{scene}，{request.style}）：{text}"]

        delay_ms = metadata.get("delay_ms", 0)
        for chunk in chunks:
            if cancellation.is_cancelled:
                return
            if delay_ms:
                time.sleep(float(delay_ms) / 1000)
            if cancellation.is_cancelled:
                return
            yield str(chunk)
