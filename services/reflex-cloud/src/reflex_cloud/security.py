from __future__ import annotations

import hashlib
import hmac
import re
import secrets


_REDACTION_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)"
        r"\s*[:=]\s*[^\s,;]{8,}"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
)


def new_installation_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def secure_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
