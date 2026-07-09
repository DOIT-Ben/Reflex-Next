from reflex_core import OptimizeRequest
from reflex_core.scene import RuleSceneDetector


def test_rule_scene_detector_recognizes_code_without_optional_dependencies():
    result = RuleSceneDetector().detect("def greet():\n    return 'hello'", OptimizeRequest("input"))
    assert result.scene == "code"
    assert result.method == "rule"


def test_rule_scene_detector_falls_back_to_general():
    result = RuleSceneDetector().detect("帮我优化这句话", OptimizeRequest("input"))
    assert result.scene == "general"
    assert result.confidence < 0.5
