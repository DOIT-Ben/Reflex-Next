from __future__ import annotations

from dataclasses import dataclass

import pytest

from reflex_runtime.provider_errors import ProviderRuntimeError
from reflex_runtime.provider_registry import ProviderConfig, ProviderRegistry


@dataclass
class RecordingProvider:
    id: str
    model: str

    def stream(self, rendered_request, request, cancellation):
        return iter(())


class RecordingFactory:
    id = "minimax"
    display_name = "MiniMax"
    version = "0.1.0"
    models = ("model-a", "model-b")
    default_model = "model-a"
    required_secret = "api_key"
    permissions = ("network",)
    default_base_url = "https://api.example.test/v1/chat/completions"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ProviderConfig]] = []

    def create(self, secret: str, config: ProviderConfig) -> RecordingProvider:
        self.calls.append((secret, config))
        return RecordingProvider(self.id, config.model)


def test_registry_replaces_configured_instance_without_exposing_secrets():
    factory = RecordingFactory()
    registry = ProviderRegistry({"minimax": factory})

    registry.configure("minimax", "first-fixture-secret", {"model": "model-a"})
    first = registry.resolve("minimax", "model-a")
    registry.configure("MiniMax", "second-fixture-secret", {"model": "model-b"})
    second = registry.resolve("minimax", "model-b")

    assert first is not second
    assert second.model == "model-b"
    assert [secret for secret, _ in factory.calls] == [
        "first-fixture-secret",
        "second-fixture-secret",
    ]
    assert "first-fixture-secret" not in repr(registry)
    assert "second-fixture-secret" not in repr(registry)


def test_registry_builds_https_tls_config_with_bounded_timeout():
    factory = RecordingFactory()
    registry = ProviderRegistry({"minimax": factory})

    registry.configure(
        "minimax",
        "fixture-secret",
        {
            "model": "model-a",
            "base_url": "https://gateway.example.test/v1/chat/completions",
            "timeout_seconds": 999,
            "tls_verify": False,
            "ca_bundle_path": "  C:\\certs\\root.pem  ",
        },
    )

    config = factory.calls[0][1]
    assert config.base_url == "https://gateway.example.test/v1/chat/completions"
    assert config.timeout_seconds == 300.0
    assert config.tls_verify is True
    assert config.ca_bundle_path == "C:\\certs\\root.pem"


@pytest.mark.parametrize(
    ("provider_id", "model", "code"),
    [
        ("minimax", None, "provider_unconfigured"),
        ("unknown", None, "provider_unconfigured"),
        ("minimax", "not-allowed", "provider_invalid_response"),
    ],
)
def test_registry_returns_stable_safe_errors(provider_id, model, code):
    registry = ProviderRegistry({"minimax": RecordingFactory()})
    if model == "not-allowed":
        registry.configure("minimax", "fixture-secret", {"model": "model-a"})

    with pytest.raises(ProviderRuntimeError) as caught:
        registry.resolve(provider_id, model)

    assert caught.value.code == code
    assert caught.value.safe_message in {
        "Provider is not configured.",
        "Provider configuration is invalid.",
    }
    assert "fixture-secret" not in str(caught.value)
    assert "fixture-secret" not in repr(caught.value)


@pytest.mark.parametrize(
    "raw_config",
    [
        {"model": "not-allowed"},
        {"model": "model-a", "base_url": "http://api.example.test"},
        {"model": "model-a", "ca_bundle_path": 42},
    ],
)
def test_registry_rejects_invalid_provider_configuration(raw_config):
    registry = ProviderRegistry({"minimax": RecordingFactory()})

    with pytest.raises(ProviderRuntimeError) as caught:
        registry.configure("minimax", "fixture-secret", raw_config)

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.action == "settings"
