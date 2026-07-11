import pytest

from reflex_core.safety import (
    HistoryRedactionPolicy,
    redact_for_history,
    redact_sensitive,
    safe_provider_error,
    sanitize_text,
    validate_input,
)


def test_redact_sensitive_removes_common_secret_forms():
    text = (
        "Authorization: Bearer bearer-fixture-key "
        "api_key=api-fixture-key sk-history-fixture-key"
    )
    redacted = redact_sensitive(text)

    assert "bearer-fixture-key" not in redacted
    assert "api-fixture-key" not in redacted
    assert "sk-history-fixture-key" not in redacted
    assert "[REDACTED]" in redacted


def test_safe_provider_error_never_returns_raw_exception_text():
    secret = "api_key=provider-fixture-key"
    code, message, recoverable, action = safe_provider_error(RuntimeError(secret))

    assert code == "provider_error"
    assert secret not in message
    assert recoverable is True
    assert action == "retry"


def test_safe_provider_error_maps_only_approved_provider_codes():
    class PluginFailure(RuntimeError):
        code = "provider_rate_limited"

    assert safe_provider_error(PluginFailure("raw provider response")) == (
        "provider_rate_limited",
        "Provider rate limit reached.",
        True,
        "retry",
    )

    PluginFailure.code = "unapproved_error"
    code, message, recoverable, action = safe_provider_error(
        PluginFailure("Bearer fixture-private-value")
    )
    assert (code, message, recoverable, action) == (
        "provider_error",
        "Provider request failed.",
        True,
        "retry",
    )
    assert "fixture-private-value" not in message


def test_sanitize_text_removes_null_and_control_characters():
    assert sanitize_text("a\x00b\x01\r\nc") == "ab\nc"


def test_validate_input_returns_trimmed_text():
    assert validate_input("  hello  ") == "hello"


def test_redact_for_history_reuses_secret_redaction_without_mutating_input():
    original = "Authorization: Bearer history-fixture-key api_key=history-fixture-secret"

    redacted = redact_for_history(original, HistoryRedactionPolicy.SECRETS)

    assert original.endswith("history-fixture-secret")
    assert "history-fixture-key" not in redacted
    assert "history-fixture-secret" not in redacted
    assert redact_for_history(redacted, HistoryRedactionPolicy.SECRETS) == redacted


def test_redact_for_history_none_returns_the_original_text():
    original = "Bearer history-fixture-key"

    assert redact_for_history(original, HistoryRedactionPolicy.NONE) == original
    assert redact_for_history(original, "none") == original


def test_history_redaction_policy_rejects_unknown_values():
    with pytest.raises(ValueError):
        HistoryRedactionPolicy("raw")

    with pytest.raises(ValueError):
        redact_for_history("text", "raw")
