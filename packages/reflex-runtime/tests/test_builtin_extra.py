from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from reflex_runtime.plugin_manager import PluginManager


RUNTIME_ROOT = Path(__file__).resolve().parents[1]


def test_history_storage_is_only_an_explicit_local_builtin_extra():
    config = tomllib.loads((RUNTIME_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["project"]["dependencies"] == ["httpx>=0.28,<0.29"]
    assert config["project"]["optional-dependencies"]["builtins"] == [
        "reflex-history-sqlite"
    ]
    assert config["tool"]["uv"]["sources"]["reflex-history-sqlite"] == {
        "path": "../../plugins/history-sqlite",
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
