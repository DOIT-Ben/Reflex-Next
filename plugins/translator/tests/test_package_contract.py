from __future__ import annotations

import importlib
import tomllib
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_translator_package_is_discoverable() -> None:
    module = importlib.import_module("reflex_translator")

    assert callable(module.plugin)


def test_translator_descriptor_and_dependencies_keep_network_and_secrets_out() -> None:
    module = importlib.import_module("reflex_translator")
    instance = module.plugin()
    config = tomllib.loads((PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert instance.descriptor.plugin_id == "translator"
    assert instance.descriptor.kind == "transformer"
    assert instance.descriptor.permissions == ("network-via-provider",)
    assert instance.descriptor.operations == ("translate",)
    assert instance.descriptor.public_operations == ("translate",)
    assert config["project"]["dependencies"] == ["reflex-core"]
