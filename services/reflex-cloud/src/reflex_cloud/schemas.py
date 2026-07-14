from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


FeedbackSentiment = Literal["positive", "negative"]
FeedbackCategory = Literal["quality", "bug", "performance", "feature", "other"]
FeedbackStatus = Literal["new", "triaged", "reproduced", "planned", "fixed", "released", "rejected"]
OptimizeMode = Literal["content", "prompt"]
OptimizeStyle = Literal["concise", "balanced", "detailed", "creative", "precise"]
ScenePolicy = Literal["auto", "manual", "ask"]


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


class QualityBucket(BaseModel):
    total: int
    negative: int
    negative_rate: float
    average_elapsed_ms: float | None


class FeedbackAnalytics(BaseModel):
    total: int
    negative: int
    negative_rate: float
    average_elapsed_ms: float | None
    by_category: dict[str, QualityBucket]
    by_version: dict[str, QualityBucket]


class UsageBucket(BaseModel):
    requests: int
    completed_requests: int
    input_chars: int
    output_chars: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_microusd: int


class UsageAnalytics(UsageBucket):
    from_date: str
    to_date: str
    pricing_configured: bool
    pricing_version: str
    by_day: dict[str, UsageBucket]
    by_provider_model: dict[str, UsageBucket]


class FeedbackUpdate(BaseModel):
    status: FeedbackStatus
    category: FeedbackCategory | None = None


class DeleteResult(BaseModel):
    deleted: bool


class QuotaView(BaseModel):
    usage_date: str
    requests_used: int
    requests_limit: int
    input_chars_used: int
    input_chars_limit: int
    output_chars_used: int
    output_chars_limit: int


class CloudOptimizeRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    text: str = Field(min_length=1, max_length=100_000)
    mode: OptimizeMode = "content"
    style: OptimizeStyle = "balanced"
    scene: str | None = Field(default=None, max_length=64)
    scene_policy: ScenePolicy = "auto"
    language: Literal["zh-CN", "en-US"] = "zh-CN"

    @model_validator(mode="after")
    def require_scene_for_manual_policy(self) -> "CloudOptimizeRequest":
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("text must not be blank")
        if self.scene_policy == "manual" and not self.scene:
            raise ValueError("manual scene policy requires scene")
        return self


class OptimizeCancelRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class OptimizeCancelResult(BaseModel):
    cancelled: bool
