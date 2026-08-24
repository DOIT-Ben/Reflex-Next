from __future__ import annotations

import base64
import binascii
from pathlib import Path
import shutil

from .schemas import ScreenshotInput


class AttachmentError(ValueError):
    pass


class AttachmentStore:
    def __init__(self, directory: Path, max_bytes: int) -> None:
        self.directory = directory.resolve()
        self.max_bytes = max_bytes
        self.directory.mkdir(parents=True, exist_ok=True)

    def save_screenshot(self, feedback_id: str, screenshot: ScreenshotInput) -> str:
        raw = self.validate_screenshot(screenshot)
        return self.save_validated_screenshot(feedback_id, screenshot.media_type, raw)

    def validate_screenshot(self, screenshot: ScreenshotInput) -> bytes:
        try:
            raw = base64.b64decode(screenshot.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise AttachmentError("invalid screenshot encoding") from None
        if not raw or len(raw) > self.max_bytes:
            raise AttachmentError("invalid screenshot size")
        _validated_extension(raw, screenshot.media_type)
        return raw

    def save_validated_screenshot(
        self, feedback_id: str, media_type: str, raw: bytes
    ) -> str:
        extension = _validated_extension(raw, media_type)
        target = (self.directory / f"{feedback_id}.{extension}").resolve()
        if target.parent != self.directory:
            raise AttachmentError("invalid screenshot path")
        target.write_bytes(raw)
        return target.name

    def has_capacity(self, additional_bytes: int, minimum_free_bytes: int) -> bool:
        if additional_bytes < 0 or minimum_free_bytes < 0:
            return False
        try:
            free_bytes = shutil.disk_usage(self.directory).free
        except OSError:
            return False
        return free_bytes - additional_bytes >= minimum_free_bytes

    def path_for(self, relative_path: str) -> Path | None:
        target = (self.directory / relative_path).resolve()
        if target.parent != self.directory or not target.is_file():
            return None
        return target

    def delete(self, relative_path: str | None) -> None:
        if not relative_path:
            return
        target = self.path_for(relative_path)
        if target is not None:
            target.unlink(missing_ok=True)


def _validated_extension(raw: bytes, media_type: str) -> str:
    if media_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if media_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    raise AttachmentError("screenshot content does not match media type")
