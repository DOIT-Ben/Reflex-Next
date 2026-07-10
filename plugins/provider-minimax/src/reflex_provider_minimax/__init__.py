"""MiniMax Provider plugin entry point."""

from dataclasses import dataclass
from typing import Any

from .provider import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    MiniMaxProvider,
)


@dataclass(frozen=True)
class MiniMaxProviderFactory:
    id: str = "minimax"
    display_name: str = "MiniMax"
    version: str = "0.1.0"
    models: tuple[str, ...] = SUPPORTED_MODELS
    default_model: str = DEFAULT_MODEL
    required_secret: str = "api_key"
    permissions: tuple[str, ...] = ("network",)
    default_base_url: str = DEFAULT_BASE_URL

    def create(self, secret: str, config: Any) -> MiniMaxProvider:
        return MiniMaxProvider(secret, config)


def plugin() -> MiniMaxProviderFactory:
    return MiniMaxProviderFactory()


__all__ = ["MiniMaxProviderFactory", "plugin"]
