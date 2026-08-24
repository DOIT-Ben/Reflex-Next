from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Installation(Base):
    __tablename__ = "installations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    feedback: Mapped[list["FeedbackItem"]] = relationship(
        back_populates="installation", cascade="all, delete-orphan"
    )
    consents: Mapped[list["ConsentRecord"]] = relationship(
        back_populates="installation", cascade="all, delete-orphan"
    )


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    usage_metrics: Mapped[bool] = mapped_column(Boolean, default=False)
    improvement_data: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    policy_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    installation: Mapped[Installation] = relationship(back_populates="consents")


class DailyUsage(Base):
    __tablename__ = "daily_usage"
    __table_args__ = (UniqueConstraint("installation_id", "usage_date", name="daily_usage_installation_date_uq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)


class DailyCostAggregate(Base):
    __tablename__ = "daily_cost_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "usage_date",
            "provider",
            "model",
            "pricing_version",
            name="daily_cost_provider_model_pricing_uq",
        ),
        Index("daily_cost_created_idx", "usage_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    pricing_version: Mapped[str] = mapped_column(String(64))
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    estimated_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_microusd: Mapped[int] = mapped_column(Integer, default=0)


class DailyBudgetLedger(Base):
    __tablename__ = "daily_budget_ledgers"

    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    admitted_requests: Mapped[int] = mapped_column(Integer, default=0)
    settled_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    __table_args__ = (Index("budget_reservation_status_expiry_idx", "status", "expires_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    estimated_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    settled_cost_microusd: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(16), default="reserved", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class HourlyIpUsage(Base):
    __tablename__ = "hourly_ip_usage"
    __table_args__ = (
        UniqueConstraint("ip_hash", "window_start", name="hourly_ip_hash_window_uq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class ClientAbuseUsage(Base):
    __tablename__ = "client_abuse_usage"
    __table_args__ = (
        UniqueConstraint(
            "ip_hash", "scope", "window_start", name="client_abuse_scope_window_uq"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    attachment_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class QualityRelease(Base):
    __tablename__ = "quality_releases"
    __table_args__ = (
        Index("quality_release_created_idx", "created_at"),
        Index(
            "quality_release_one_published_uq",
            "status",
            unique=True,
            sqlite_where=text("status = 'published'"),
            postgresql_where=text("status = 'published'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    release_version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    template_pack_version: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(160))
    summary: Mapped[str] = mapped_column(Text)
    global_guidance: Mapped[str] = mapped_column(Text, default="")
    scene_guidance_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class QualityReleaseSource(Base):
    __tablename__ = "quality_release_sources"
    __table_args__ = (Index("quality_release_source_feedback_idx", "feedback_id"),)

    release_id: Mapped[str] = mapped_column(
        ForeignKey("quality_releases.id", ondelete="CASCADE"), primary_key=True
    )
    feedback_id: Mapped[str] = mapped_column(
        ForeignKey("feedback_items.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QualityExposure(Base):
    __tablename__ = "quality_exposures"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "request_id",
            name="quality_exposure_installation_request_uq",
        ),
        Index("quality_exposure_release_created_idx", "release_version", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    quality_release_id: Mapped[str | None] = mapped_column(
        ForeignKey("quality_releases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_id: Mapped[str] = mapped_column(String(128))
    release_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ImprovementSample(Base):
    __tablename__ = "improvement_samples"
    __table_args__ = (
        UniqueConstraint("installation_id", "request_id", name="improvement_installation_request_uq"),
        Index("improvement_created_idx", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    consent_record_id: Mapped[int] = mapped_column(
        ForeignKey("consent_records.id", ondelete="CASCADE"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128))
    prompt_text: Mapped[str] = mapped_column(Text)
    result_text: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(32))
    style: Mapped[str] = mapped_column(String(32))
    scene: Mapped[str] = mapped_column(String(64), default="")
    provider: Mapped[str] = mapped_column(String(64), default="minimax")
    model: Mapped[str] = mapped_column(String(128))
    policy_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class FeedbackItem(Base):
    __tablename__ = "feedback_items"
    __table_args__ = (
        Index("feedback_status_created_idx", "status", "created_at"),
        Index("feedback_installation_created_idx", "installation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    installation_id: Mapped[str] = mapped_column(
        ForeignKey("installations.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    sentiment: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="new")
    message: Mapped[str] = mapped_column(Text, default="")
    expected_output: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(320), default="")
    app_version: Mapped[str] = mapped_column(String(64))
    os_version: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    mode: Mapped[str] = mapped_column(String(32), default="")
    style: Mapped[str] = mapped_column(String(32), default="")
    scene: Mapped[str] = mapped_column(String(64), default="")
    request_id: Mapped[str] = mapped_column(String(128), default="")
    diagnostic_id: Mapped[str] = mapped_column(String(128), default="")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    include_prompt: Mapped[bool] = mapped_column(Boolean, default=False)
    include_result: Mapped[bool] = mapped_column(Boolean, default=False)
    include_screenshot: Mapped[bool] = mapped_column(Boolean, default=False)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    screenshot_media_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    installation: Mapped[Installation] = relationship(back_populates="feedback")
