"""Allowlisted Provider and capability plugin discovery."""

from __future__ import annotations

import importlib
import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any

from .plugin_contracts import PluginDescriptor, PluginFailure

PLUGIN_UNAVAILABLE_MESSAGE = "Provider plugin unavailable."
DEFAULT_ALLOWED_PROVIDER_IDS = frozenset({"minimax"})


@dataclass(frozen=True)
class PluginDiscoveryResult:
    factories: dict[str, Any]
    failures: tuple[PluginFailure, ...]


@dataclass(frozen=True)
class CapabilityDiscoveryResult:
    plugins: dict[str, Any]
    descriptors: tuple[PluginDescriptor, ...]
    failures: tuple[PluginFailure, ...]


CAPABILITY_GROUPS = {
    "reflex.storage": frozenset({"history-sqlite"}),
    "reflex.transformers": frozenset({"translator"}),
    "reflex.commands": frozenset({"markdown-preview"}),
}
BUILTIN_CAPABILITY_DESCRIPTORS = {
    "history-sqlite": PluginDescriptor(
        plugin_id="history-sqlite",
        display_name="History",
        version="1",
        kind="storage",
        # Keep read/write capabilities distinct: registry write gates depend on these names.
        permissions=("storage_read", "storage_write"),
        operations=(
            "save",
            "list",
            "detail",
            "rate",
            "delete",
            "clear",
            "export",
            "scan",
            "repair",
            "backups",
            "restore",
            "rotate",
        ),
        public_operations=("list", "detail", "rate", "backups", "scan"),
    ),
    "translator": PluginDescriptor(
        plugin_id="translator",
        display_name="Translator",
        version="1",
        kind="transformer",
        permissions=(),
        operations=("translate",),
        public_operations=("translate",),
    ),
    "markdown-preview": PluginDescriptor(
        plugin_id="markdown-preview",
        display_name="Markdown Preview",
        version="1",
        kind="command",
        permissions=(),
        operations=("preview", "export"),
        public_operations=("preview",),
    ),
}


class PluginManager:
    def __init__(
        self,
        *,
        entry_points_loader: Callable[[], Iterable[Any]] | None = None,
        development_modules: tuple[str, ...] = (),
        module_loader: Callable[[str], ModuleType | Any] = importlib.import_module,
        allowed_provider_ids: frozenset[str] = DEFAULT_ALLOWED_PROVIDER_IDS,
        capability_entry_points_loader: Callable[[str], Iterable[Any]] | None = None,
        development_capability_modules: tuple[tuple[str, str], ...] = (),
        enabled_plugins: set[str] | frozenset[str] | None = None,
    ) -> None:
        self._entry_points_loader = entry_points_loader or _provider_entry_points
        self._development_modules = tuple(development_modules)
        self._module_loader = module_loader
        self._allowed_provider_ids = frozenset(
            provider_id.strip().lower() for provider_id in allowed_provider_ids
        )
        self._capability_entry_points_loader = (
            capability_entry_points_loader or _capability_entry_points
        )
        self._development_capability_modules = tuple(development_capability_modules)
        self._enabled_plugins = set(enabled_plugins or ())
        self._capability_cache: dict[str, tuple[PluginDescriptor, Any]] = {}

    def configure_enabled_plugin(self, plugin_id: str, enabled: bool) -> None:
        if plugin_id not in {"translator", "markdown-preview"}:
            raise ValueError("plugin configuration denied")
        if not isinstance(enabled, bool):
            raise ValueError("plugin configuration denied")
        if enabled:
            self._enabled_plugins.add(plugin_id)
        else:
            self._enabled_plugins.discard(plugin_id)

    def discover_provider_factories(self) -> PluginDiscoveryResult:
        factories: dict[str, Any] = {}
        failures: list[PluginFailure] = []

        for entry_point in self._entry_points_loader():
            source_id = _safe_source_id(getattr(entry_point, "name", "unknown"))
            if source_id not in self._allowed_provider_ids:
                failures.append(PluginFailure(source_id))
                continue
            try:
                loaded = entry_point.load()
                factory = _materialize_factory(loaded)
                provider_id = _validate_factory(factory)
                if provider_id != source_id:
                    raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
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

    def discover_capabilities(self) -> CapabilityDiscoveryResult:
        collected: dict[str, list[Any]] = {}
        failures: list[PluginFailure] = []

        for group, allowed_ids in CAPABILITY_GROUPS.items():
            for entry_point in self._capability_entry_points_loader(group):
                source_id = _safe_source_id(getattr(entry_point, "name", "unknown"))
                if source_id not in allowed_ids:
                    failures.append(PluginFailure(source_id, "plugin_not_allowed"))
                    continue
                collected.setdefault(source_id, []).append(entry_point)

        for plugin_id, module_name in self._development_capability_modules:
            if plugin_id not in BUILTIN_CAPABILITY_DESCRIPTORS:
                failures.append(
                    PluginFailure(_safe_source_id(plugin_id), "plugin_not_allowed")
                )
                continue
            collected.setdefault(plugin_id, []).append(
                _DevelopmentCapability(module_name)
            )

        candidates: dict[str, Any] = {}
        forced_unavailable: set[str] = set()
        for plugin_id, plugin_candidates in collected.items():
            if len(plugin_candidates) != 1:
                forced_unavailable.add(plugin_id)
                self._capability_cache.pop(plugin_id, None)
                failures.append(PluginFailure(plugin_id, "plugin_unavailable"))
                continue
            candidates[plugin_id] = plugin_candidates[0]

        plugins: dict[str, Any] = {}
        descriptors: list[PluginDescriptor] = []
        for plugin_id, builtin in BUILTIN_CAPABILITY_DESCRIPTORS.items():
            candidate = candidates.get(plugin_id)
            if plugin_id in forced_unavailable:
                descriptors.append(
                    replace(
                        builtin,
                        enabled=False,
                        state="unavailable",
                        error_code="plugin_unavailable",
                    )
                )
                continue
            if candidate is None:
                descriptors.append(replace(builtin, enabled=False, state="absent"))
                continue
            if plugin_id in {"translator", "markdown-preview"} and (
                plugin_id not in self._enabled_plugins
            ):
                descriptors.append(replace(builtin, enabled=False, state="disabled"))
                continue
            cached = self._capability_cache.get(plugin_id)
            if cached is not None:
                descriptor, instance = cached
                plugins[plugin_id] = instance
                descriptors.append(replace(descriptor, enabled=True, state="available"))
                continue
            try:
                loaded = self._load_capability_candidate(candidate)
                instance = _materialize_capability(loaded)
                descriptor = _validate_capability(instance, plugin_id, builtin)
            except Exception:
                failures.append(PluginFailure(plugin_id, "plugin_unavailable", builtin.kind))
                descriptors.append(
                    replace(
                        builtin,
                        enabled=False,
                        state="unavailable",
                        error_code="plugin_unavailable",
                    )
                )
                continue
            plugins[plugin_id] = instance
            self._capability_cache[plugin_id] = (descriptor, instance)
            descriptors.append(replace(descriptor, enabled=True, state="available"))

        return CapabilityDiscoveryResult(
            plugins=plugins,
            descriptors=tuple(descriptors),
            failures=tuple(failures),
        )

    def _load_capability_candidate(self, candidate: Any) -> Any:
        if isinstance(candidate, _DevelopmentCapability):
            module = self._module_loader(candidate.module_name)
            return getattr(module, "plugin")
        return candidate.load()

    def _register_factory(self, factories: dict[str, Any], factory: Any) -> None:
        provider_id = _validate_factory(factory)
        if provider_id not in self._allowed_provider_ids or provider_id in factories:
            raise ValueError(PLUGIN_UNAVAILABLE_MESSAGE)
        factories[provider_id] = factory


def _provider_entry_points() -> Iterable[Any]:
    return importlib.metadata.entry_points(group="reflex.providers")


def _capability_entry_points(group: str) -> Iterable[Any]:
    return importlib.metadata.entry_points(group=group)


def _materialize_factory(loaded: Any) -> Any:
    if callable(loaded) and not hasattr(loaded, "id"):
        return loaded()
    return loaded


def _materialize_capability(loaded: Any) -> Any:
    if callable(loaded) and not hasattr(loaded, "descriptor"):
        return loaded()
    return loaded


def _validate_capability(
    instance: Any,
    expected_id: str,
    builtin: PluginDescriptor,
) -> PluginDescriptor:
    descriptor = getattr(instance, "descriptor", None)
    canonical_fields = (
        "plugin_id",
        "display_name",
        "version",
        "kind",
        "permissions",
        "operations",
        "public_operations",
    )
    if descriptor is None or any(
        getattr(descriptor, field, None) != getattr(builtin, field)
        for field in canonical_fields
    ):
        raise ValueError("plugin unavailable")
    if descriptor.plugin_id != expected_id:
        raise ValueError("plugin unavailable")
    if not callable(getattr(instance, "invoke", None)):
        raise ValueError("plugin unavailable")
    return builtin


@dataclass(frozen=True)
class _DevelopmentCapability:
    module_name: str


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
    return normalized if _safe_failure_source_id(normalized) else "unknown"


def _safe_failure_source_id(value: str) -> bool:
    return (
        _safe_identifier(value)
        and value[0].isalnum()
        and value[-1] != "."
        and ".." not in value
    )


def _safe_identifier(value: str) -> bool:
    return bool(value) and len(value) <= 64 and all(
        character.isascii() and (character.isalnum() or character in "-_.")
        for character in value
    )
