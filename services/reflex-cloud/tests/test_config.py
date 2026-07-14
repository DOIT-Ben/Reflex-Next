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

    settings = CloudSettings(
        environment="production",
        database_url=f"sqlite:///{tmp_path / 'cloud.db'}",
        upload_directory=tmp_path / "uploads",
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
        provider_api_key=SecretStr("k" * 32),
    )
    assert settings.environment == "production"


def test_redaction_removes_common_secret_shapes_without_removing_normal_text():
    source = "Bearer secret-token-value-123 api_key=secret-value-123456 sk-private123456789012345"

    redacted = redact_text(source)

    assert "secret-token" not in redacted
    assert "secret-value" not in redacted
    assert "sk-private" not in redacted
    assert redacted.count("<redacted>") == 3
