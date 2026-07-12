"""Explicit model-cache management for the optional semantic detector."""

from __future__ import annotations

import importlib.util
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reflex_core import OperationCancelled

from .plugin import DEFAULT_MODEL_ID

MODEL_FILE_SUFFIXES = (
    ".json",
    ".safetensors",
    ".txt",
    ".model",
    ".py",
)


def default_cache_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".cache"
    return root / "Reflex Next" / "models"


@dataclass(frozen=True)
class SemanticModelManagerDescriptor:
    plugin_id: str = "semantic-detector"
    display_name: str = "Semantic Detector"
    version: str = "1"
    kind: str = "command"
    permissions: tuple[str, ...] = ("model_cache", "network")
    operations: tuple[str, ...] = ("status", "download", "delete")
    public_operations: tuple[str, ...] = ("status", "download", "delete")


class SemanticModelError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SemanticModelManager:
    descriptor = SemanticModelManagerDescriptor()

    def __init__(
        self,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        cache_dir: Path | None = None,
        module_available: Callable[[str], bool] | None = None,
        list_repo_files: Callable[[str], Iterable[str]] | None = None,
        download_file: Callable[..., Any] | None = None,
    ) -> None:
        self._model_id = model_id
        self._cache_dir = (cache_dir or default_cache_dir()).resolve()
        self._module_available = module_available or _module_available
        self._list_repo_files = list_repo_files
        self._download_file = download_file

    def invoke(self, operation: str, payload: dict[str, Any], services: Any, cancellation: Any):
        del services
        if payload:
            raise SemanticModelError("model_payload_invalid")
        if operation == "status":
            return self.status()
        if operation == "download":
            return self.download(cancellation)
        if operation == "delete":
            return self.delete()
        raise SemanticModelError("model_operation_invalid")

    def status(self) -> dict[str, Any]:
        model_root = self._model_root()
        return {
            "model_id": self._model_id,
            "model_state": "ready" if _has_complete_snapshot(model_root) else "missing",
            "runtime_state": (
                "ready" if self._module_available("sentence_transformers") else "missing"
            ),
            "size_bytes": _directory_size(model_root),
        }

    def download(self, cancellation: Any):
        def events():
            if getattr(cancellation, "is_cancelled", False):
                raise OperationCancelled
            list_repo_files, download_file = self._download_functions()
            try:
                files = _selected_files(list_repo_files(self._model_id))
            except Exception as error:
                raise SemanticModelError("model_download_failed") from error
            if not files:
                raise SemanticModelError("model_download_failed")
            total = len(files)
            for index, filename in enumerate(files, start=1):
                if getattr(cancellation, "is_cancelled", False):
                    raise OperationCancelled
                try:
                    download_file(
                        repo_id=self._model_id,
                        filename=filename,
                        cache_dir=str(self._cache_dir),
                    )
                except Exception as error:
                    raise SemanticModelError("model_download_failed") from error
                yield {
                    "status": "progress",
                    "data": {
                        "completed": index,
                        "total": total,
                        "percent": round(index * 100 / total),
                    },
                }
            status = self.status()
            if status["model_state"] != "ready":
                raise SemanticModelError("model_download_incomplete")
            yield {"status": "result", "data": status}

        return events()

    def delete(self) -> dict[str, Any]:
        model_root = self._model_root()
        if model_root.exists():
            try:
                model_root.relative_to(self._cache_dir)
                shutil.rmtree(model_root)
            except Exception as error:
                raise SemanticModelError("model_delete_failed") from error
        return self.status()

    def _download_functions(self):
        if self._list_repo_files is not None and self._download_file is not None:
            return self._list_repo_files, self._download_file
        if not self._module_available("huggingface_hub"):
            raise SemanticModelError("model_runtime_missing")
        try:
            from huggingface_hub import hf_hub_download, list_repo_files
        except Exception as error:
            raise SemanticModelError("model_runtime_missing") from error
        return list_repo_files, hf_hub_download

    def _model_root(self) -> Path:
        return self._cache_dir / f"models--{self._model_id.replace('/', '--')}"


def manager() -> SemanticModelManager:
    return SemanticModelManager()


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _selected_files(values: Iterable[str]) -> list[str]:
    files = {
        value
        for value in values
        if isinstance(value, str)
        and value
        and not value.startswith(("onnx/", "."))
        and value.lower().endswith(MODEL_FILE_SUFFIXES)
    }
    return sorted(files)


def _has_complete_snapshot(model_root: Path) -> bool:
    snapshots = model_root / "snapshots"
    if not snapshots.is_dir():
        return False
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        has_config = (snapshot / "config.json").is_file()
        has_weights = any(snapshot.rglob("*.safetensors")) or any(
            snapshot.rglob("pytorch_model*.bin")
        )
        if has_config and has_weights:
            return True
    return False


def _directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        return 0
    return total
