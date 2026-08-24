from __future__ import annotations

from reflex_core import OptimizeRequest, SceneDetectionResult
from reflex_core.scene.detectors import RuleSceneDetector
from reflex_runtime.context import _FallbackSceneDetector


class RecordingSemanticDetector:
    def __init__(self, result: SceneDetectionResult | None) -> None:
        self.result = result
        self.calls: list[str] = []

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult | None:
        self.calls.append(text)
        return self.result


def test_explicit_l0_rule_wins_without_loading_the_semantic_detector() -> None:
    semantic = RecordingSemanticDetector(
        SceneDetectionResult("article_writing", 0.99, "semantic")
    )
    detector = _FallbackSceneDetector(semantic, RuleSceneDetector())

    result = detector.detect("请做一次代码审查并指出风险", OptimizeRequest("input"))

    assert result.scene == "code_review"
    assert result.method == "rule"
    assert semantic.calls == []


def test_semantic_detector_refines_only_the_general_l0_fallback() -> None:
    semantic = RecordingSemanticDetector(
        SceneDetectionResult("article_writing", 0.73, "semantic")
    )
    detector = _FallbackSceneDetector(semantic, RuleSceneDetector())

    result = detector.detect("帮我把这段内容写得更吸引人", OptimizeRequest("input"))

    assert result.scene == "article_writing"
    assert semantic.calls == ["帮我把这段内容写得更吸引人"]


def test_general_l0_result_is_kept_when_semantic_detector_has_no_answer() -> None:
    semantic = RecordingSemanticDetector(None)
    detector = _FallbackSceneDetector(semantic, RuleSceneDetector())

    result = detector.detect("帮我处理一下", OptimizeRequest("input"))

    assert result.scene == "general"
    assert result.method == "rule"
