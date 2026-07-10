from __future__ import annotations


class FixtureProvider:
    id = "minimax"

    def __init__(self, model: str) -> None:
        self.model = model

    def stream(self, rendered_request, request, cancellation):
        if cancellation.is_cancelled:
            return
        yield f"{self.model}:{request.text}"


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
