from __future__ import annotations

import sys
from importlib.metadata import entry_points

from reflex_core import OptimizeRequest
from reflex_semantic_detector import SemanticSceneDetector


class FakeModel:
    def __init__(self, *_args, **_kwargs) -> None:
        self.calls: list[list[str]] = []

    def encode(self, values: list[str]) -> list[list[float]]:
        self.calls.append(values)
        vectors = {
            "write a professional business email reply": [1.0, 0.0],
            "write code implement a function program algorithm": [0.0, 1.0],
            "draft an email to a customer": [0.95, 0.05],
        }
        return [vectors.get(value, [0.0, 0.0]) for value in values]


def test_import_does_not_load_optional_model_packages() -> None:
    import reflex_semantic_detector

    assert reflex_semantic_detector
    assert "sentence_transformers" not in sys.modules
    assert "torch" not in sys.modules


def test_entry_point_uses_the_runtime_allowlist_id() -> None:
    matches = [
        item
        for item in entry_points(group="reflex.scene_detectors")
        if item.name == "semantic-detector"
    ]
    assert len(matches) == 1
    assert matches[0].load()().descriptor.plugin_id == "semantic-detector"


def test_detects_with_an_injected_local_model_without_network() -> None:
    detector = SemanticSceneDetector(
        model_factory=FakeModel,
        scene_examples={
            "email": "write a professional business email reply",
            "code_generation": "write code implement a function program algorithm",
        },
        min_confidence=0.4,
    )

    result = detector.detect("draft an email to a customer", OptimizeRequest("input"))

    assert result is not None
    assert result.scene == "email"
    assert result.method == "semantic"
    assert detector.model_loaded is True


def test_missing_optional_model_falls_back_without_loading_or_error() -> None:
    detector = SemanticSceneDetector(model_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    assert detector.detect("review this code", OptimizeRequest("input")) is None
    assert detector.model_loaded is False


def test_low_confidence_and_empty_input_return_no_result() -> None:
    detector = SemanticSceneDetector(
        model_factory=FakeModel,
        scene_examples={"email": "write a professional business email reply"},
        min_confidence=0.99,
    )

    assert detector.detect("unknown input", OptimizeRequest("input")) is None
    assert detector.detect("", OptimizeRequest("input")) is None
