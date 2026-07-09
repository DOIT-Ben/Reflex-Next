"""Built-in zero-dependency scene detectors."""

from __future__ import annotations

import re

from ..models import OptimizeRequest, SceneDetectionResult

_CODE_MARKERS = (
    "```",
    "def ",
    "class ",
    "function ",
    "import ",
    "traceback",
    ".py",
    ".js",
    ".ts",
    ".rs",
)
_TRANSLATION_MARKERS = ("翻译", "译成", "translate", "translation")
_REPORT_MARKERS = ("报告", "总结", "分析", "结论", "汇报")
_DIAGNOSIS_MARKERS = ("报错", "异常", "故障", "为什么", "error", "exception", "failed")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


class RuleSceneDetector:
    """Fast L0 detector with deterministic, zero-dependency rules."""

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        normalized = text.strip()
        lowered = normalized.lower()

        if any(marker in lowered for marker in _CODE_MARKERS):
            return SceneDetectionResult("code", 0.88, "rule", "code_marker")
        if _EMAIL_RE.search(normalized) or any(
            marker in normalized for marker in ("邮件", "求职信", "商务信函", "主题：", "收件人：", "发件人：")
        ):
            return SceneDetectionResult("email", 0.84, "rule", "email_structure")
        if any(marker in lowered for marker in _TRANSLATION_MARKERS):
            return SceneDetectionResult("translation", 0.82, "rule", "translation_marker")
        if any(marker in lowered for marker in _DIAGNOSIS_MARKERS):
            return SceneDetectionResult("problem_diagnosis", 0.76, "rule", "diagnosis_marker")
        if any(marker in normalized for marker in _REPORT_MARKERS):
            return SceneDetectionResult("report_writing", 0.72, "rule", "report_marker")
        return SceneDetectionResult("general", 0.2, "rule", "no_specific_rule")


class GeneralSceneDetector:
    """Safe fallback detector used when no specialized detector is available."""

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult:
        return SceneDetectionResult(scene="general", confidence=0.0, method="fallback")
