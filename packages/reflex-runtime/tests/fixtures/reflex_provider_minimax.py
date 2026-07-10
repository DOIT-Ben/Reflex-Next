from __future__ import annotations

import time

from reflex_runtime.provider_errors import ProviderRuntimeError


class FixtureProvider:
    id = "minimax"

    def __init__(self, model: str) -> None:
        self.model = model

    def stream(self, rendered_request, request, cancellation):
        if request.text == "fixture-private-auth-request":
            raise ProviderRuntimeError(
                "provider_auth_failed",
                "Provider authentication failed.",
                recoverable=True,
                action="settings",
            )
        if cancellation.is_cancelled:
            return
        chunks = request.metadata.get("chunks")
        if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
            chunks = [f"{self.model}:{request.text}"]
        delay_seconds = max(0, int(request.metadata.get("delay_ms", 0))) / 1000
        for chunk in chunks:
            if cancellation.is_cancelled:
                return
            yield chunk
            if delay_seconds:
                time.sleep(delay_seconds)


class FixtureFactory:
    id = "minimax"
    display_name = "MiniMax Fixture"
    version = "0.1.0"
    models = ("fixture-model-a", "fixture-model-b")
    default_model = "fixture-model-a"
    required_secret = "api_key"
    permissions = ("network",)
    default_base_url = "https://fixture.invalid/v1/chat/completions"

    def create(self, secret, config):
        if not secret:
            raise ValueError("secret required")
        return FixtureProvider(config.model)


def plugin():
    return FixtureFactory()
