from __future__ import annotations

from dataclasses import dataclass

from reflex_runtime.plugin_manager import PluginManager


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
            FakeEntryPoint("first", loaded=lambda: first),
            FakeEntryPoint("second", loaded=lambda: second),
        ]
    )

    result = manager.discover_provider_factories()

    assert result.factories["minimax"] is first
    assert result.failures == (
        result.failures[0],
    )
    assert result.failures[0].plugin_id == "second"
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
