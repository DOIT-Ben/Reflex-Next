"""Validated file-backed template packs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_MAX_ASSET_BYTES = 65_536
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_SUPPORTED_MODES = frozenset({"content", "prompt"})
_SUPPORTED_LANGUAGES = frozenset({"zh-CN", "en-US"})


class TemplatePackError(RuntimeError):
    """One stable error for malformed or unavailable local template packs."""

    def __init__(self) -> None:
        super().__init__("Template pack is invalid.")


@dataclass(frozen=True)
class TemplateAsset:
    id: str
    path: str


@dataclass(frozen=True)
class TemplatePackManifest:
    schema_version: int
    id: str
    version: str
    default_scene: str
    default_style: str
    supported_modes: tuple[str, ...]
    supported_languages: tuple[str, ...]
    system: TemplateAsset
    scenes: tuple[TemplateAsset, ...]
    styles: tuple[TemplateAsset, ...]


class FileTemplatePack:
    """Load a bounded manifest and its allowlisted Markdown assets into memory."""

    def __init__(
        self,
        manifest: TemplatePackManifest,
        assets: dict[str, str],
    ) -> None:
        self.manifest = manifest
        self._assets = dict(assets)
        self._scene_paths = {asset.id: asset.path for asset in manifest.scenes}
        self._style_paths = {asset.id: asset.path for asset in manifest.styles}

    @classmethod
    def load(cls, root: str | Path) -> "FileTemplatePack":
        try:
            root_path = Path(root).resolve(strict=True)
            if not root_path.is_dir():
                raise ValueError
            raw_manifest = _read_json(root_path / "manifest.json")
            manifest = _parse_manifest(raw_manifest)
            listed_assets = (manifest.system, *manifest.scenes, *manifest.styles)
            paths = [asset.path for asset in listed_assets]
            if len(paths) != len(set(paths)):
                raise ValueError
            assets = {
                asset.path: _read_asset(root_path, asset.path)
                for asset in listed_assets
            }
            return cls(manifest, assets)
        except TemplatePackError:
            raise
        except Exception:
            raise TemplatePackError() from None

    @property
    def scene_ids(self) -> tuple[str, ...]:
        return tuple(self._scene_paths)

    @property
    def style_ids(self) -> tuple[str, ...]:
        return tuple(self._style_paths)

    @property
    def asset_count(self) -> int:
        return 1 + len(self._scene_paths) + len(self._style_paths)

    def read_system(self) -> str:
        return self._assets[self.manifest.system.path]

    def read_scene(self, scene_id: str) -> str:
        try:
            return self._assets[self._scene_paths[scene_id]]
        except (KeyError, TypeError):
            raise TemplatePackError() from None

    def read_style(self, style_id: str) -> str:
        try:
            return self._assets[self._style_paths[style_id]]
        except (KeyError, TypeError):
            raise TemplatePackError() from None


def _read_json(path: Path) -> dict[str, Any]:
    text = _read_bounded_utf8(path)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError
    return parsed


def _parse_manifest(raw: dict[str, Any]) -> TemplatePackManifest:
    schema_version = raw.get("schema_version")
    pack_id = raw.get("id")
    version = raw.get("version")
    default_scene = raw.get("default_scene")
    default_style = raw.get("default_style")
    if schema_version != 1:
        raise ValueError
    if not _valid_id(pack_id) or not isinstance(version, str) or not _SEMVER.fullmatch(version):
        raise ValueError
    if not _valid_id(default_scene) or not _valid_id(default_style):
        raise ValueError

    supported_modes = _string_tuple(raw.get("supported_modes"))
    supported_languages = _string_tuple(raw.get("supported_languages"))
    if not supported_modes or not set(supported_modes).issubset(_SUPPORTED_MODES):
        raise ValueError
    if not supported_languages or not set(supported_languages).issubset(_SUPPORTED_LANGUAGES):
        raise ValueError

    system = _parse_asset(raw.get("system"))
    scenes = _parse_assets(raw.get("scenes"))
    styles = _parse_assets(raw.get("styles"))
    if default_scene not in {asset.id for asset in scenes}:
        raise ValueError
    if default_style not in {asset.id for asset in styles}:
        raise ValueError
    return TemplatePackManifest(
        schema_version=schema_version,
        id=pack_id,
        version=version,
        default_scene=default_scene,
        default_style=default_style,
        supported_modes=supported_modes,
        supported_languages=supported_languages,
        system=system,
        scenes=scenes,
        styles=styles,
    )


def _parse_assets(value: object) -> tuple[TemplateAsset, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError
    assets = tuple(_parse_asset(item) for item in value)
    ids = [asset.id for asset in assets]
    if len(ids) != len(set(ids)):
        raise ValueError
    return assets


def _parse_asset(value: object) -> TemplateAsset:
    if not isinstance(value, dict):
        raise ValueError
    asset_id = value.get("id")
    path = value.get("path")
    if not _valid_id(asset_id) or not isinstance(path, str) or not _safe_asset_path(path):
        raise ValueError
    return TemplateAsset(asset_id, path)


def _read_asset(root: Path, relative_path: str) -> str:
    unresolved_candidate = root.joinpath(*PurePosixPath(relative_path).parts)
    if unresolved_candidate.is_symlink():
        raise ValueError
    candidate = unresolved_candidate.resolve(strict=True)
    if root not in candidate.parents or not candidate.is_file() or candidate.is_symlink():
        raise ValueError
    return _read_bounded_utf8(candidate)


def _read_bounded_utf8(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError
    size = path.stat().st_size
    if size <= 0 or size > _MAX_ASSET_BYTES:
        raise ValueError
    text = path.read_bytes().decode("utf-8", errors="strict")
    if not text.strip() or "\x00" in text:
        raise ValueError
    return text


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError
    normalized = tuple(item.strip() for item in value)
    if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
        raise ValueError
    return normalized


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _safe_asset_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and path.suffix == ".md"
        and all(part not in {"", ".", ".."} for part in path.parts)
    )
