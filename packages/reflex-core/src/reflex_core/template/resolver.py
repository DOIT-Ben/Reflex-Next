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


class PassthroughTemplateResolver:
    """Return a structured, provider-neutral request without provider logic."""

    def render(self, request: OptimizeRequest, scene: SceneDetectionResult) -> dict[str, object]:
        return {
            "text": request.text,
            "mode": request.mode,
            "style": request.style,
            "scene": scene.scene,
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
        scene_id, style_id, system, scene_template, style_template = self._templates(
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
            "language": language,
        }

    def _templates(self, scene_id: str, style_id: str) -> tuple[str, str, str, str, str]:
        pack = self._pack
        if pack is not None:
            resolved_scene = scene_id if scene_id in pack.scene_ids else pack.manifest.default_scene
            resolved_style = style_id if style_id in pack.style_ids else pack.manifest.default_style
            try:
                return (
                    resolved_scene,
                    resolved_style,
                    pack.read_system(),
                    pack.read_scene(resolved_scene),
                    pack.read_style(resolved_style),
                )
            except Exception:
                pass
        resolved_style = style_id if style_id in _FALLBACK_STYLES else "balanced"
        return (
            "general",
            resolved_style,
            _FALLBACK_SYSTEM,
            _FALLBACK_SCENE,
            _FALLBACK_STYLES[resolved_style],
        )


def _language(value: object) -> str:
    return value if isinstance(value, str) and value in _LANGUAGE_INSTRUCTIONS else "zh-CN"
