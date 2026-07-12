"""Optional lazy local semantic scene detector."""

from .model_manager import SemanticModelManager, manager
from .plugin import SemanticSceneDetector, plugin

__all__ = ["SemanticModelManager", "SemanticSceneDetector", "manager", "plugin"]
