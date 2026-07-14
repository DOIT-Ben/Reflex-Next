from __future__ import annotations

import sys
import threading
from importlib.metadata import entry_points

import pytest

from reflex_core import CancellationToken, OperationCancelled, OptimizeRequest
from reflex_semantic_detector import SemanticModelManager, SemanticSceneDetector
from reflex_semantic_detector.model_manager import SemanticModelError
from reflex_semantic_detector.lifecycle import ModelLifecycle


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

    managers = [
        item
        for item in entry_points(group="reflex.model_managers")
        if item.name == "semantic-detector"
    ]
    assert len(managers) == 1
    assert managers[0].load()().descriptor.operations == ("status", "download", "delete")


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


class ActiveCancellation:
    is_cancelled = False


class Cancelled:
    is_cancelled = True


def test_model_manager_reports_runtime_and_cache_state(tmp_path) -> None:
    manager = SemanticModelManager(
        cache_dir=tmp_path,
        module_available=lambda name: name == "sentence_transformers",
    )

    missing = manager.invoke("status", {}, None, ActiveCancellation())

    assert missing["model_state"] == "missing"
    assert missing["runtime_state"] == "ready"
    assert missing["size_bytes"] == 0

    snapshot = (
        tmp_path
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        / "snapshots"
        / "fixture"
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"weights")

    ready = manager.invoke("status", {}, None, ActiveCancellation())

    assert ready["model_state"] == "ready"
    assert ready["size_bytes"] > 0


def test_model_manager_downloads_selected_files_with_bounded_progress(tmp_path) -> None:
    downloaded: list[str] = []

    def download_file(*, repo_id, filename, cache_dir):
        downloaded.append(filename)
        snapshot = (
            tmp_path
            / f"models--{repo_id.replace('/', '--')}"
            / "snapshots"
            / "fixture"
        )
        path = snapshot / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    manager = SemanticModelManager(
        cache_dir=tmp_path,
        module_available=lambda _name: True,
        list_repo_files=lambda _model_id: [
            "README.md",
            "config.json",
            "model.safetensors",
            "onnx/model.onnx",
        ],
        download_file=download_file,
    )

    events = list(manager.invoke("download", {}, None, ActiveCancellation()))

    assert downloaded == ["config.json", "model.safetensors"]
    assert [event["status"] for event in events] == ["progress", "progress", "result"]
    assert events[-1]["data"]["model_state"] == "ready"
    assert events[-1]["data"]["runtime_state"] == "ready"


def test_model_manager_uses_safe_errors_and_deletes_only_its_model_cache(tmp_path) -> None:
    manager = SemanticModelManager(
        cache_dir=tmp_path,
        module_available=lambda _name: False,
    )

    with pytest.raises(SemanticModelError) as caught:
        list(manager.invoke("download", {}, None, ActiveCancellation()))
    assert caught.value.code == "model_runtime_missing"

    model_root = (
        tmp_path
        / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    )
    model_root.mkdir()
    (model_root / "partial.bin").write_bytes(b"partial")
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    result = manager.invoke("delete", {}, None, ActiveCancellation())

    assert result["model_state"] == "missing"
    assert not model_root.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_model_manager_honors_cancellation_before_network_access(tmp_path) -> None:
    manager = SemanticModelManager(
        cache_dir=tmp_path,
        module_available=lambda _name: True,
        list_repo_files=lambda _model_id: (_ for _ in ()).throw(AssertionError()),
        download_file=lambda **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    with pytest.raises(OperationCancelled):
        list(manager.invoke("download", {}, None, Cancelled()))


def test_concurrent_detection_loads_the_model_only_once() -> None:
    lifecycle = ModelLifecycle()
    entered = threading.Event()
    release = threading.Event()
    factory_calls = 0
    factory_lock = threading.Lock()

    def factory(*_args, **_kwargs):
        nonlocal factory_calls
        with factory_lock:
            factory_calls += 1
        entered.set()
        release.wait(timeout=2)
        return FakeModel()

    detector = SemanticSceneDetector(
        model_factory=factory,
        lifecycle=lifecycle,
        scene_examples={"email": "write a professional business email reply"},
        min_confidence=0.4,
    )
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                detector.detect("draft an email to a customer", OptimizeRequest("input"))
            )
        )
        for _ in range(4)
    ]

    for thread in threads:
        thread.start()
    assert entered.wait(timeout=1)
    release.set()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert factory_calls == 1
    assert len(results) == 4
    assert all(result is not None and result.scene == "email" for result in results)


def test_download_blocks_status_delete_and_model_load_with_safe_busy_semantics(
    tmp_path,
) -> None:
    lifecycle = ModelLifecycle()
    entered = threading.Event()
    release = threading.Event()
    download_errors = []

    def download_file(*, repo_id, filename, cache_dir):
        entered.set()
        release.wait(timeout=2)
        snapshot = (
            tmp_path
            / f"models--{repo_id.replace('/', '--')}"
            / "snapshots"
            / "fixture"
        )
        path = snapshot / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    manager = SemanticModelManager(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        module_available=lambda _name: True,
        list_repo_files=lambda _model_id: ["config.json", "model.safetensors"],
        download_file=download_file,
    )
    detector_factory_called = False

    def detector_factory(*_args, **_kwargs):
        nonlocal detector_factory_called
        detector_factory_called = True
        return FakeModel()

    detector = SemanticSceneDetector(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        model_factory=detector_factory,
    )

    def run_download():
        try:
            list(manager.download(ActiveCancellation()))
        except Exception as error:
            download_errors.append(error)

    thread = threading.Thread(target=run_download)
    thread.start()
    assert entered.wait(timeout=1)

    for operation in (manager.status, manager.delete):
        with pytest.raises(SemanticModelError) as caught:
            operation()
        assert caught.value.code == "model_busy"
    assert detector.detect("fixture", OptimizeRequest("input")) is None
    assert detector_factory_called is False

    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert download_errors == []


def test_delete_invalidates_an_already_loaded_detector(tmp_path) -> None:
    lifecycle = ModelLifecycle()
    factory_calls = 0

    def factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        return FakeModel()

    detector = SemanticSceneDetector(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        model_factory=factory,
        scene_examples={"email": "write a professional business email reply"},
        min_confidence=0.4,
    )
    manager = SemanticModelManager(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        module_available=lambda _name: True,
    )

    assert detector.detect(
        "draft an email to a customer", OptimizeRequest("input")
    ) is not None
    assert detector.model_loaded is True
    manager.delete()

    assert detector.model_loaded is False
    assert detector.detect(
        "draft an email to a customer", OptimizeRequest("input")
    ) is not None
    assert factory_calls == 2


def test_model_load_blocks_management_until_single_flight_finishes(tmp_path) -> None:
    lifecycle = ModelLifecycle()
    entered = threading.Event()
    release = threading.Event()
    result = []

    def factory(*_args, **_kwargs):
        entered.set()
        release.wait(timeout=2)
        return FakeModel()

    detector = SemanticSceneDetector(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        model_factory=factory,
        scene_examples={"email": "write a professional business email reply"},
        min_confidence=0.4,
    )
    manager = SemanticModelManager(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        module_available=lambda _name: True,
    )
    thread = threading.Thread(
        target=lambda: result.append(
            detector.detect("draft an email to a customer", OptimizeRequest("input"))
        )
    )
    thread.start()
    assert entered.wait(timeout=1)

    for operation in (manager.status, manager.delete):
        with pytest.raises(SemanticModelError) as caught:
            operation()
        assert caught.value.code == "model_busy"

    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert result[0] is not None


def test_mid_download_cancellation_releases_the_lifecycle_lock(tmp_path) -> None:
    lifecycle = ModelLifecycle()
    cancellation = CancellationToken()

    def download_file(*, repo_id, filename, cache_dir):
        snapshot = (
            tmp_path
            / f"models--{repo_id.replace('/', '--')}"
            / "snapshots"
            / "fixture"
        )
        path = snapshot / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
        cancellation.cancel()

    manager = SemanticModelManager(
        cache_dir=tmp_path,
        lifecycle=lifecycle,
        module_available=lambda _name: True,
        list_repo_files=lambda _model_id: ["config.json", "model.safetensors"],
        download_file=download_file,
    )

    with pytest.raises(OperationCancelled):
        list(manager.download(cancellation))

    assert manager.delete()["model_state"] == "missing"
