import pytest

from reflex_core import OptimizeRequest, SceneDetectionResult


def test_optimize_request_normalizes_fields():
    request = OptimizeRequest(
        text="  hello  ",
        mode=" CONTENT ",
        style=" Balanced ",
        scene=" report ",
        scene_policy=" AUTO ",
        provider=" minimax ",
        model=" model-a ",
        metadata={"x": 1},
    )

    assert request.text == "hello"
    assert request.mode == "content"
    assert request.style == "balanced"
    assert request.scene == "report"
    assert request.scene_policy == "auto"
    assert request.provider == "minimax"
    assert request.model == "model-a"
    assert request.metadata == {"x": 1}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "other"),
        ("style", "verbose"),
        ("scene_policy", "sometimes"),
    ],
)
def test_optimize_request_rejects_invalid_enum_values(field, value):
    kwargs = {field: value}
    with pytest.raises(ValueError):
        OptimizeRequest(text="hello", **kwargs)


def test_scene_detection_result_validates_confidence():
    with pytest.raises(ValueError):
        SceneDetectionResult("general", 1.5, "rule")


def test_precise_style_is_preserved_as_a_compatibility_alias():
    request = OptimizeRequest("hello", style=" PRECISE ")

    assert request.style == "precise"
