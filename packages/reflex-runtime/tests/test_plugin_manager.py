from __future__ import annotations

from dataclasses import dataclass

import pytest

from reflex_runtime.plugin_contracts import PluginDescriptor
from reflex_runtime.plugin_manager import BUILTIN_CAPABILITY_DESCRIPTORS, PluginManager


@dataclass
class FakeFactory:
    id: str = "minimax"
    display_name: str = "MiniMax"
    version: str = "0.1.0"
    models: tuple[str, ...] = ("model-a", "model-b")
    default_model: str = "model-a"
    required_secret: str = "api_key"
    permissions: tuple[str, ...] = ("network",)
    default_base_url: str = "https://api.example.test/v1/chat/completions"

    def create(self, secret, config):
        raise AssertionError("discovery must not create provider instances")


class FakeEntryPoint:
    def __init__(self, name: str, loaded=None, error: Exception | None = None) -> None:
        self.name = name
        self._loaded = loaded
        self._error = error

    def load(self):
        if self._error is not None:
            raise self._error
        return self._loaded


class FakeCapability:
    def __init__(self, descriptor: PluginDescriptor) -> None:
        self.descriptor = descriptor

    def invoke(self, operation, payload, services, cancellation):
        return None


def capability_descriptor(
    plugin_id: str,
    kind: str,
    operations: tuple[str, ...],
    public_operations: tuple[str, ...] | None = None,
    permissions: tuple[str, ...] | None = None,
):
    display_names = {
        "history-sqlite": "History",
        "translator": "Translator",
        "markdown-preview": "Markdown Preview",
        "semantic-detector": "Semantic Detector",
    }
    return PluginDescriptor(
        plugin_id=plugin_id,
        display_name=display_names.get(plugin_id, plugin_id),
        version="1",
        kind=kind,
        permissions=("network-via-provider",)
        if permissions is None and plugin_id == "translator"
        else (permissions or ()),
        operations=operations,
        public_operations=operations if public_operations is None else public_operations,
    )


HISTORY_OPERATIONS = (
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
)
HISTORY_PUBLIC_OPERATIONS = ("list", "detail", "rate", "backups", "scan")


def test_entry_point_failure_does_not_block_an_allowed_provider_factory():
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("broken", error=RuntimeError("raw traceback detail")),
            FakeEntryPoint("minimax", loaded=lambda: FakeFactory()),
        ]
    )

    result = manager.discover_provider_factories()

    assert tuple(result.factories) == ("minimax",)
    assert result.factories["minimax"].display_name == "MiniMax"
    assert len(result.failures) == 1
    assert result.failures[0].plugin_id == "broken"
    assert result.failures[0].safe_message == "Provider plugin unavailable."
    assert "traceback" not in repr(result.failures).lower()


def test_development_loading_imports_only_explicit_module_names():
    imported: list[str] = []

    class Module:
        @staticmethod
        def plugin():
            return FakeFactory()

    def module_loader(name: str):
        imported.append(name)
        return Module

    manager = PluginManager(
        entry_points_loader=lambda: [],
        development_modules=("reflex_provider_minimax",),
        module_loader=module_loader,
    )

    result = manager.discover_provider_factories()

    assert imported == ["reflex_provider_minimax"]
    assert tuple(result.factories) == ("minimax",)


def test_duplicate_provider_ids_keep_the_first_factory_and_report_a_safe_failure():
    first = FakeFactory(display_name="First")
    second = FakeFactory(display_name="Second")
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("minimax", loaded=lambda: first),
            FakeEntryPoint("minimax", loaded=lambda: second),
        ]
    )

    result = manager.discover_provider_factories()

    assert result.factories["minimax"] is first
    assert result.failures == (
        result.failures[0],
    )
    assert result.failures[0].plugin_id == "minimax"
    assert result.failures[0].safe_message == "Provider plugin unavailable."


def test_unapproved_provider_metadata_is_not_registered():
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("unexpected", loaded=lambda: FakeFactory(id="unexpected"))
        ]
    )

    result = manager.discover_provider_factories()

    assert result.factories == {}
    assert result.failures[0].plugin_id == "unexpected"


def test_unapproved_provider_entry_point_is_rejected_before_load():
    loads = []

    class TrackingEntryPoint(FakeEntryPoint):
        def load(self):
            loads.append(self.name)
            return super().load()

    entry_point = TrackingEntryPoint("unexpected", loaded=lambda: FakeFactory())
    manager = PluginManager(entry_points_loader=lambda: [entry_point])

    result = manager.discover_provider_factories()

    assert result.factories == {}
    assert result.failures[0].plugin_id == "unexpected"
    assert loads == []


def test_provider_factory_id_must_match_normalized_entry_point_name():
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("minimax", loaded=lambda: FakeFactory(id="other"))
        ],
        allowed_provider_ids=frozenset({"minimax", "other"}),
    )

    result = manager.discover_provider_factories()

    assert result.factories == {}
    assert result.failures[0].plugin_id == "minimax"


@pytest.mark.parametrize(
    "factory",
    [
        FakeFactory(display_name="unsafe\nname"),
        FakeFactory(display_name=" x" * 81),
        FakeFactory(models=("model-a", "model-a")),
        FakeFactory(models=("model-a", " unsafe-model")),
        FakeFactory(models=("model-a", "unsafe\rmodel")),
        FakeFactory(models=({"not": "a model id"},)),
        FakeFactory(models=tuple(f"model-{index}" for index in range(257))),
    ],
)
def test_provider_factory_with_unsafe_catalog_metadata_is_isolated(factory):
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("minimax", loaded=lambda: factory)
        ]
    )

    result = manager.discover_provider_factories()

    assert result.factories == {}
    assert result.failures[0].plugin_id == "minimax"


def test_provider_failure_preserves_an_existing_safe_dotted_entry_point_id():
    manager = PluginManager(
        entry_points_loader=lambda: [
            FakeEntryPoint("vendor.provider", error=RuntimeError("fixture failure"))
        ]
    )

    result = manager.discover_provider_factories()

    assert result.failures[0].plugin_id == "vendor.provider"


def test_capability_discovery_checks_builtin_name_before_loading_entry_point():
    loaded: list[str] = []

    class TrackingEntryPoint(FakeEntryPoint):
        def load(self):
            loaded.append(self.name)
            return super().load()

    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            TrackingEntryPoint(
                "unknown-command",
                loaded=FakeCapability(
                    capability_descriptor("unknown-command", "command", ("run",))
                ),
            )
        ]
        if group == "reflex.commands"
        else [],
        enabled_plugins={"unknown-command"},
    )

    result = manager.discover_capabilities()

    assert loaded == []
    assert "unknown-command" not in result.plugins
    assert any(failure.code == "plugin_not_allowed" for failure in result.failures)


def test_disabled_capability_is_described_without_import_or_resource_creation():
    entry_point = FakeEntryPoint(
        "translator",
        error=AssertionError("disabled plugin must not be imported"),
    )
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [entry_point]
        if group == "reflex.transformers"
        else [],
        enabled_plugins=set(),
    )

    result = manager.discover_capabilities()
    translator = next(
        item for item in result.descriptors if item.plugin_id == "translator"
    )

    assert "translator" not in result.plugins
    assert translator.enabled is False
    assert translator.state == "disabled"


def test_enabling_a_disabled_capability_lazily_loads_it_once():
    loads = []
    translator = FakeCapability(
        capability_descriptor("translator", "transformer", ("translate",))
    )

    class TrackingEntryPoint(FakeEntryPoint):
        def load(self):
            loads.append(self.name)
            return super().load()

    entry_point = TrackingEntryPoint("translator", translator)
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [entry_point]
        if group == "reflex.transformers"
        else [],
        enabled_plugins=set(),
    )

    manager.discover_capabilities()
    manager.configure_enabled_plugin("translator", True)
    first_enabled = manager.discover_capabilities()
    second_enabled = manager.discover_capabilities()

    assert loads == ["translator"]
    assert first_enabled.plugins == {"translator": translator}
    assert second_enabled.plugins == {"translator": translator}


def test_capability_failure_is_isolated_and_exposes_only_safe_unavailable_code():
    private_detail = "C:\\private\\plugin.py raw traceback"
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            FakeEntryPoint("translator", error=RuntimeError(private_detail))
        ]
        if group == "reflex.transformers"
        else [],
        enabled_plugins={"translator"},
    )

    result = manager.discover_capabilities()
    translator = next(
        item for item in result.descriptors if item.plugin_id == "translator"
    )

    assert translator.state == "unavailable"
    assert translator.error_code == "plugin_unavailable"
    assert result.failures[0].code == "plugin_unavailable"
    assert private_detail not in repr(result)


def test_duplicate_allowed_capability_candidates_are_never_loaded():
    loads: list[str] = []
    translator = FakeCapability(
        capability_descriptor("translator", "transformer", ("translate",))
    )

    class TrackingEntryPoint(FakeEntryPoint):
        def load(self):
            loads.append(self.name)
            return super().load()

    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            TrackingEntryPoint("translator", translator),
            TrackingEntryPoint("translator", translator),
        ]
        if group == "reflex.transformers"
        else [],
        enabled_plugins={"translator"},
    )

    result = manager.discover_capabilities()
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "translator"
    )

    assert loads == []
    assert "translator" not in result.plugins
    assert descriptor.state == "unavailable"
    assert descriptor.error_code == "plugin_unavailable"
    assert [failure.plugin_id for failure in result.failures].count("translator") == 1


def test_capability_groups_load_valid_builtins_and_represent_absent_history():
    translator = FakeCapability(
        capability_descriptor("translator", "transformer", ("translate",))
    )
    markdown = FakeCapability(
        capability_descriptor(
            "markdown-preview",
            "command",
            ("preview", "export"),
            ("preview",),
        )
    )
    by_group = {
        "reflex.storage": [],
        "reflex.transformers": [FakeEntryPoint("translator", translator)],
        "reflex.commands": [FakeEntryPoint("markdown-preview", markdown)],
        "reflex.model_managers": [],
    }
    manager = PluginManager(
        capability_entry_points_loader=lambda group: by_group[group],
        enabled_plugins={"translator", "markdown-preview"},
    )

    result = manager.discover_capabilities()

    assert result.plugins == {
        "translator": translator,
        "markdown-preview": markdown,
    }
    states = {item.plugin_id: item.state for item in result.descriptors}
    assert states == {
        "history-sqlite": "absent",
        "batch-runner": "absent",
        "semantic-detector": "absent",
        "translator": "available",
        "markdown-preview": "available",
    }
    translator_descriptor = next(
        item for item in result.descriptors if item.plugin_id == "translator"
    )
    assert translator_descriptor.permissions == ("network-via-provider",)


def test_semantic_model_manager_is_loaded_only_when_enabled():
    semantic = FakeCapability(
        capability_descriptor(
            "semantic-detector",
            "command",
            ("status", "download", "delete"),
            permissions=("model_cache", "network"),
        )
    )
    loader = lambda group: (
        [FakeEntryPoint("semantic-detector", semantic)]
        if group == "reflex.model_managers"
        else []
    )

    disabled = PluginManager(capability_entry_points_loader=loader).discover_capabilities()
    enabled = PluginManager(
        capability_entry_points_loader=loader,
        enabled_plugins={"semantic-detector"},
    ).discover_capabilities()

    assert "semantic-detector" not in disabled.plugins
    assert next(
        item for item in disabled.descriptors if item.plugin_id == "semantic-detector"
    ).state == "disabled"
    assert enabled.plugins["semantic-detector"] is semantic


def test_conforming_history_plugin_loads_with_the_canonical_operation_contract():
    history = FakeCapability(
        capability_descriptor(
            "history-sqlite",
            "storage",
            HISTORY_OPERATIONS,
            HISTORY_PUBLIC_OPERATIONS,
            ("storage_read", "storage_write"),
        )
    )
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            FakeEntryPoint("history-sqlite", history)
        ]
        if group == "reflex.storage"
        else [],
    )

    result = manager.discover_capabilities()

    assert result.plugins["history-sqlite"] is history
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "history-sqlite"
    )
    assert descriptor.operations == HISTORY_OPERATIONS
    assert descriptor.public_operations == HISTORY_PUBLIC_OPERATIONS
    assert descriptor.permissions == ("storage_read", "storage_write")


def test_independent_history_descriptor_is_normalized_to_runtime_builtin_contract():
    class ForeignDescriptor:
        plugin_id = "history-sqlite"
        display_name = "History"
        version = "1"
        kind = "storage"
        permissions = ("storage_read", "storage_write")
        operations = HISTORY_OPERATIONS
        public_operations = HISTORY_PUBLIC_OPERATIONS

    class ForeignHistory:
        descriptor = ForeignDescriptor()

        def invoke(self, operation, payload, services, cancellation):
            return None

    history = ForeignHistory()
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            FakeEntryPoint("history-sqlite", history)
        ]
        if group == "reflex.storage"
        else [],
    )

    result = manager.discover_capabilities()

    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "history-sqlite"
    )
    assert descriptor == BUILTIN_CAPABILITY_DESCRIPTORS["history-sqlite"]
    assert result.plugins["history-sqlite"] is history


def test_history_descriptor_with_noncanonical_display_or_version_is_rejected():
    class ForeignDescriptor:
        plugin_id = "history-sqlite"
        display_name = "Alternate History"
        version = "fixture-1"
        kind = "storage"
        permissions = ("storage_read", "storage_write")
        operations = HISTORY_OPERATIONS
        public_operations = HISTORY_PUBLIC_OPERATIONS

    history = FakeCapability(capability_descriptor("translator", "transformer", ("translate",)))
    history.descriptor = ForeignDescriptor()
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            FakeEntryPoint("history-sqlite", history)
        ]
        if group == "reflex.storage"
        else [],
    )

    result = manager.discover_capabilities()

    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "history-sqlite"
    )
    assert "history-sqlite" not in result.plugins
    assert descriptor.state == "unavailable"


def test_history_plugin_with_legacy_operation_alias_is_rejected():
    legacy_operations = tuple(
        "get" if operation == "detail" else operation
        for operation in HISTORY_OPERATIONS
    )
    history = FakeCapability(
        capability_descriptor(
            "history-sqlite",
            "storage",
            legacy_operations,
            tuple(
                "get" if operation == "detail" else operation
                for operation in HISTORY_PUBLIC_OPERATIONS
            ),
            ("storage_read", "storage_write"),
        )
    )
    manager = PluginManager(
        capability_entry_points_loader=lambda group: [
            FakeEntryPoint("history-sqlite", history)
        ]
        if group == "reflex.storage"
        else [],
    )

    result = manager.discover_capabilities()

    assert "history-sqlite" not in result.plugins
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "history-sqlite"
    )
    assert descriptor.state == "unavailable"
    assert result.failures[0].code == "plugin_unavailable"


def test_capability_development_loading_imports_only_explicit_fixed_modules():
    imported: list[str] = []
    translator = FakeCapability(
        capability_descriptor("translator", "transformer", ("translate",))
    )

    class Module:
        plugin = translator

    manager = PluginManager(
        capability_entry_points_loader=lambda group: [],
        development_capability_modules=(("translator", "fixture_translator"),),
        module_loader=lambda name: imported.append(name) or Module,
        enabled_plugins={"translator"},
    )

    result = manager.discover_capabilities()

    assert imported == ["fixture_translator"]
    assert result.plugins == {"translator": translator}
