"""In-memory configuration and request selection for Provider plugins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import PurePosixPath, PureWindowsPath
from threading import RLock
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from .provider_errors import (
    ProviderRuntimeError,
    provider_configuration_invalid,
    provider_unconfigured,
)
from .plugin_contracts import MAX_PROVIDER_MODELS, ProviderDescriptor
from .provider_profiles import ModelCapabilityProfile, ProtocolProfile


TRUSTED_PROVIDER_RELEASE_STATUS = MappingProxyType(
    {
        "anthropic": "experimental",
        "gemini": "experimental",
        "minimax": "supported",
        "deepseek": "experimental",
        "qwen": "experimental",
        "zhipu": "experimental",
        "siliconflow": "experimental",
        "openai-responses": "experimental",
    }
)


@dataclass(frozen=True)
class ProviderConfig:
    model: str
    base_url: str
    timeout_seconds: float = 60.0
    tls_verify: bool = True
    ca_bundle_path: str | None = None
    protocol: ProtocolProfile = ProtocolProfile("openai_chat_completions")
    model_capabilities: ModelCapabilityProfile = ModelCapabilityProfile()


class ProviderRegistry:
    def __init__(self, factories: Mapping[str, Any]) -> None:
        self._factories: dict[str, Any] = {}
        self._descriptors: dict[str, ProviderDescriptor] = {}
        for provider_id, factory in factories.items():
            try:
                normalized_id = _normalize_provider_id(provider_id)
                factory_id = _normalize_provider_id(getattr(factory, "id", None))
                descriptor = ProviderDescriptor(
                    provider_id=normalized_id,
                    display_name=getattr(factory, "display_name", None),
                    models=getattr(factory, "models", None),
                    default_model=getattr(factory, "default_model", None),
                    release_status=TRUSTED_PROVIDER_RELEASE_STATUS[normalized_id],
                    session_configured=False,
                )
            except Exception:
                continue
            if factory_id != normalized_id or normalized_id in self._factories:
                continue
            self._factories[normalized_id] = factory
            self._descriptors[normalized_id] = descriptor
        self._providers: dict[str, Any] = {}
        self._lock = RLock()

    def __repr__(self) -> str:
        with self._lock:
            return (
                "ProviderRegistry("
                f"factories={sorted(self._factories)!r}, "
                f"session_configured={sorted(self._providers)!r})"
            )

    def configure(
        self,
        provider_id: str,
        secret: str,
        raw_config: dict[str, object],
    ) -> None:
        normalized_id = _normalize_provider_id(provider_id)
        factory = self._factories.get(normalized_id)
        if factory is None:
            raise provider_unconfigured()
        if not isinstance(secret, str) or not secret.strip() or len(secret) > 16_384:
            raise provider_configuration_invalid()
        if not isinstance(raw_config, dict):
            raise provider_configuration_invalid()

        config = _provider_config(factory, raw_config)
        try:
            provider = factory.create(secret.strip(), config)
        except ProviderRuntimeError:
            raise
        except Exception:
            raise provider_configuration_invalid() from None
        if getattr(provider, "id", None) != normalized_id:
            raise provider_configuration_invalid()
        with self._lock:
            self._providers[normalized_id] = provider

    def resolve(self, provider_id: str, model: str | None) -> Any:
        normalized_id = _normalize_provider_id(provider_id)
        factory = self._factories.get(normalized_id)
        with self._lock:
            provider = self._providers.get(normalized_id)
        if factory is None or provider is None:
            raise provider_unconfigured()
        if model is not None and not _model_allowed(factory, model):
            raise provider_configuration_invalid()
        return provider

    def discover_models(
        self, provider_id: str, secret: str, raw_config: dict[str, object]
    ) -> tuple[str, ...]:
        provider = self._transient_provider(provider_id, secret, raw_config)
        operation = getattr(provider, "list_models", None)
        if not callable(operation):
            raise ProviderRuntimeError(
                "provider_capability_unsupported",
                "Provider does not support model discovery.",
                recoverable=False,
                action=None,
            )
        try:
            models = operation()
        except Exception as error:
            raise _probe_error(error) from None
        if not isinstance(models, tuple):
            raise provider_configuration_invalid()
        normalized = tuple(sorted(set(models)))
        if (
            not normalized
            or len(normalized) > MAX_PROVIDER_MODELS
            or any(not _safe_model_id(model) for model in normalized)
        ):
            raise provider_configuration_invalid()
        return normalized

    def test_connection(
        self, provider_id: str, secret: str, raw_config: dict[str, object]
    ) -> bool:
        provider = self._transient_provider(provider_id, secret, raw_config)
        operation = getattr(provider, "test_connection", None)
        if not callable(operation):
            raise ProviderRuntimeError(
                "provider_capability_unsupported",
                "Provider does not support connection testing.",
                recoverable=False,
                action=None,
            )
        try:
            result = operation(getattr(provider, "model", None))
        except Exception as error:
            raise _probe_error(error) from None
        if result is not True:
            raise provider_configuration_invalid()
        return True

    def _transient_provider(
        self, provider_id: str, secret: str, raw_config: dict[str, object]
    ) -> Any:
        normalized_id = _normalize_provider_id(provider_id)
        factory = self._factories.get(normalized_id)
        if factory is None:
            raise provider_unconfigured()
        if not isinstance(secret, str) or not secret.strip() or len(secret) > 16_384:
            raise provider_configuration_invalid()
        config = _provider_config(factory, raw_config)
        try:
            provider = factory.create(secret.strip(), config)
        except Exception as error:
            raise _probe_error(error) from None
        if getattr(provider, "id", None) != normalized_id:
            raise provider_configuration_invalid()
        return provider

    def catalog(self) -> tuple[ProviderDescriptor, ...]:
        with self._lock:
            configured = dict(self._providers)
        descriptors: list[ProviderDescriptor] = []
        for provider_id in sorted(self._descriptors):
            descriptor = self._descriptors[provider_id]
            provider = configured.get(provider_id)
            model = getattr(provider, "model", None)
            models = descriptor.models
            if (
                isinstance(model, str)
                and model not in models
                and len(models) < MAX_PROVIDER_MODELS
                and _safe_model_id(model)
            ):
                models = (*models, model)
            descriptors.append(
                replace(
                    descriptor,
                    models=models,
                    session_configured=provider_id in configured,
                )
            )
        return tuple(descriptors)


def _provider_config(factory: Any, raw_config: dict[str, object]) -> ProviderConfig:
    model = raw_config.get("model", factory.default_model)
    if not isinstance(model, str) or not _model_allowed(factory, model):
        raise provider_configuration_invalid()

    base_url = raw_config.get("base_url", getattr(factory, "default_base_url", None))
    if not isinstance(base_url, str):
        raise provider_configuration_invalid()
    base_url = base_url.strip()
    if not _valid_https_url(base_url):
        raise provider_configuration_invalid()

    timeout = raw_config.get("timeout_seconds", 60.0)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise provider_configuration_invalid()
    timeout_seconds = min(300.0, max(1.0, float(timeout)))

    ca_bundle_path = raw_config.get("ca_bundle_path")
    if ca_bundle_path is not None:
        if not isinstance(ca_bundle_path, str):
            raise provider_configuration_invalid()
        ca_bundle_path = ca_bundle_path.strip()
        if not _valid_ca_bundle_path(ca_bundle_path):
            raise provider_configuration_invalid()

    declared_protocol = getattr(factory, "protocol", "openai_chat_completions")
    requested_protocol = raw_config.get("protocol", declared_protocol)
    if requested_protocol != declared_protocol:
        raise provider_configuration_invalid()
    protocol = declared_protocol
    if isinstance(protocol, str):
        try:
            protocol = ProtocolProfile(protocol)
        except (TypeError, ValueError):
            raise provider_configuration_invalid() from None
    if not isinstance(protocol, ProtocolProfile):
        raise provider_configuration_invalid()
    raw_capabilities = getattr(factory, "model_capabilities", {})
    if not isinstance(raw_capabilities, Mapping):
        raise provider_configuration_invalid()
    capability_values = raw_capabilities.get(model, {})
    if isinstance(capability_values, ModelCapabilityProfile):
        capabilities = capability_values
    elif isinstance(capability_values, Mapping):
        try:
            capabilities = ModelCapabilityProfile(**dict(capability_values))
        except (TypeError, ValueError):
            raise provider_configuration_invalid() from None
    else:
        raise provider_configuration_invalid()

    return ProviderConfig(
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        tls_verify=True,
        ca_bundle_path=ca_bundle_path,
        protocol=protocol,
        model_capabilities=capabilities,
    )


def _model_allowed(factory: Any, model: str) -> bool:
    if not isinstance(model, str) or not model or len(model) > 256:
        return False
    if model != model.strip() or any(not character.isprintable() for character in model):
        return False
    models = getattr(factory, "models", ())
    if model in models:
        return True
    return bool(getattr(factory, "accepts_custom_models", False))


def _safe_model_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 256
        and value == value.strip()
        and all(character.isascii() and character.isprintable() for character in value)
    )


def _normalize_provider_id(provider_id: object) -> str:
    if not isinstance(provider_id, str):
        raise provider_unconfigured()
    normalized = provider_id.strip().lower()
    if not normalized or len(normalized) > 64 or not all(
        character.isascii() and (character.isalnum() or character in "-_.")
        for character in normalized
    ):
        raise provider_unconfigured()
    return normalized


def _valid_https_url(value: str) -> bool:
    if not value or len(value) > 2048:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def _valid_ca_bundle_path(value: str) -> bool:
    if not value or len(value) > 2048 or any(ord(character) < 32 for character in value):
        return False
    lower = value.lower()
    if value.startswith(("\\\\", "//")) or lower.startswith(("file:", "http:", "https:")):
        return False
    raw_segments = [segment for segment in value.replace("\\", "/").split("/") if segment]
    if any(
        segment in {".", ".."}
        or segment.endswith((" ", "."))
        or _reserved_windows_name(segment)
        for segment in raw_segments
        if not segment.endswith(":")
    ):
        return False
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    is_windows_absolute = (
        windows_path.is_absolute()
        and len(windows_path.drive) == 2
        and windows_path.drive[0].isalpha()
        and windows_path.drive[1] == ":"
    )
    path = windows_path if is_windows_absolute else posix_path
    return (is_windows_absolute or posix_path.is_absolute()) and path.suffix.lower() in {
        ".pem",
        ".crt",
        ".cer",
    }


def _reserved_windows_name(value: str) -> bool:
    stem = value.split(".", 1)[0].upper()
    return stem in {"CON", "PRN", "AUX", "NUL"} or (
        len(stem) == 4
        and stem[:3] in {"COM", "LPT"}
        and stem[3] in "123456789"
    )


def _probe_error(error: Exception) -> ProviderRuntimeError:
    if isinstance(error, ProviderRuntimeError):
        return error
    code = getattr(error, "code", "provider_invalid_response")
    if code not in {
        "provider_auth_failed",
        "provider_rate_limited",
        "provider_timeout",
        "provider_network_error",
        "provider_service_error",
        "provider_invalid_response",
    }:
        code = "provider_invalid_response"
    return ProviderRuntimeError(
        code,
        "Provider connection test failed.",
        recoverable=bool(getattr(error, "retryable", False)),
        action="retry" if bool(getattr(error, "retryable", False)) else "settings",
    )
