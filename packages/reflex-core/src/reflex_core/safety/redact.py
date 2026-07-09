"""Secret redaction and user-safe provider errors."""

from __future__ import annotations

import re

_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def redact_sensitive(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    redacted = text
    for pattern in _PATTERNS:
        if pattern.groups:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def safe_provider_error(exc: BaseException) -> tuple[str, str, bool, str | None]:
    """Return a stable code/message without exposing the raw exception."""

    if isinstance(exc, TimeoutError):
        return "provider_timeout", "Provider request timed out.", True, "retry"
    if isinstance(exc, PermissionError):
        return "provider_authentication_failed", "Provider authentication failed.", True, "settings"
    if isinstance(exc, ConnectionError):
        return "provider_unavailable", "Provider service is unavailable.", True, "retry"
    return "provider_error", "Provider request failed.", True, "retry"
