from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


FeedbackSentiment = Literal["positive", "negative"]
FeedbackCategory = Literal["quality", "bug", "performance", "feature", "other"]
FeedbackSource = Literal["manual", "prompt"]
FeedbackStatus = Literal["new", "triaged", "reproduced", "planned", "fixed", "released", "rejected"]
QualityReleaseStatus = Literal["draft", "published", "superseded", "rolled_back"]
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
    source: FeedbackSource = "manual"
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
    source: FeedbackSource
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


class QualityReleaseCreate(BaseModel):
    release_version: str = Field(
        min_length=5,
        max_length=64,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$",
    )
    template_pack_version: str = Field(
        min_length=5,
        max_length=64,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?$",
    )
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=2000)
    global_guidance: str = Field(default="", max_length=4000)
    scene_guidance: dict[str, str] = Field(default_factory=dict)
    source_feedback_ids: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def normalize_curated_release(self) -> "QualityReleaseCreate":
        self.title = self.title.strip()
        self.summary = self.summary.strip()
        self.global_guidance = self.global_guidance.strip()
        if not self.title or not self.summary:
            raise ValueError("release title and summary must not be blank")
        if len(self.source_feedback_ids) != len(set(self.source_feedback_ids)):
            raise ValueError("source feedback ids must be unique")
        if any(
            not re.fullmatch(r"^[A-Za-z0-9-]{8,64}$", item)
            for item in self.source_feedback_ids
        ):
            raise ValueError("invalid source feedback id")
        if len(self.scene_guidance) > 32:
            raise ValueError("too many scene guidance entries")
        normalized: dict[str, str] = {}
        total_chars = len(self.global_guidance)
        for scene, guidance in self.scene_guidance.items():
            if not re.fullmatch(r"^[a-z0-9][a-z0-9._-]{0,63}$", scene):
                raise ValueError("invalid scene guidance id")
            value = guidance.strip()
            if not value or len(value) > 4000:
                raise ValueError("invalid scene guidance")
            total_chars += len(value)
            normalized[scene] = value
        if not self.global_guidance and not normalized:
            raise ValueError("release guidance must not be empty")
        if total_chars > 20_000:
            raise ValueError("release guidance is too large")
        self.scene_guidance = normalized
        return self


class QualityReleasePublic(BaseModel):
    id: str
    release_version: str
    template_pack_version: str
    title: str
    summary: str
    source_feedback_count: int
    published_at: datetime


class QualityReleaseSummary(BaseModel):
    id: str
    release_version: str
    template_pack_version: str
    title: str
    summary: str
    status: QualityReleaseStatus
    source_feedback_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    rolled_back_at: datetime | None


class QualityReleaseDetail(QualityReleaseSummary):
    global_guidance: str
    scene_guidance: dict[str, str]
    source_feedback_ids: list[str]


class QualityReleasePage(BaseModel):
    items: list[QualityReleaseSummary]
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
    by_source: dict[str, QualityBucket]
    by_category: dict[str, QualityBucket]
    by_version: dict[str, QualityBucket]
    by_scene: dict[str, QualityBucket]
    by_provider_model: dict[str, QualityBucket]
    by_quality_release: dict[str, QualityBucket]


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
    daily_budget_date: str
    daily_request_limit: int | None
    daily_requests_used: int
    daily_requests_remaining: int | None
    daily_request_usage_ratio: float | None
    daily_cost_budget_microusd: int | None
    daily_cost_used_microusd: int
    daily_cost_reserved_microusd: int
    daily_cost_committed_microusd: int
    daily_cost_remaining_microusd: int | None
    daily_cost_usage_ratio: float | None
    budget_exceeded: bool


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
