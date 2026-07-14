from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_DEVELOPMENT_SECRET = "development-only-secret-change-before-deploy"


class CloudSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REFLEX_CLOUD_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "sqlite:///./data/reflex-cloud.db"
    upload_directory: Path = Path("./data/uploads")
    admin_token: SecretStr = SecretStr(_DEVELOPMENT_SECRET)
    token_pepper: SecretStr = SecretStr(_DEVELOPMENT_SECRET)
    retention_days: int = Field(default=90, ge=1, le=3650)
    feedback_limit_per_hour: int = Field(default=10, ge=1, le=1000)
    free_requests_per_day: int = Field(default=20, ge=1, le=10000)
    free_input_chars_per_day: int = Field(default=200_000, ge=1_000, le=10_000_000)
    free_output_chars_per_day: int = Field(default=200_000, ge=1_000, le=10_000_000)
    max_screenshot_bytes: int = Field(default=3 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    provider_api_key: SecretStr = SecretStr("")
    provider_base_url: str = "https://api.minimaxi.com/v1/chat/completions"
    provider_model: str = "MiniMax-M2.7-highspeed"
    provider_timeout_seconds: float = Field(default=90.0, ge=5.0, le=120.0)
    provider_pricing_version: str = Field(default="unconfigured", min_length=1, max_length=64)
    provider_input_usd_per_million_tokens: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), le=Decimal("10000")
    )
    provider_output_usd_per_million_tokens: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"), le=Decimal("10000")
    )
    provider_estimated_chars_per_token: Decimal = Field(
        default=Decimal("2"), gt=Decimal("0"), le=Decimal("100")
    )
    template_pack_directory: Path = Path("../../template-packs/builtin")
    max_concurrent_global: int = Field(default=32, ge=1, le=1000)
    max_concurrent_per_installation: int = Field(default=2, ge=1, le=20)
    free_ip_requests_per_hour: int = Field(default=60, ge=1, le=10000)
    retention_cleanup_interval_seconds: int = Field(default=86_400, ge=60, le=604_800)

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("invalid environment")
        return normalized

    @model_validator(mode="after")
    def reject_development_secrets_in_production(self) -> "CloudSettings":
        if self.environment != "production":
            return self
        secrets = (
            self.admin_token.get_secret_value(),
            self.token_pepper.get_secret_value(),
            self.provider_api_key.get_secret_value(),
        )
        if any(secret == _DEVELOPMENT_SECRET or len(secret) < 32 for secret in secrets):
            raise ValueError("production secrets must be independently configured")
        if not self.provider_base_url.startswith("https://"):
            raise ValueError("production provider URL must use HTTPS")
        if (
            self.provider_pricing_version == "unconfigured"
            or self.provider_input_usd_per_million_tokens <= 0
            or self.provider_output_usd_per_million_tokens <= 0
        ):
            raise ValueError("production provider pricing must be configured")
        return self
