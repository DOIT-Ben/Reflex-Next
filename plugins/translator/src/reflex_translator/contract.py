"""Strict public contracts for the translator plugin."""

from __future__ import annotations

import re
from dataclasses import dataclass

from reflex_core.safety import InputValidationError, validate_input

TARGET_LANGUAGES = frozenset({"auto", "zh", "en"})
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class TranslatorPluginError(RuntimeError):
    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or _SAFE_ERROR_CODE.fullmatch(code) is None:
            raise ValueError("invalid translator error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TranslationRequest:
    text: str
    source_language: str
    target_language: str

    @classmethod
    def from_payload(cls, payload: object) -> "TranslationRequest":
        if not isinstance(payload, dict) or set(payload) != {"text", "target"}:
            raise TranslatorPluginError("translation_payload_invalid")
        target = payload.get("target")
        if target not in TARGET_LANGUAGES:
            raise TranslatorPluginError("translation_payload_invalid")
        try:
            text = validate_input(payload.get("text"))
        except (InputValidationError, TypeError):
            raise TranslatorPluginError("translation_payload_invalid") from None
        source = detect_language(text)
        resolved_target = ("en" if source == "zh" else "zh") if target == "auto" else target
        return cls(text=text, source_language=source, target_language=resolved_target)


def detect_language(text: str) -> str:
    return "zh" if any("\u4e00" <= character <= "\u9fff" for character in text[:100]) else "en"
