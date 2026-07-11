"""Local-only L1 semantic scene detection with lazy model loading."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reflex_core import OptimizeRequest, SceneDetectionResult

DEFAULT_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MIN_CONFIDENCE = 0.42

_SCENE_EXAMPLES: dict[str, str] = {
    "article_writing": "write an article blog post content writing",
    "email": "write a professional business email reply",
    "code_generation": "write code implement a function program algorithm",
    "code_review": "review code quality bug security readability",
    "bug_fix": "fix an exception error crash bug",
    "data_analysis": "analyze data metrics statistics visualization",
    "paper_writing": "write an academic research paper abstract",
    "report_writing": "write a work report summary",
    "project_planning": "plan a project milestones tasks schedule",
    "meeting_summary": "summarize meeting notes decisions action items",
    "doc_translation": "translate a technical document",
    "localization": "localize software content for another language",
    "problem_diagnosis": "diagnose a system problem root cause",
    "solution_generation": "design a solution approach",
    "risk_assessment": "assess risks and mitigation plan",
    "study_plan": "create a learning study plan",
    "market_research": "conduct market research user insights",
    "competitor_analysis": "analyze competitors competitive positioning",
}


@dataclass(frozen=True)
class SemanticDetectorDescriptor:
    plugin_id: str = "semantic-detector"
    display_name: str = "Semantic Detector"
    version: str = "1"
    kind: str = "scene_detector"
    permissions: tuple[str, ...] = ("model_cache",)


class SemanticSceneDetector:
    """Classify against local embeddings without downloading a model."""

    descriptor = SemanticDetectorDescriptor()

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        cache_dir: Path | None = None,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        model_factory: Callable[..., Any] | None = None,
        scene_examples: dict[str, str] | None = None,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("invalid model id")
        if not isinstance(min_confidence, (int, float)) or not 0.0 <= min_confidence <= 1.0:
            raise ValueError("invalid minimum confidence")
        self._model_id = model_id.strip()
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self._min_confidence = float(min_confidence)
        self._model_factory = model_factory
        self._scene_examples = dict(scene_examples or _SCENE_EXAMPLES)
        self._model: Any | None = None
        self._scene_vectors: list[list[float]] | None = None
        self._scene_ids = tuple(self._scene_examples)

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult | None:
        if not isinstance(text, str) or not text.strip():
            return None
        model = self._load_model()
        if model is None:
            return None
        try:
            if self._scene_vectors is None:
                self._scene_vectors = _vectors(model.encode(list(self._scene_examples.values())))
            query = _vectors(model.encode([text.strip()]))[0]
            scores = [_cosine(query, candidate) for candidate in self._scene_vectors]
        except Exception:
            return None
        if not scores:
            return None
        index, confidence = max(enumerate(scores), key=lambda item: item[1])
        if confidence < self._min_confidence:
            return None
        return SceneDetectionResult(
            scene=self._scene_ids[index],
            confidence=confidence,
            method="semantic",
            reason="local_embedding",
        )

    def _load_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        factory = self._model_factory
        if factory is None:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception:
                return None
            factory = SentenceTransformer
        try:
            kwargs: dict[str, Any] = {"local_files_only": True}
            if self._cache_dir is not None:
                kwargs["cache_folder"] = str(self._cache_dir)
            self._model = factory(self._model_id, **kwargs)
        except Exception:
            return None
        return self._model


def _vectors(values: Sequence[Any]) -> list[list[float]]:
    result: list[list[float]] = []
    for value in values:
        vector = value.tolist() if hasattr(value, "tolist") else value
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise ValueError("invalid embedding")
        converted = [float(item) for item in vector]
        if not converted or not all(math.isfinite(item) for item in converted):
            raise ValueError("invalid embedding")
        result.append(converted)
    return result


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions differ")
    magnitude = math.sqrt(sum(item * item for item in left)) * math.sqrt(sum(item * item for item in right))
    if magnitude == 0:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left, right)) / magnitude))


def plugin() -> SemanticSceneDetector:
    return SemanticSceneDetector()
