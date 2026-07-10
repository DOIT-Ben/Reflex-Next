"""Provider plugin discovery with an allowlist and failure isolation."""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import ModuleType
from typing import Any

PLUGIN_UNAVAILABLE_MESSAGE = "Provider plugin unavailable."
DEFAULT_ALLOWED_PROVIDER_IDS = frozenset({"minimax"})


@dataclass(frozen=True)
class PluginFailure:
    plugin_id: str
    safe_message: str = PLUGIN_UNAVAILABLE_MESSAGE


@dataclass(frozen=True)
class PluginDiscoveryResult:
    factories: dict[str, Any]
    failures: tuple[PluginFailure, ...]


class PluginManager:
    def __init__(
        self,
        *,
        entry_points_loader: Callable[[], Iterable[Any]] | None = None,
        development_modules: tuple[str, ...] = (),
        module_loader: Callable[[str], ModuleType | Any] = importlib.import_module,
        allowed_provider_ids: frozenset[str] = DEFAULT_ALLOWED_PROVIDER_IDS,
    ) -> None:
        self._entry_points_loader = entry_points_loader or _provider_entry_points
        self._development_modules = tuple(development_modules)
        self._module_loader = module_loader
        self._allowed_provider_ids = allowed_provider_ids

    def discover_provider_factories(self) -> PluginDiscoveryResult:
        factories: dict[str, Any] = {}
        failures: list[PluginFailure] = []

        for entry_point in self._entry_points_loader():
            source_id = _safe_source_id(getattr(entry_point, "name", "unknown"))
            try:
                loaded = entry_point.load()
                factory = _materialize_factory(loaded)
                self._register_factory(factories, factory)
            except Exception:
                failures.append(PluginFailure(source_id))

        for module_name in self._development_modules:
            source_id = _safe_source_id(module_name.rsplit(".", 1)[-1])
            try:
                module = self._module_loader(module_name)
                factory = _materialize_factory(getattr(module, "plugin"))
                self._register_factory(factories, factory)
            except Exception:
                failures.append(PluginFailure(source_id))

        return PluginDiscoveryResult(factories=factories, failures=tuple(failures))

    def _register_factory(self, factories: dict[str, Any], factory: Any) -> None:
        provider_id = _validate_factory(factory)
        if provider_id not in self._allowed_provider_ids or provider_id in factories:
            raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
        factories[provider_id] = factory


def _provider_entry_points() -> Iterable[Any]:
    return importlib.metadata.entry_points(group="reflex.providers")


def _materialize_factory(loaded: Any) -> Any:
    if callable(loaded) and not hasattr(loaded, "id"):
        return loaded()
    return loaded


def _validate_factory(factory: Any) -> str:
    provider_id = getattr(factory, "id", None)
    if not isinstance(provider_id, str):
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
    provider_id = provider_id.strip().lower()
    if not _safe_identifier(provider_id):
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)

    for field_name in ("display_name", "version", "default_model", "required_secret"):
        value = getattr(factory, field_name, None)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)

    models = getattr(factory, "models", None)
    if not isinstance(models, tuple) or not models or not all(isinstance(model, str) and model for model in models):
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
    if factory.default_model not in models:
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)

    permissions = getattr(factory, "permissions", None)
    if not isinstance(permissions, tuple) or any(permission not in {"network"} for permission in permissions):
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
    if not callable(getattr(factory, "create", None)):
        raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
    return provider_id


def _safe_source_id(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    normalized = value.strip().lower()
    return normalized if _safe_identifier(normalized) else "unknown"


def _safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 64 and all(
        character.isascii() and (character.isalnum() or character in "-_.")
        for character in value
    )
