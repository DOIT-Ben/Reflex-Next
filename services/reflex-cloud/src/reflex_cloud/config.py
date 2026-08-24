from __future__ import annotations

from ipaddress import ip_address, ip_network
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

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
    privacy_policy_version: str = Field(
        default="2026-07-14",
        min_length=1,
        max_length=32,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    retention_days: int = Field(default=90, ge=1, le=3650)
    feedback_limit_per_hour: int = Field(default=10, ge=1, le=1000)
    installation_limit_per_ip_per_hour: int = Field(default=20, ge=1, le=1000)
    feedback_limit_per_ip_per_hour: int = Field(default=30, ge=1, le=1000)
    feedback_attachment_bytes_per_ip_per_day: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024
    )
    global_daily_feedback_limit: int = Field(default=10_000, ge=1, le=10_000_000)
    global_daily_feedback_attachment_bytes: int = Field(
        default=1024 * 1024 * 1024, ge=1024, le=1024**5
    )
    feedback_attachment_min_free_bytes: int = Field(
        default=512 * 1024 * 1024, ge=0, le=1024**5
    )
    trusted_proxy_cidrs: str = ""
    free_requests_per_day: int = Field(default=20, ge=1, le=10000)
    free_input_chars_per_day: int = Field(default=200_000, ge=1_000, le=10_000_000)
    free_output_chars_per_day: int = Field(default=200_000, ge=1_000, le=10_000_000)
    max_screenshot_bytes: int = Field(default=3 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    provider_api_key: SecretStr = SecretStr("")
    provider_base_url: str = "https://api.minimaxi.com/v1/chat/completions"
    provider_allowed_hosts: str = "api.minimaxi.com"
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
    global_daily_request_limit: int = Field(default=0, ge=0, le=1_000_000)
    global_daily_cost_budget_microusd: int = Field(default=0, ge=0, le=2_000_000_000)
    budget_max_output_chars_per_request: int = Field(default=200_000, ge=1, le=2_100_000)
    budget_reservation_ttl_seconds: int = Field(default=600, ge=60, le=3_600)
    retention_cleanup_interval_seconds: int = Field(default=86_400, ge=60, le=604_800)

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("invalid environment")
        return normalized

    @field_validator("trusted_proxy_cidrs")
    @classmethod
    def validate_trusted_proxy_cidrs(cls, value: str) -> str:
        networks = []
        for item in value.split(","):
            item = item.strip()
            if item:
                networks.append(str(ip_network(item, strict=False)))
        return ",".join(networks)

    @field_validator("provider_allowed_hosts")
    @classmethod
    def validate_provider_allowed_hosts(cls, value: str) -> str:
        hosts: list[str] = []
        for item in value.split(","):
            host = item.strip().lower().rstrip(".")
            if not host or len(host) > 253 or any(
                character.isspace() or ord(character) < 32 for character in host
            ):
                raise ValueError("invalid provider host allowlist")
            if any(character in host for character in "/@?#:"):
                raise ValueError("invalid provider host allowlist")
            try:
                address = ip_address(host)
            except ValueError:
                labels = host.split(".")
                if any(
                    not label
                    or len(label) > 63
                    or label.startswith("-")
                    or label.endswith("-")
                    or not all(character.isalnum() or character == "-" for character in label)
                    for label in labels
                ):
                    raise ValueError("invalid provider host allowlist") from None
            else:
                if not address.is_global:
                    raise ValueError("invalid provider host allowlist")
            if host not in hosts:
                hosts.append(host)
        if not hosts:
            raise ValueError("provider host allowlist is required")
        return ",".join(hosts)

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
        try:
            provider_url = urlsplit(self.provider_base_url)
            provider_port = provider_url.port
        except ValueError:
            raise ValueError("invalid production provider URL") from None
        provider_host = (provider_url.hostname or "").lower().rstrip(".")
        allowed_hosts = set(self.provider_allowed_hosts.split(","))
        if (
            provider_url.scheme != "https"
            or not provider_host
            or provider_url.username is not None
            or provider_url.password is not None
            or provider_port not in {None, 443}
            or provider_url.path != "/v1/chat/completions"
            or provider_url.query
            or provider_url.fragment
            or provider_host not in allowed_hosts
            or any(
                character.isspace() or ord(character) < 32
                for character in self.provider_base_url
            )
        ):
            raise ValueError("invalid production provider URL")
        try:
            provider_address = ip_address(provider_host)
        except ValueError:
            pass
        else:
            if not provider_address.is_global:
                raise ValueError("invalid production provider URL")
        if (
            self.provider_pricing_version == "unconfigured"
            or self.provider_input_usd_per_million_tokens <= 0
            or self.provider_output_usd_per_million_tokens <= 0
        ):
            raise ValueError("production provider pricing must be configured")
        if (
            self.global_daily_request_limit <= 0
            or self.global_daily_cost_budget_microusd <= 0
        ):
            raise ValueError("production global budgets must be configured")
        return self
