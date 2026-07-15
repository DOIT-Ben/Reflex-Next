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


def test_privacy_policy_version_is_server_owned_and_path_safe():
    assert CloudSettings().privacy_policy_version == "2026-07-14"
    with pytest.raises(ValidationError):
        CloudSettings(privacy_policy_version="../policy")
