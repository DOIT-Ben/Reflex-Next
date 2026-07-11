"""Pure redaction policy for text persisted by history plugins."""

from __future__ import annotations

from enum import Enum

from .redact import redact_sensitive


class HistoryRedactionPolicy(str, Enum):
    SECRETS = "secrets"
    NONE = "none"


def redact_for_history(
    text: str, policy: HistoryRedactionPolicy | str
) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    normalized_policy = HistoryRedactionPolicy(policy)
    if normalized_policy is HistoryRedactionPolicy.NONE:
        return text
    return redact_sensitive(text)
