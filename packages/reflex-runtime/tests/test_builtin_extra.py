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

    assert config["project"]["dependencies"] == ["httpx>=0.28,<0.29"]
    assert config["project"]["optional-dependencies"]["builtins"] == [
        "reflex-history-sqlite",
        "reflex-translator",
    ]
    assert config["tool"]["uv"]["sources"]["reflex-history-sqlite"] == {
        "path": "../../plugins/history-sqlite",
        "editable": True,
    }
    assert config["tool"]["uv"]["sources"]["reflex-translator"] == {
        "path": "../../plugins/translator",
        "editable": True,
    }


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
