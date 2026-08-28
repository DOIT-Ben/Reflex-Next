from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
from io import StringIO
from pathlib import Path

import pytest

from reflex_runtime.plugin_manager import PluginManager
from reflex_runtime.context import RuntimeContext
from reflex_runtime.protocol import parse_command


RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def test_capability_plugins_are_only_explicit_local_builtin_extras():
    config = tomllib.loads((RUNTIME_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["project"]["dependencies"] == [
        "httpx>=0.28,<0.29",
        "reflex-core==0.7.0-alpha.8",
    ]
    assert config["project"]["optional-dependencies"]["builtins"] == [
        "reflex-history-sqlite",
        "reflex-batch-runner",
        "reflex-markdown-preview",
        "reflex-plugin-semantic-detector",
        "reflex-translator",
        "reflex-provider-minimax",
        "reflex-provider-native-protocols",
        "reflex-provider-openai-compatible",
        "reflex-provider-openai-responses",
    ]
    assert config["tool"]["uv"]["sources"]["reflex-history-sqlite"] == {
        "path": "../../plugins/history-sqlite",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-batch-runner"] == {
        "path": "../../plugins/batch-runner",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-translator"] == {
        "path": "../../plugins/translator",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-markdown-preview"] == {
        "path": "../../plugins/markdown-preview",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-plugin-semantic-detector"] == {
        "path": "../../plugins/semantic-detector",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-provider-openai-compatible"] == {
        "path": "../../plugins/provider-openai-compatible",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-provider-native-protocols"] == {
        "path": "../../plugins/provider-native-protocols",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-provider-openai-responses"] == {
        "path": "../../plugins/provider-openai-responses",
        "editable": True,
    }


def test_installed_semantic_detector_is_disabled_without_importing_optional_model_packages(
    tmp_path, monkeypatch
):
    if importlib.util.find_spec("reflex_semantic_detector") is None:
        pytest.skip("builtins extra is not installed in this environment")
    monkeypatch.chdir(tmp_path)

    manager = PluginManager()
    result = manager.discover_scene_detector()

    assert result.detector is None
    assert result.failure is None
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_installed_semantic_detector_can_be_discovered_without_loading_its_model(
    tmp_path, monkeypatch
):
    if importlib.util.find_spec("reflex_semantic_detector") is None:
        pytest.skip("builtins extra is not installed in this environment")
    monkeypatch.chdir(tmp_path)

    result = PluginManager(enabled_plugins={"semantic-detector"}).discover_scene_detector()

    assert result.detector is not None
    assert result.detector.descriptor.permissions == ("model_cache",)
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules
    assert list(tmp_path.iterdir()) == []


def test_default_runtime_package_import_does_not_load_storage_dependencies(tmp_path):
    code = (
        "import sys; import reflex_runtime; "
        "assert 'sqlite3' not in sys.modules; "
        "assert not any(name == 'cryptography' or name.startswith('cryptography.') "
        "for name in sys.modules)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_installed_builtin_history_entry_point_discovers_without_filesystem_effects(
    tmp_path, monkeypatch
):
    if importlib.util.find_spec("reflex_history_sqlite") is None:
        pytest.skip("builtins extra is not installed in this environment")
    monkeypatch.chdir(tmp_path)

    result = PluginManager().discover_capabilities()

    assert "history-sqlite" in result.plugins
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "history-sqlite"
    )
    assert descriptor.state == "available"
    assert list(tmp_path.iterdir()) == []


def test_installed_builtin_translator_discovers_with_provider_gateway_permission(
    tmp_path, monkeypatch
):
    if importlib.util.find_spec("reflex_translator") is None:
        pytest.skip("builtins extra is not installed in this environment")
    monkeypatch.chdir(tmp_path)

    manager = PluginManager(enabled_plugins={"translator"})
    result = manager.discover_capabilities()

    assert "translator" in result.plugins
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "translator"
    )
    assert descriptor.permissions == ("network-via-provider",)
    assert descriptor.state == "available"
    assert list(tmp_path.iterdir()) == []


def test_installed_markdown_preview_discovers_without_permissions_or_filesystem_effects(
    tmp_path, monkeypatch
):
    if importlib.util.find_spec("reflex_markdown_preview") is None:
        pytest.skip("builtins extra is not installed in this environment")
    monkeypatch.chdir(tmp_path)

    manager = PluginManager(enabled_plugins={"markdown-preview"})
    result = manager.discover_capabilities()

    assert "markdown-preview" in result.plugins
    descriptor = next(
        item for item in result.descriptors if item.plugin_id == "markdown-preview"
    )
    assert descriptor.permissions == ()
    assert descriptor.public_operations == ("preview",)
    assert descriptor.state == "available"
    assert list(tmp_path.iterdir()) == []


def test_development_runtime_does_not_register_the_installed_translator_twice():
    if importlib.util.find_spec("reflex_translator") is None:
        pytest.skip("builtins extra is not installed in this environment")
    output = StringIO()
    runtime = RuntimeContext(stdout=output, stderr=StringIO(), development=True)

    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "enable-translator",
                "type": "configure_plugin",
                "payload": {"plugin_id": "translator", "enabled": True},
            }
        )
    )
    runtime.handle(
        parse_command(
            {
                "version": 1,
                "request_id": "list-translator",
                "type": "list_plugins",
                "payload": {},
            }
        )
    )
    listed = json.loads(output.getvalue().splitlines()[-1])
    translator = next(item for item in listed["plugins"] if item["id"] == "translator")

    assert translator["state"] == "available"
    assert translator["enabled"] is True
