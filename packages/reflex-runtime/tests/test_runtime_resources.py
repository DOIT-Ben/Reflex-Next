from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from reflex_core import OptimizeRequest, SceneDetectionResult
from reflex_core.template import TemplatePackError

import reflex_runtime.context as runtime_context


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_builtin_template_pack_path_uses_source_repository_layout(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert runtime_context._builtin_template_pack_path() == (
        REPOSITORY_ROOT / "template-packs" / "builtin"
    )


def test_builtin_template_pack_path_uses_pyinstaller_bundle_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert runtime_context._builtin_template_pack_path() == (
        tmp_path / "template-packs" / "builtin"
    )


def test_builtin_template_resolver_fails_health_initialization_when_pack_is_missing(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(runtime_context, "_builtin_template_pack_path", lambda: tmp_path / "missing")

    with pytest.raises(TemplatePackError):
        runtime_context._builtin_template_resolver()


def test_builtin_template_resolver_preserves_a_non_general_scene():
    rendered = runtime_context._builtin_template_resolver().render(
        OptimizeRequest(text="review this", scene="code_review", scene_policy="manual"),
        SceneDetectionResult(scene="code_review", confidence=1.0, method="manual"),
    )

    assert rendered["scene"] == "code_review"


def test_sidecar_build_embeds_native_provider_and_builtin_templates():
    source = (REPOSITORY_ROOT / "tools" / "build_runtime_sidecar.ps1").read_text(
        encoding="utf-8"
    )

    registry = json.loads(
        (REPOSITORY_ROOT / "tools" / "project-registry.json").read_text(encoding="utf-8")
    )
    native_provider = next(
        project
        for project in registry["projects"]
        if project["id"] == "provider-native-protocols"
    )
    assert native_provider["sidecar"] is True
    assert native_provider["module"] == "reflex_provider_native_protocols"
    assert "project_registry.ps1" in source
    assert "Get-ReflexProjectRegistry" in source
    assert "$_ .module".replace(" ", "") in source
    assert "$_ .package_name".replace(" ", "") in source
    assert '"--collect-submodules"' in source
    assert '"--copy-metadata"' in source
    assert '"--add-data"' in source
    assert 'template-packs\\builtin' in source
