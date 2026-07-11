"""Encrypted history storage plugin entry point."""

from .plugin import HistorySqlitePlugin, plugin

__all__ = ["HistorySqlitePlugin", "plugin"]
