from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version


try:
    __version__ = version("reflex-cloud")
except PackageNotFoundError:
    # Source-only imports are supported for lightweight tooling; installed
    # production environments always resolve the distribution metadata.
    __version__ = "0.0.0+source"
