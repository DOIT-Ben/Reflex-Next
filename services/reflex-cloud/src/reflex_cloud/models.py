from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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
