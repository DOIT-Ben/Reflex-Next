from __future__ import annotations

import os
import sys
import time

from reflex_runtime.provider_errors import ProviderRuntimeError


if os.environ.get("REFLEX_NOISY_FIXTURE") == "1":
    print("fixture-print-noise", flush=True)
    sys.__stdout__.write("fixture-dunder-noise\n")
    sys.__stdout__.flush()
    os.write(1, b"fixture-fd-noise\n")


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
        if request.metadata.get("fixture_template_contract") is True:
            messages = rendered_request.get("messages") if isinstance(rendered_request, dict) else None
            if not _valid_template_messages(messages, request):
                raise RuntimeError("template contract missing")
            yield "template-contract-ok"
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


def _valid_template_messages(messages, request) -> bool:
    if not isinstance(messages, list) or len(messages) != 2:
        return False
    system, user = messages
    if not isinstance(system, dict) or not isinstance(user, dict):
        return False
    system_content = system.get("content")
    return (
        system.get("role") == "system"
        and isinstance(system_content, str)
        and "结构化提示词" in system_content
        and "代码审查场景" in system_content
        and "精准风格" in system_content
        and "English (US)" in system_content
        and user == {"role": "user", "content": request.text}
        and request.mode == "prompt"
        and request.style == "precise"
        and request.scene == "code_review"
    )
