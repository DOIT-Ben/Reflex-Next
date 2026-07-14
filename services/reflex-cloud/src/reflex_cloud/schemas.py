from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


FeedbackSentiment = Literal["positive", "negative"]
FeedbackCategory = Literal["quality", "bug", "performance", "feature", "other"]
FeedbackStatus = Literal["new", "triaged", "reproduced", "planned", "fixed", "released", "rejected"]


class InstallationCreated(BaseModel):
    installation_id: str
    token: str


class ConsentUpdate(BaseModel):
    usage_metrics: bool = False
    improvement_data: bool = False
    feedback_attachments: bool = False
    policy_version: str = Field(min_length=1, max_length=32)


class ConsentView(ConsentUpdate):
    updated_at: datetime | None = None


class FeedbackContext(BaseModel):
    app_version: str = Field(min_length=1, max_length=64)
    os_version: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    mode: str = Field(default="", max_length=32)
    style: str = Field(default="", max_length=32)
    scene: str = Field(default="", max_length=64)
    request_id: str = Field(default="", max_length=128)
    diagnostic_id: str = Field(default="", max_length=128)
    error_code: str = Field(default="", max_length=64)
    elapsed_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class ScreenshotInput(BaseModel):
    media_type: Literal["image/png", "image/jpeg"]
    data_base64: str = Field(min_length=4, max_length=14_000_000)


class FeedbackCreate(BaseModel):
    sentiment: FeedbackSentiment
    category: FeedbackCategory
    message: str = Field(default="", max_length=4000)
    expected_output: str = Field(default="", max_length=10_000)
    contact: str = Field(default="", max_length=320)
    context: FeedbackContext
    include_prompt: bool = False
    include_result: bool = False
    include_screenshot: bool = False
    prompt_text: str | None = Field(default=None, max_length=100_000)
    result_text: str | None = Field(default=None, max_length=100_000)
    screenshot: ScreenshotInput | None = None
    consent_version: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def enforce_attachment_consent(self) -> "FeedbackCreate":
        if bool(self.prompt_text) != self.include_prompt:
            raise ValueError("prompt attachment and consent must match")
        if bool(self.result_text) != self.include_result:
            raise ValueError("result attachment and consent must match")
        if (self.screenshot is not None) != self.include_screenshot:
            raise ValueError("screenshot attachment and consent must match")
        if self.sentiment == "negative" and not self.message.strip() and self.category == "other":
            raise ValueError("negative feedback requires a category or message")
        return self


class FeedbackCreated(BaseModel):
    id: str
    status: FeedbackStatus
    created_at: datetime


class FeedbackSummary(BaseModel):
    id: str
    sentiment: FeedbackSentiment
    category: FeedbackCategory
    status: FeedbackStatus
    app_version: str
    provider: str
    model: str
    error_code: str
    has_prompt: bool
    has_result: bool
    has_screenshot: bool
    created_at: datetime


class FeedbackDetail(FeedbackSummary):
    message: str
    expected_output: str
    contact: str
    context: FeedbackContext
    prompt_text: str | None
    result_text: str | None
    screenshot_url: str | None
    consent_version: str


class FeedbackPage(BaseModel):
    items: list[FeedbackSummary]
    total: int


class FeedbackUpdate(BaseModel):
    status: FeedbackStatus
    category: FeedbackCategory | None = None


class DeleteResult(BaseModel):
    deleted: bool
