"""Pure response sanitization."""

from __future__ import annotations


def sanitize_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return "".join(char for char in normalized if char in "\n\t" or ord(char) >= 32)
