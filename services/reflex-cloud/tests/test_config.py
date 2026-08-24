from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from reflex_cloud.config import CloudSettings
from reflex_cloud.security import redact_text


def test_production_rejects_default_or_short_secrets(tmp_path):
    with pytest.raises(ValidationError):
        CloudSettings(
            environment="production",
            database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
            upload_directory=tmp_path / "uploads",
        )

    with pytest.raises(ValidationError):
        CloudSettings(
            environment="production",
            database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
            upload_directory=tmp_path / "uploads",
            admin_token=SecretStr("a" * 32),
            token_pepper=SecretStr("p" * 32),
            provider_api_key=SecretStr("k" * 32),
            provider_pricing_version="fixture-pricing-1",
            provider_input_usd_per_million_tokens=1,
            provider_output_usd_per_million_tokens=2,
        )

    settings = CloudSettings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
        upload_directory=tmp_path / "uploads",
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
        provider_api_key=SecretStr("k" * 32),
        provider_pricing_version="fixture-pricing-1",
        provider_input_usd_per_million_tokens=1,
        provider_output_usd_per_million_tokens=2,
        global_daily_request_limit=1000,
        global_daily_cost_budget_microusd=5_000_000,
    )
    assert settings.environment == "production"


def test_redaction_removes_common_secret_shapes_without_removing_normal_text():
    source = "Bearer test-token-value-123 api_key=not-a-real-value-123456 sk-private123456789012345"

    redacted = redact_text(source)

    assert "test-token" not in redacted
    assert "not-a-real" not in redacted
    assert "sk-private" not in redacted
    assert redacted.count("<redacted>") == 3


@pytest.mark.parametrize(
    "secret",
    [
        "gh" + "p_" + ("a" * 36),
        "AK" + "IA" + ("A" * 16),
        "ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456",
        "https://hooks.slack.com/" + "services/T00000000/B00000000/" + ("a" * 24),
        "AI" + "za" + ("A" * 35),
        "sk_" + "live_" + ("a" * 24),
        "-----BEGIN " + "PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----",
    ],
)
def test_redaction_removes_standalone_high_risk_credentials(secret: str):
    redacted = redact_text(f"before {secret} after")

    assert secret not in redacted
    assert "before" in redacted
    assert "after" in redacted
    assert "<redacted>" in redacted


def test_privacy_policy_version_is_server_owned_and_path_safe():
    assert CloudSettings().privacy_policy_version == "2026-07-14"
    with pytest.raises(ValidationError):
        CloudSettings(privacy_policy_version="../policy")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("installation_limit_per_ip_per_hour", 0),
        ("feedback_limit_per_ip_per_hour", 0),
        ("feedback_attachment_bytes_per_ip_per_day", 1023),
        ("trusted_proxy_cidrs", "not-a-network"),
    ],
)
def test_abuse_protection_settings_reject_unsafe_values(field: str, value: object):
    with pytest.raises(ValidationError):
        CloudSettings(**{field: value})


def test_abuse_protection_defaults_are_enabled_and_forwarded_headers_are_untrusted():
    settings = CloudSettings()

    assert settings.installation_limit_per_ip_per_hour > 0
    assert settings.feedback_limit_per_ip_per_hour > 0
    assert settings.feedback_attachment_bytes_per_ip_per_day > 0
    assert settings.trusted_proxy_cidrs == ""


@pytest.mark.parametrize(
    "provider_base_url",
    [
        "https://api.minimaxi.com@attacker.example/v1/chat/completions",
        "https://user@api.minimaxi.com/v1/chat/completions",
        "https://attacker.example/v1/chat/completions",
        "https://127.0.0.1/v1/chat/completions",
        "https://api.minimaxi.com/v1/chat/completions?redirect=attacker.example",
        "https://api.minimaxi.com/v1/chat/completions#fragment",
    ],
)
def test_production_rejects_unsafe_provider_urls(tmp_path, provider_base_url: str):
    with pytest.raises(ValidationError):
        CloudSettings(
            environment="production",
            database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
            upload_directory=tmp_path / "uploads",
            admin_token=SecretStr("a" * 32),
            token_pepper=SecretStr("p" * 32),
            provider_api_key=SecretStr("k" * 32),
            provider_base_url=provider_base_url,
            provider_pricing_version="fixture-pricing-1",
            provider_input_usd_per_million_tokens=1,
            provider_output_usd_per_million_tokens=2,
            global_daily_request_limit=1000,
            global_daily_cost_budget_microusd=5_000_000,
        )
