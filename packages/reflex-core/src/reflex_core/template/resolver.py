"""Provider-neutral template resolvers."""

from __future__ import annotations

from pathlib import Path

from ..interfaces import TemplatePack
from ..models import OptimizeRequest, SceneDetectionResult
from .pack import FileTemplatePack, TemplatePackError

_CONTENT_MODE = """## 工作模式：内容优化
优化用户给出的原始文本，保持核心事实、实体、数字、日期、观点和格式。
直接输出优化后的正文，不添加分析、解释或前缀。"""

_PROMPT_MODE = """## 工作模式：结构化提示词
把用户需求改写为结构化提示词，包含角色、任务、要求、执行流程和输出格式。
保留原始意图与明确约束，不虚构新的事实或限制。直接输出结构化提示词。"""

_LANGUAGE_INSTRUCTIONS = {
    "zh-CN": "## 输出语言\n使用简体中文输出。",
    "en-US": "## Output language\nUse English (US) for the complete response.",
}

_FALLBACK_SYSTEM = """# Role: 文本与提示词优化助手
保持用户原意和关键事实，不虚构具体数据，不泄露敏感信息。
只返回最终结果，不附加内部推理或工具说明。"""
_FALLBACK_SCENE = """# 通用场景
保持表达清晰、准确、连贯，并保留原始结构。"""
_FALLBACK_STYLES = {
    "concise": "# 简洁风格\n删除冗余内容，直接呈现核心信息。",
    "balanced": "# 平衡风格\n平衡信息完整性、清晰度和篇幅。",
    "detailed": "# 详细风格\n完整展开必要细节，保持逻辑严谨。",
    "creative": "# 创意风格\n在不改变事实和意图的前提下增强表达。",
    "precise": "# 精准风格\n使用准确术语、明确边界和可执行表述。",
}


_FALLBACK_CATEGORIES = {
    "business": "# 商务沟通类\n目的明确、专业得体、条理清晰。",
    "marketing": "# 营销文案类\n突出卖点、打动读者、行动导向。",
    "market_analysis": "# 市场分析类\n数据支撑、逻辑严谨、结论明确。",
    "tech_doc": "# 技术文档类\n准确规范、可执行、面向读者。",
    "code": "# 代码工程类\n正确、可读、可维护。",
    "diagnosis": "# 问题诊断类\n定位根因、结构清晰、措施可落地。",
    "academic": "# 学术研究类\n严谨规范、引用准确、论证充分。",
    "education": "# 学习教育类\n循序渐进、讲解清晰、重点突出。",
    "creative": "# 创意写作类\n想象丰富、表达生动、结构完整。",
    "translation": "# 翻译本地化类\n语义准确、自然流畅、文化适配。",
}


def _split_scene(value: str) -> tuple[str | None, str | None]:
    """Split ``category:scene`` into (category, scene); both parts optional."""
    if ":" in value:
        category, _, scene = value.partition(":")
        return (category or None, scene or None)
    return (None, value)


class PassthroughTemplateResolver:
    """Return a structured, provider-neutral request without provider logic."""

    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> dict[str, object]:
        return {
            "text": request.text,
            "mode": request.mode,
            "style": request.style,
            "scene": scene.scene,
            "category": getattr(scene, "category", None),
            "metadata": dict(request.metadata),
        }


class TemplatePackResolver:
    """Compose validated system, mode, scene, style and language instructions."""

    def __init__(self, pack: TemplatePack | None = None) -> None:
        self._pack = pack

    @classmethod
    def from_directory(cls, root: str | Path) -> "TemplatePackResolver":
        try:
            return cls(FileTemplatePack.load(root))
        except TemplatePackError:
            return cls()

    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> dict[str, object]:
        language = _language(request.metadata.get("language"))
        scene_id, category, style_id, system, scene_template, style_template = self._templates(
            scene.scene,
            request.style,
        )
        mode_template = _CONTENT_MODE if request.mode == "content" else _PROMPT_MODE
        system_message = "\n\n".join(
            section.strip()
            for section in (
                system,
                mode_template,
                _LANGUAGE_INSTRUCTIONS[language],
                scene_template,
                style_template,
            )
            if section.strip()
        )
        return {
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": request.text},
            ],
            "text": request.text,
            "mode": request.mode,
            "style": style_id,
            "scene": scene_id,
            "category": category,
            "language": language,
        }

    def _templates(
        self, scene_value: str, style_id: str
    ) -> tuple[str, str | None, str, str, str, str]:
        explicit_category, requested_scene = _split_scene(scene_value)
        pack = self._pack
        if pack is not None:
            if requested_scene is not None and requested_scene in pack.scene_ids:
                resolved_scene = requested_scene
                category = explicit_category or pack.scene_categories.get(requested_scene)
                scene_template = pack.read_scene(requested_scene)
            elif requested_scene is not None and requested_scene in pack.category_ids:
                resolved_scene = requested_scene
                category = requested_scene
                scene_template = pack.read_category(requested_scene)
            elif explicit_category is not None and explicit_category in pack.category_ids:
                resolved_scene = explicit_category
                category = explicit_category
                scene_template = pack.read_category(explicit_category)
            else:
                resolved_scene = pack.manifest.default_scene
                category = pack.scene_categories.get(resolved_scene)
                scene_template = pack.read_scene(resolved_scene)
            resolved_style = style_id if style_id in pack.style_ids else pack.manifest.default_style
            try:
                return (
                    resolved_scene,
                    category,
                    resolved_style,
                    pack.read_system(),
                    scene_template,
                    pack.read_style(resolved_style),
                )
            except Exception:
                pass
        if requested_scene is not None and requested_scene in _FALLBACK_CATEGORIES:
            resolved_scene = requested_scene
            category = requested_scene
            scene_template = _FALLBACK_CATEGORIES[requested_scene]
        elif explicit_category is not None and explicit_category in _FALLBACK_CATEGORIES:
            resolved_scene = explicit_category
            category = explicit_category
            scene_template = _FALLBACK_CATEGORIES[explicit_category]
        else:
            resolved_scene = "general"
            category = None
            scene_template = _FALLBACK_SCENE
        resolved_style = style_id if style_id in _FALLBACK_STYLES else "balanced"
        return (
            resolved_scene,
            category,
            resolved_style,
            _FALLBACK_SYSTEM,
            scene_template,
            _FALLBACK_STYLES[resolved_style],
        )


def _language(value: object) -> str:
    return value if isinstance(value, str) and value in _LANGUAGE_INSTRUCTIONS else "zh-CN"
