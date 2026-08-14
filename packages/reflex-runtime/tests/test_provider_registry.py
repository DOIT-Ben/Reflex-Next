from __future__ import annotations

from dataclasses import dataclass

import pytest

from reflex_runtime.plugin_contracts import ProviderDescriptor
from reflex_runtime.provider_errors import ProviderRuntimeError
from reflex_runtime.provider_registry import (
    TRUSTED_PROVIDER_RELEASE_STATUS,
    ProviderConfig,
    ProviderRegistry,
)
from reflex_runtime.provider_profiles import (
    ModelCapabilityProfile,
    ProtocolProfile,
)


@dataclass
class RecordingProvider:
    id: str
    model: str

    def stream(self, rendered_request, request, cancellation):
        return iter(())

    def list_models(self):
        return ("model-a", "model-b")

    def test_connection(self, model):
        return model in self.list_models()


class RecordingFactory:
    id = "minimax"
    display_name = "MiniMax"
    version = "0.1.0"
    models = ("model-a", "model-b")
    default_model = "model-a"
    required_secret = "api_key"
    permissions = ("network",)
    default_base_url = "https://api.example.test/v1/chat/completions"
    protocol = "openai_chat_completions"
    accepts_custom_models = False
    model_capabilities = {
        "model-a": {"context_window": 32_768, "supports_json": True},
    }

    def __init__(self) -> None:
        self.calls: list[tuple[str, ProviderConfig]] = []

    def create(self, secret: str, config: ProviderConfig) -> RecordingProvider:
        self.calls.append((secret, config))
        return RecordingProvider(self.id, config.model)


def test_runtime_owns_the_read_only_v1_provider_release_policy():
    assert dict(TRUSTED_PROVIDER_RELEASE_STATUS) == {
        "anthropic": "experimental",
        "gemini": "experimental",
        "minimax": "supported",
        "deepseek": "experimental",
        "qwen": "experimental",
        "zhipu": "experimental",
        "siliconflow": "experimental",
        "openai-responses": "experimental",
    }
    with pytest.raises(TypeError):
        TRUSTED_PROVIDER_RELEASE_STATUS["qwen"] = "supported"


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


def test_registry_provider_probe_is_transient_and_returns_safe_results():
    factory = RecordingFactory()
    registry = ProviderRegistry({"minimax": factory})

    models = registry.discover_models(
        "minimax", "fixture-private-credential", {"model": "model-a"}
    )
    connected = registry.test_connection(
        "minimax", "fixture-private-credential", {"model": "model-a"}
    )

    assert models == ("model-a", "model-b")
    assert connected is True
    assert registry.catalog()[0].session_configured is False


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
    assert config.protocol == ProtocolProfile("openai_chat_completions")
    assert config.model_capabilities == ModelCapabilityProfile(
        context_window=32_768,
        supports_json=True,
    )


def test_registry_accepts_safe_custom_model_when_factory_declares_support():
    factory = RecordingFactory()
    factory.accepts_custom_models = True
    registry = ProviderRegistry({"minimax": factory})

    registry.configure("minimax", "fixture-secret", {"model": "gpt-5.6-luna"})

    configured = factory.calls[0][1]
    assert configured.model == "gpt-5.6-luna"
    assert configured.model_capabilities == ModelCapabilityProfile()
    assert registry.resolve("minimax", "gpt-5.6-luna").model == "gpt-5.6-luna"


@pytest.mark.parametrize("model", [" unsafe", "unsafe\nmodel", "", "x" * 257])
def test_registry_rejects_unsafe_custom_model_ids(model):
    factory = RecordingFactory()
    factory.accepts_custom_models = True
    registry = ProviderRegistry({"minimax": factory})

    with pytest.raises(ProviderRuntimeError) as caught:
        registry.configure("minimax", "fixture-secret", {"model": model})

    assert caught.value.code == "provider_invalid_response"


def test_profile_contracts_reject_unknown_protocol_and_invalid_capabilities():
    with pytest.raises(ValueError, match="unsupported provider protocol"):
        ProtocolProfile("vendor_magic")
    with pytest.raises(ValueError, match="context_window"):
        ModelCapabilityProfile(context_window=0)


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
        {"model": "model-a", "ca_bundle_path": "certs/root.pem"},
        {"model": "model-a", "ca_bundle_path": "file:///C:/certs/root.pem"},
        {"model": "model-a", "ca_bundle_path": r"\\server\share\root.pem"},
        {"model": "model-a", "ca_bundle_path": r"\\?\C:\certs\root.pem"},
        {"model": "model-a", "ca_bundle_path": r"C:\certs\..\root.pem"},
        {"model": "model-a", "ca_bundle_path": "C:\\certs\\root\n.pem"},
        {"model": "model-a", "ca_bundle_path": r"C:\certs\CON.pem"},
        {"model": "model-a", "ca_bundle_path": r"C:\certs\root.txt"},
    ],
)
def test_registry_rejects_invalid_provider_configuration(raw_config):
    registry = ProviderRegistry({"minimax": RecordingFactory()})

    with pytest.raises(ProviderRuntimeError) as caught:
        registry.configure("minimax", "fixture-secret", raw_config)

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.action == "settings"


@pytest.mark.parametrize(
    "ca_bundle_path",
    [
        r"C:\certs\root.pem",
        r"D:\Reflex Certificates\company-root.CRT",
        r"E:/certificates/company.cer",
        "/etc/ssl/certs/company.pem",
    ],
)
def test_registry_accepts_local_absolute_certificate_bundle_paths(ca_bundle_path):
    factory = RecordingFactory()
    registry = ProviderRegistry({"minimax": factory})

    registry.configure(
        "minimax",
        "fixture-secret",
        {"model": "model-a", "ca_bundle_path": ca_bundle_path},
    )

    assert factory.calls[0][1].ca_bundle_path == ca_bundle_path


def test_registry_catalog_is_stable_and_ignores_factory_claimed_release_status():
    qwen = RecordingFactory()
    qwen.id = "qwen"
    qwen.display_name = "Qwen"
    qwen.models = ("qwen-2", "qwen-1")
    qwen.default_model = "qwen-1"
    qwen.release_status = "supported"
    registry = ProviderRegistry({"qwen": qwen, "minimax": RecordingFactory()})

    catalog = registry.catalog()

    assert catalog == (
        ProviderDescriptor(
            provider_id="minimax",
            display_name="MiniMax",
            models=("model-a", "model-b"),
            default_model="model-a",
            release_status="supported",
            session_configured=False,
        ),
        ProviderDescriptor(
            provider_id="qwen",
            display_name="Qwen",
            models=("qwen-2", "qwen-1"),
            default_model="qwen-1",
            release_status="experimental",
            session_configured=False,
        ),
    )
    assert isinstance(catalog, tuple)
    assert isinstance(catalog[0].models, tuple)


def test_registry_catalog_only_tracks_configuration_in_the_current_runtime_session():
    registry = ProviderRegistry({"minimax": RecordingFactory()})
    secret = "catalog-private-secret"
    private_url = "https://private-gateway.example.test/v1/chat/completions"

    before = registry.catalog()
    registry.configure(
        "minimax",
        secret,
        {"model": "model-b", "base_url": private_url},
    )
    after = registry.catalog()

    assert before[0].session_configured is False
    assert after[0].session_configured is True
    assert before[0].models == after[0].models
    assert before[0].default_model == after[0].default_model == "model-a"
    visible = repr(after) + repr(registry)
    assert secret not in visible
    assert private_url not in visible


def test_registry_catalog_allows_no_discovered_provider():
    assert ProviderRegistry({}).catalog() == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_id": "Unsafe.Provider"},
        {"display_name": " unsafe"},
        {"models": ["model-a"]},
        {"models": ("model-a", "model-a")},
        {"models": ({"not": "a model id"},)},
        {"models": tuple(f"model-{index}" for index in range(257))},
        {"default_model": "missing-model"},
        {"release_status": "stable"},
        {"session_configured": "yes"},
    ],
)
def test_provider_descriptor_rejects_non_contract_fields(overrides):
    values = {
        "provider_id": "minimax",
        "display_name": "MiniMax",
        "models": ("model-a",),
        "default_model": "model-a",
        "release_status": "supported",
        "session_configured": False,
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        ProviderDescriptor(**values)
