"""In-memory configuration and request selection for Provider plugins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from threading import RLock
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from .provider_errors import (
    ProviderRuntimeError,
    provider_configuration_invalid,
    provider_unconfigured,
)
from .plugin_contracts import ProviderDescriptor


TRUSTED_PROVIDER_RELEASE_STATUS = MappingProxyType(
    {
        "minimax": "supported",
        "deepseek": "experimental",
        "qwen": "experimental",
        "zhipu": "experimental",
        "siliconflow": "experimental",
    }
)


@dataclass(frozen=True)
class ProviderConfig:
    model: str
    base_url: str
    timeout_seconds: float = 60.0
    tls_verify: bool = True
    ca_bundle_path: str | None = None


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
        if model is not None and model not in factory.models:
            raise provider_configuration_invalid()
        return provider

    def catalog(self) -> tuple[ProviderDescriptor, ...]:
        with self._lock:
            session_configured_ids = frozenset(self._providers)
        return tuple(
            replace(
                self._descriptors[provider_id],
                session_configured=provider_id in session_configured_ids,
            )
            for provider_id in sorted(self._descriptors)
        )


def _provider_config(factory: Any, raw_config: dict[str, object]) -> ProviderConfig:
    model = raw_config.get("model", factory.default_model)
    if not isinstance(model, str) or model not in factory.models:
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
        if not ca_bundle_path or len(ca_bundle_path) > 2048:
            raise provider_configuration_invalid()

    return ProviderConfig(
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        tls_verify=True,
        ca_bundle_path=ca_bundle_path,
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
