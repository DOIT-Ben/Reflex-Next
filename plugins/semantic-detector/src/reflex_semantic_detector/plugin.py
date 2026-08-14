"""Local-only L1 semantic scene detection with lazy model loading."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reflex_core import OptimizeRequest, SceneDetectionResult

from .lifecycle import MODEL_LIFECYCLE, ModelLifecycle, ModelLifecycleBusy

DEFAULT_MODEL_ID = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_MIN_CONFIDENCE = 0.42

_SCENE_EXAMPLES: dict[str, str] = {
    "general": "general request improve rewrite organize clarify this content",
    "article_writing": "write an article blog post content writing",
    "social_media": "write a social media post caption for a platform audience",
    "email": "write a professional business email reply",
    "ad_creative": "create advertising copy slogan campaign call to action",
    "product_desc": "write a product description features benefits use cases",
    "paper_writing": "write an academic research paper abstract",
    "code_generation": "write code implement a function program algorithm",
    "code_review": "review code quality bug security readability",
    "bug_fix": "fix an exception error crash bug",
    "code_refactor": "refactor code structure while preserving behavior",
    "tech_doc": "write technical documentation api reference examples",
    "data_analysis": "analyze data metrics statistics visualization",
    "market_research": "conduct market research user insights",
    "competitor_analysis": "analyze competitors competitive positioning",
    "literature_review": "review research literature prior work evidence gaps",
    "trend_prediction": "predict future industry trends signals scenarios uncertainty",
    "knowledge_explain": "explain a concept with examples for understanding",
    "study_plan": "create a learning study plan",
    "exam_prep": "prepare for an exam syllabus revision practice schedule",
    "course_design": "design a course lesson learning objectives activities assessment",
    "homework_help": "help solve homework exercise with steps and checks",
    "report_writing": "write a work report summary",
    "decision_analysis": "compare options tradeoffs and recommend a decision",
    "project_planning": "plan a project milestones tasks schedule",
    "process_optimization": "improve a workflow process sop controls metrics",
    "meeting_summary": "summarize meeting notes decisions action items",
    "story_writing": "write a story fiction characters conflict pacing",
    "script_writing": "write a screenplay video script scenes dialogue shots",
    "poetry_creation": "write a poem imagery rhythm poetic language",
    "game_plot": "design a game plot quests conflict player feedback",
    "world_building": "build a fictional world rules history consistency",
    "doc_translation": "translate a technical document",
    "localization": "localize software content for another language",
    "literary_translation": "translate literature fiction poetry preserving style",
    "term_unification": "unify terminology glossary consistent word choices",
    "interpreting_notes": "prepare concise interpreting notes for spoken translation",
    "problem_diagnosis": "diagnose a system problem symptoms and hypotheses",
    "solution_generation": "design alternative solution approaches and steps",
    "root_cause": "perform root cause analysis evidence five whys system causes",
    "risk_assessment": "assess risks probability impact mitigation plan",
    "emergency_plan": "create an emergency response contingency recovery plan",
    "resume": "optimize a resume highlight achievements quantify results match job description",
    "cover_letter": "write a cover letter application motivation skills matching the role",
    "interview": "prepare for a job interview questions answers star method examples",
    "headline": "create catchy article headlines titles hooks for readers",
    "sales_script": "write a sales pitch script value proposition objection handling call to action",
    "speech": "write a speech address presentation inspiring the audience call to action",
    "prd": "write a product requirements document user stories acceptance criteria priorities",
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
        lifecycle: ModelLifecycle = MODEL_LIFECYCLE,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("invalid model id")
        if not isinstance(min_confidence, (int, float)) or not 0.0 <= min_confidence <= 1.0:
            raise ValueError("invalid minimum confidence")
        self._model_id = model_id.strip()
        if cache_dir is None:
            from .model_manager import default_cache_dir

            self._cache_dir = default_cache_dir()
        else:
            self._cache_dir = Path(cache_dir)
        self._min_confidence = float(min_confidence)
        self._model_factory = model_factory
        self._scene_examples = dict(scene_examples or _SCENE_EXAMPLES)
        self._model: Any | None = None
        self._scene_vectors: list[list[float]] | None = None
        self._scene_ids = tuple(self._scene_examples)
        self._lifecycle = lifecycle
        self._condition = threading.Condition()
        self._model_loading = False
        self._vectors_loading = False
        self._model_generation = lifecycle.generation()

    @property
    def model_loaded(self) -> bool:
        generation = self._lifecycle.try_generation()
        if generation is None:
            return False
        with self._condition:
            return self._model is not None and self._model_generation == generation

    def detect(self, text: str, request: OptimizeRequest) -> SceneDetectionResult | None:
        if not isinstance(text, str) or not text.strip():
            return None
        model = self._load_model()
        if model is None:
            return None
        try:
            scene_vectors = self._load_scene_vectors(model)
            if scene_vectors is None:
                return None
            query = _vectors(model.encode([text.strip()]))[0]
            scores = [_cosine(query, candidate) for candidate in scene_vectors]
        except Exception:
            return None
        if not scores:
            return None
        index, confidence = max(enumerate(scores), key=lambda item: item[1])
        if confidence < self._min_confidence:
            return None
        generation = self._lifecycle.try_generation()
        if generation is None or self._model_generation != generation:
            return None
        return SceneDetectionResult(
            scene=self._scene_ids[index],
            confidence=confidence,
            method="semantic",
            reason="local_embedding",
        )

    def _load_model(self) -> Any | None:
        with self._condition:
            if self._model_loading:
                self._condition.wait_for(lambda: not self._model_loading)
                return self._model
        generation = self._lifecycle.try_generation()
        if generation is None:
            return None
        with self._condition:
            if self._model_loading:
                self._condition.wait_for(lambda: not self._model_loading)
                return self._model
            if self._model_generation != generation:
                self._model = None
                self._scene_vectors = None
                self._model_generation = generation
            if self._model is not None:
                return self._model
            self._model_loading = True

        factory = self._model_factory
        if factory is None:
            try:
                from sentence_transformers import SentenceTransformer
            except Exception:
                with self._condition:
                    self._model_loading = False
                    self._condition.notify_all()
                return None
            factory = SentenceTransformer

        model = None
        try:
            with self._lifecycle.enter(blocking=False):
                kwargs: dict[str, Any] = {"local_files_only": True}
                kwargs["cache_folder"] = str(self._cache_dir)
                model = factory(self._model_id, **kwargs)
                generation = self._lifecycle.generation()
        except (Exception, ModelLifecycleBusy):
            model = None
        finally:
            with self._condition:
                self._model = model
                self._model_generation = generation
                self._model_loading = False
                self._condition.notify_all()
        return model

    def _load_scene_vectors(self, model: Any) -> list[list[float]] | None:
        with self._condition:
            if self._scene_vectors is not None:
                return self._scene_vectors
            if self._vectors_loading:
                self._condition.wait_for(lambda: not self._vectors_loading)
                return self._scene_vectors
            self._vectors_loading = True
        vectors = None
        try:
            vectors = _vectors(model.encode(list(self._scene_examples.values())))
        except Exception:
            vectors = None
        finally:
            with self._condition:
                self._scene_vectors = vectors
                self._vectors_loading = False
                self._condition.notify_all()
        return vectors


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
