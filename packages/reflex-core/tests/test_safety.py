from reflex_core.safety import redact_sensitive, safe_provider_error, sanitize_text, validate_input


def test_redact_sensitive_removes_common_secret_forms():
    text = "Authorization: Bearer abc123 api_key=secret-value sk-abcdefgh123456"
    redacted = redact_sensitive(text)

    assert "abc123" not in redacted
    assert "secret-value" not in redacted
    assert "sk-abcdefgh123456" not in redacted
    assert "[REDACTED]" in redacted


def test_safe_provider_error_never_returns_raw_exception_text():
    secret = "api_key=do-not-leak"
    code, message, recoverable, action = safe_provider_error(RuntimeError(secret))

    assert code == "provider_error"
    assert secret not in message
    assert recoverable is True
    assert action == "retry"


def test_sanitize_text_removes_null_and_control_characters():
    assert sanitize_text("a\x00b\x01\r\nc") == "ab\nc"


def test_validate_input_returns_trimmed_text():
    assert validate_input("  hello  ") == "hello"
