import json
from pathlib import Path

import pytest

from reflex_core import OptimizeRequest, SceneDetectionResult
from reflex_core.template import FileTemplatePack, TemplatePackError, TemplatePackResolver


REPO_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_PACK_ROOT = REPO_ROOT / "template-packs" / "builtin"

EXPECTED_SCENES = (
    "general",
    "article_writing",
    "social_media",
    "email",
    "ad_creative",
    "product_desc",
    "paper_writing",
    "code_generation",
    "code_review",
    "bug_fix",
    "code_refactor",
    "tech_doc",
    "data_analysis",
    "market_research",
    "competitor_analysis",
    "literature_review",
    "trend_prediction",
    "knowledge_explain",
    "study_plan",
    "exam_prep",
    "course_design",
    "homework_help",
    "report_writing",
    "decision_analysis",
    "project_planning",
    "process_optimization",
    "meeting_summary",
    "story_writing",
    "script_writing",
    "poetry_creation",
    "game_plot",
    "world_building",
    "doc_translation",
    "localization",
    "literary_translation",
    "term_unification",
    "interpreting_notes",
    "problem_diagnosis",
    "solution_generation",
    "root_cause",
    "risk_assessment",
    "emergency_plan",
)
EXPECTED_STYLES = ("concise", "balanced", "detailed", "creative", "precise")


EXPECTED_CATEGORIES = (
    "business",
    "marketing",
    "market_analysis",
    "tech_doc",
    "code",
    "diagnosis",
    "academic",
    "education",
    "creative",
    "translation",
)


def test_builtin_pack_manifest_lists_exactly_42_scenes_and_58_assets():
    pack = FileTemplatePack.load(BUILTIN_PACK_ROOT)

    assert pack.manifest.id == "builtin"
    assert pack.manifest.version == "1.0.0"
    assert pack.manifest.supported_modes == ("content", "prompt")
    assert pack.manifest.supported_languages == ("zh-CN", "en-US")
    assert pack.scene_ids == EXPECTED_SCENES
    assert pack.style_ids == EXPECTED_STYLES
    assert pack.category_ids == EXPECTED_CATEGORIES
    assert pack.asset_count == 58
    assert all(pack.read_scene(scene_id).strip() for scene_id in pack.scene_ids)
    assert all(pack.read_style(style_id).strip() for style_id in pack.style_ids)
    assert all(pack.read_category(category_id).strip() for category_id in pack.category_ids)
    assert pack.read_system().startswith("# Role:")


def test_builtin_pack_every_scene_belongs_to_a_registered_category():
    pack = FileTemplatePack.load(BUILTIN_PACK_ROOT)

    scene_categories = pack.scene_categories
    assert set(scene_categories) == set(EXPECTED_SCENES) - {"general"}
    assert set(scene_categories.values()).issubset(set(pack.category_ids))


def test_template_resolver_renders_mode_style_scene_and_language_without_user_text_in_system():
    resolver = TemplatePackResolver(FileTemplatePack.load(BUILTIN_PACK_ROOT))
    scene = SceneDetectionResult("code_review", 1.0, "manual")

    content = resolver.render(
        OptimizeRequest(
            "Review this change without leaking it into the system message.",
            mode="content",
            style="concise",
            metadata={"language": "en-US"},
        ),
        scene,
    )
    prompt = resolver.render(
        OptimizeRequest(
            "Review this change without leaking it into the system message.",
            mode="prompt",
            style="creative",
            metadata={"language": "zh-CN"},
        ),
        scene,
    )

    content_system = content["messages"][0]["content"]
    prompt_system = prompt["messages"][0]["content"]
    assert "内容优化" in content_system
    assert "结构化提示词" in prompt_system
    assert "代码审查场景" in content_system
    assert "简洁风格" in content_system
    assert "创意风格" in prompt_system
    assert "English (US)" in content_system
    assert "简体中文" in prompt_system
    assert content_system != prompt_system
    assert content["messages"][1] == {
        "role": "user",
        "content": "Review this change without leaking it into the system message.",
    }
    assert content["messages"][1]["content"] not in content_system


def test_template_resolver_supports_category_colon_scene():
    resolver = TemplatePackResolver(FileTemplatePack.load(BUILTIN_PACK_ROOT))
    scene = SceneDetectionResult("business:email", 1.0, "manual")

    content = resolver.render(
        OptimizeRequest("hello", style="concise"),
        scene,
    )
    assert content["scene"] == "email"
    assert content["category"] == "business"
    assert "邮件撰写" in content["messages"][0]["content"]


def test_template_resolver_supports_category_only_template():
    resolver = TemplatePackResolver(FileTemplatePack.load(BUILTIN_PACK_ROOT))
    scene = SceneDetectionResult("marketing", 1.0, "manual")

    content = resolver.render(
        OptimizeRequest("hello", style="concise"),
        scene,
    )
    assert content["scene"] == "marketing"
    assert content["category"] == "marketing"
    assert "营销文案" in content["messages"][0]["content"]


def test_template_resolver_legacy_scene_keeps_category_metadata():
    resolver = TemplatePackResolver(FileTemplatePack.load(BUILTIN_PACK_ROOT))
    scene = SceneDetectionResult("email", 1.0, "manual")

    content = resolver.render(
        OptimizeRequest("hello", style="concise"),
        scene,
    )
    assert content["scene"] == "email"
    assert content["category"] == "business"


def test_template_resolver_unknown_category_falls_back_to_general():
    resolver = TemplatePackResolver(FileTemplatePack.load(BUILTIN_PACK_ROOT))
    scene = SceneDetectionResult("unknown:scene", 1.0, "manual")

    content = resolver.render(
        OptimizeRequest("hello", style="concise"),
        scene,
    )
    assert content["scene"] == "general"
    assert content["category"] is None


def test_template_resolver_uses_safe_general_fallback_when_pack_cannot_load(tmp_path):
    resolver = TemplatePackResolver.from_directory(tmp_path / "missing")

    rendered = resolver.render(
        OptimizeRequest("input", metadata={"language": "unsupported"}),
        SceneDetectionResult("not-in-pack", 0.4, "test"),
    )

    assert rendered["scene"] == "general"
    assert rendered["style"] == "balanced"
    assert rendered["language"] == "zh-CN"
    assert rendered["messages"][0]["role"] == "system"
    assert rendered["messages"][1] == {"role": "user", "content": "input"}


@pytest.mark.parametrize("mutation", ["future_schema", "duplicate_scene", "traversal"])
def test_template_pack_rejects_unsafe_manifests_with_one_safe_error(tmp_path, mutation):
    root = _write_minimal_pack(tmp_path)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if mutation == "future_schema":
        manifest["schema_version"] = 2
    elif mutation == "duplicate_scene":
        manifest["scenes"].append(dict(manifest["scenes"][0]))
    else:
        manifest["scenes"][0]["path"] = "../outside.md"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(TemplatePackError) as caught:
        FileTemplatePack.load(root)

    assert str(caught.value) == "Template pack is invalid."
    assert str(root) not in str(caught.value)


@pytest.mark.parametrize(
    "content",
    [b"\xff\xfe", b"x" * 65_537],
    ids=["invalid-utf8", "oversized"],
)
def test_template_pack_rejects_invalid_or_oversized_utf8_assets(tmp_path, content):
    root = _write_minimal_pack(tmp_path)
    (root / "content" / "general.md").write_bytes(content)

    with pytest.raises(TemplatePackError, match="^Template pack is invalid\\.$"):
        FileTemplatePack.load(root)


def test_template_pack_rejects_symlinked_assets_before_resolving_them(tmp_path, monkeypatch):
    root = _write_minimal_pack(tmp_path)
    scene_path = root / "content" / "general.md"
    target_path = root / "content" / "general-target.md"
    scene_path.rename(target_path)
    real_resolve = Path.resolve
    real_is_symlink = Path.is_symlink

    def resolve(path, strict=False):
        if path == scene_path:
            return target_path
        return real_resolve(path, strict=strict)

    def is_symlink(path):
        return path == scene_path or real_is_symlink(path)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    with pytest.raises(TemplatePackError, match="^Template pack is invalid\\.$"):
        FileTemplatePack.load(root)


def _write_minimal_pack(tmp_path: Path) -> Path:
    root = tmp_path / "pack"
    (root / "system").mkdir(parents=True)
    (root / "content").mkdir()
    (root / "style").mkdir()
    (root / "system" / "base.md").write_text("system", encoding="utf-8")
    (root / "content" / "general.md").write_text("general", encoding="utf-8")
    (root / "style" / "balanced.md").write_text("balanced", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "id": "test-pack",
        "version": "1.0.0",
        "default_scene": "general",
        "default_style": "balanced",
        "supported_modes": ["content", "prompt"],
        "supported_languages": ["zh-CN", "en-US"],
        "system": {"id": "base", "path": "system/base.md"},
        "scenes": [{"id": "general", "path": "content/general.md"}],
        "styles": [{"id": "balanced", "path": "style/balanced.md"}],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root
