"""Pure input validation."""

from __future__ import annotations


class InputValidationError(ValueError):
    """User input is invalid without exposing the input itself."""


def validate_input(text: str, *, max_length: int = 100_000) -> str:
    if not isinstance(text, str):
        raise InputValidationError("Input must be text.")
    normalized = text.strip()
    if not normalized:
        raise InputValidationError("Input is empty.")
    if len(normalized) > max_length:
        raise InputValidationError("Input is too long.")
    return normalized
