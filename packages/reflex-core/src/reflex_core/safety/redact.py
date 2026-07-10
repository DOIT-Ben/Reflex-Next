"""Secret redaction and user-safe provider errors."""

from __future__ import annotations

import re

_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:api[_-]?key|token|secret)\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)

_APPROVED_PROVIDER_ERRORS = {
    "provider_unconfigured": ("Provider is not configured.", True, "settings"),
    "provider_auth_failed": ("Provider authentication failed.", True, "settings"),
    "provider_rate_limited": ("Provider rate limit reached.", True, "retry"),
    "provider_timeout": ("Provider request timed out.", True, "retry"),
    "provider_network_error": ("Provider network request failed.", True, "retry"),
    "provider_service_error": ("Provider service is unavailable.", True, "retry"),
    "provider_invalid_response": ("Provider response was invalid.", True, "retry"),
    "provider_empty_response": ("Provider returned no content.", True, "retry"),
    "cancelled": ("Generation cancelled.", True, None),
}


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

    provider_code = getattr(exc, "code", None)
    if isinstance(provider_code, str) and provider_code in _APPROVED_PROVIDER_ERRORS:
        message, recoverable, action = _APPROVED_PROVIDER_ERRORS[provider_code]
        return provider_code, message, recoverable, action
    if isinstance(exc, TimeoutError):
        return "provider_timeout", "Provider request timed out.", True, "retry"
    if isinstance(exc, PermissionError):
        return "provider_authentication_failed", "Provider authentication failed.", True, "settings"
    if isinstance(exc, ConnectionError):
        return "provider_unavailable", "Provider service is unavailable.", True, "retry"
    return "provider_error", "Provider request failed.", True, "retry"
