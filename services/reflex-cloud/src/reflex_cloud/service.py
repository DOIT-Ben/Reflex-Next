from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from threading import Lock
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import CloudSettings
from .models import (
    ConsentRecord,
    DailyCostAggregate,
    DailyUsage,
    FeedbackItem,
    HourlyIpUsage,
    ImprovementSample,
    Installation,
    utc_now,
)
from .schemas import (
    CloudOptimizeRequest,
    ConsentUpdate,
    FeedbackAnalytics,
    FeedbackCreate,
    FeedbackUpdate,
    QualityBucket,
    QuotaView,
    UsageAnalytics,
    UsageBucket,
)
from .security import new_installation_token, redact_text, token_hash
from .storage import AttachmentStore


class CloudServiceError(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class CloudService:
    def __init__(self, settings: CloudSettings, attachments: AttachmentStore) -> None:
        self.settings = settings
        self.attachments = attachments
        self._pepper = settings.token_pepper.get_secret_value()
        self._quota_lock = Lock()

    def create_installation(self, session: Session) -> tuple[Installation, str]:
        token = new_installation_token()
        installation = Installation(
            id=str(uuid4()),
            token_hash=token_hash(token, self._pepper),
        )
        session.add(installation)
        session.add(
            ConsentRecord(
                installation=installation,
                usage_metrics=False,
                improvement_data=False,
                feedback_attachments=False,
                policy_version="2026-07-14",
            )
        )
        session.commit()
        return installation, token

    def authenticate_installation(self, session: Session, token: str) -> Installation:
        if not token or len(token) > 256:
            raise CloudServiceError("installation_unauthorized", 401)
        installation = session.scalar(
            select(Installation).where(
                Installation.token_hash == token_hash(token, self._pepper),
                Installation.deleted_at.is_(None),
            )
        )
        if installation is None:
            raise CloudServiceError("installation_unauthorized", 401)
        installation.last_seen_at = utc_now()
        session.commit()
        return installation

    def latest_consent(self, session: Session, installation_id: str) -> ConsentRecord:
        record = session.scalar(
            select(ConsentRecord)
            .where(ConsentRecord.installation_id == installation_id)
            .order_by(ConsentRecord.id.desc())
            .limit(1)
        )
        if record is None:
            raise CloudServiceError("consent_unavailable", 409)
        return record

    def update_consent(
        self, session: Session, installation: Installation, payload: ConsentUpdate
    ) -> ConsentRecord:
        record = ConsentRecord(
            installation_id=installation.id,
            usage_metrics=payload.usage_metrics,
            improvement_data=payload.improvement_data,
            feedback_attachments=payload.feedback_attachments,
            policy_version=payload.policy_version,
        )
        session.add(record)
        session.commit()
        return record

    def quota(self, session: Session, installation: Installation) -> QuotaView:
        today = date.today()
        usage = session.scalar(
            select(DailyUsage).where(
                DailyUsage.installation_id == installation.id,
                DailyUsage.usage_date == today,
            )
        )
        return QuotaView(
            usage_date=today.isoformat(),
            requests_used=usage.request_count if usage else 0,
            requests_limit=self.settings.free_requests_per_day,
            input_chars_used=usage.input_chars if usage else 0,
            input_chars_limit=self.settings.free_input_chars_per_day,
            output_chars_used=usage.output_chars if usage else 0,
            output_chars_limit=self.settings.free_output_chars_per_day,
        )

    def reserve_quota(
        self, session: Session, installation: Installation, *, input_chars: int
    ) -> DailyUsage:
        if input_chars < 0 or input_chars > self.settings.free_input_chars_per_day:
            raise CloudServiceError("quota_input_too_large", 413)
        with self._quota_lock:
            today = date.today()
            usage = session.scalar(
                select(DailyUsage)
                .where(
                    DailyUsage.installation_id == installation.id,
                    DailyUsage.usage_date == today,
                )
                .with_for_update()
            )
            if usage is None:
                usage = DailyUsage(installation_id=installation.id, usage_date=today)
                session.add(usage)
                session.flush()
            if (
                usage.request_count >= self.settings.free_requests_per_day
                or usage.input_chars + input_chars > self.settings.free_input_chars_per_day
                or usage.output_chars >= self.settings.free_output_chars_per_day
            ):
                raise CloudServiceError("quota_exhausted", 429)
            usage.request_count += 1
            usage.input_chars += input_chars
            session.commit()
            return usage

    def reserve_ip_quota(self, session: Session, client_ip: str | None) -> None:
        if not client_ip:
            return
        window = utc_now().replace(minute=0, second=0, microsecond=0)
        ip_hash = token_hash(client_ip, self._pepper)
        with self._quota_lock:
            usage = session.scalar(
                select(HourlyIpUsage)
                .where(
                    HourlyIpUsage.ip_hash == ip_hash,
                    HourlyIpUsage.window_start == window,
                )
                .with_for_update()
            )
            if usage is None:
                usage = HourlyIpUsage(ip_hash=ip_hash, window_start=window)
                session.add(usage)
                session.flush()
            if usage.request_count >= self.settings.free_ip_requests_per_hour:
                raise CloudServiceError("ip_rate_limited", 429)
            usage.request_count += 1
            session.commit()

    def record_output_usage(
        self, session: Session, installation_id: str, *, output_chars: int
    ) -> None:
        if output_chars < 0:
            raise CloudServiceError("quota_output_invalid", 400)
        with self._quota_lock:
            usage = session.scalar(
                select(DailyUsage)
                .where(
                    DailyUsage.installation_id == installation_id,
                    DailyUsage.usage_date == date.today(),
                )
                .with_for_update()
            )
            if usage is None:
                raise CloudServiceError("quota_unavailable", 409)
            usage.output_chars += output_chars
            session.commit()

    def record_provider_usage(
        self,
        session: Session,
        *,
        input_chars: int,
        output_chars: int,
        completed: bool,
    ) -> None:
        if input_chars < 0 or output_chars < 0:
            raise CloudServiceError("usage_chars_invalid", 400)
        input_tokens = self._estimate_tokens(input_chars)
        output_tokens = self._estimate_tokens(output_chars)
        estimated_cost = self._estimate_cost(input_tokens, output_tokens)
        today = date.today()
        with self._quota_lock:
            aggregate = session.scalar(
                select(DailyCostAggregate)
                .where(
                    DailyCostAggregate.usage_date == today,
                    DailyCostAggregate.provider == "minimax",
                    DailyCostAggregate.model == self.settings.provider_model,
                    DailyCostAggregate.pricing_version
                    == self.settings.provider_pricing_version,
                )
                .with_for_update()
            )
            if aggregate is None:
                aggregate = DailyCostAggregate(
                    usage_date=today,
                    provider="minimax",
                    model=self.settings.provider_model,
                    pricing_version=self.settings.provider_pricing_version,
                )
                session.add(aggregate)
                session.flush()
            aggregate.request_count += 1
            aggregate.completed_count += int(completed)
            aggregate.input_chars += input_chars
            aggregate.output_chars += output_chars
            aggregate.estimated_input_tokens += input_tokens
            aggregate.estimated_output_tokens += output_tokens
            aggregate.estimated_cost_microusd += estimated_cost
            session.commit()

    def usage_analytics(self, session: Session, *, days: int) -> UsageAnalytics:
        today = date.today()
        start = today - timedelta(days=days - 1)
        rows = list(
            session.scalars(
                select(DailyCostAggregate)
                .where(DailyCostAggregate.usage_date >= start)
                .order_by(DailyCostAggregate.usage_date.asc())
            )
        )

        def empty() -> dict[str, int]:
            return {
                "requests": 0,
                "completed_requests": 0,
                "input_chars": 0,
                "output_chars": 0,
                "estimated_input_tokens": 0,
                "estimated_output_tokens": 0,
                "estimated_cost_microusd": 0,
            }

        total = empty()
        by_day: dict[str, dict[str, int]] = {}
        by_provider_model: dict[str, dict[str, int]] = {}
        for row in rows:
            values = {
                "requests": row.request_count,
                "completed_requests": row.completed_count,
                "input_chars": row.input_chars,
                "output_chars": row.output_chars,
                "estimated_input_tokens": row.estimated_input_tokens,
                "estimated_output_tokens": row.estimated_output_tokens,
                "estimated_cost_microusd": row.estimated_cost_microusd,
            }
            _add_usage(total, values)
            _add_usage(by_day.setdefault(row.usage_date.isoformat(), empty()), values)
            _add_usage(
                by_provider_model.setdefault(f"{row.provider}/{row.model}", empty()),
                values,
            )

        return UsageAnalytics(
            **total,
            from_date=start.isoformat(),
            to_date=today.isoformat(),
            pricing_configured=(
                self.settings.provider_pricing_version != "unconfigured"
                and self.settings.provider_input_usd_per_million_tokens > 0
                and self.settings.provider_output_usd_per_million_tokens > 0
            ),
            pricing_version=self.settings.provider_pricing_version,
            by_day={key: UsageBucket(**value) for key, value in by_day.items()},
            by_provider_model={
                key: UsageBucket(**value) for key, value in by_provider_model.items()
            },
        )

    def _estimate_tokens(self, chars: int) -> int:
        if chars <= 0:
            return 0
        return ceil(chars / float(self.settings.provider_estimated_chars_per_token))

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        total = (
            Decimal(input_tokens) * self.settings.provider_input_usd_per_million_tokens
            + Decimal(output_tokens) * self.settings.provider_output_usd_per_million_tokens
        )
        return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def store_improvement_sample(
        self,
        session: Session,
        installation_id: str,
        payload: CloudOptimizeRequest,
        *,
        output_text: str,
        scene: str,
    ) -> bool:
        consent = self.latest_consent(session, installation_id)
        if not consent.improvement_data:
            return False
        sample = ImprovementSample(
            id=str(uuid4()),
            installation_id=installation_id,
            consent_record_id=consent.id,
            request_id=payload.request_id,
            prompt_text=redact_text(payload.text),
            result_text=redact_text(output_text),
            mode=payload.mode,
            style=payload.style,
            scene=scene,
            provider="minimax",
            model=self.settings.provider_model,
            policy_version=consent.policy_version,
        )
        session.add(sample)
        session.commit()
        return True

    def submit_feedback(
        self, session: Session, installation: Installation, payload: FeedbackCreate
    ) -> FeedbackItem:
        cutoff = utc_now() - timedelta(hours=1)
        recent = session.scalar(
            select(func.count(FeedbackItem.id)).where(
                FeedbackItem.installation_id == installation.id,
                FeedbackItem.created_at >= cutoff,
            )
        )
        if int(recent or 0) >= self.settings.feedback_limit_per_hour:
            raise CloudServiceError("feedback_rate_limited", 429)

        feedback_id = str(uuid4())
        screenshot_path: str | None = None
        if payload.screenshot is not None:
            screenshot_path = self.attachments.save_screenshot(feedback_id, payload.screenshot)

        context = payload.context
        feedback = FeedbackItem(
            id=feedback_id,
            installation_id=installation.id,
            sentiment=payload.sentiment,
            category=payload.category,
            message=redact_text(payload.message.strip()),
            expected_output=redact_text(payload.expected_output.strip()),
            contact=redact_text(payload.contact.strip()),
            app_version=context.app_version,
            os_version=context.os_version,
            provider=context.provider,
            model=context.model,
            mode=context.mode,
            style=context.style,
            scene=context.scene,
            request_id=context.request_id,
            diagnostic_id=context.diagnostic_id,
            error_code=context.error_code,
            elapsed_ms=context.elapsed_ms,
            include_prompt=payload.include_prompt,
            include_result=payload.include_result,
            include_screenshot=payload.include_screenshot,
            prompt_text=redact_text(payload.prompt_text) if payload.prompt_text else None,
            result_text=redact_text(payload.result_text) if payload.result_text else None,
            screenshot_path=screenshot_path,
            screenshot_media_type=(payload.screenshot.media_type if payload.screenshot else None),
            consent_version=payload.consent_version,
        )
        try:
            session.add(feedback)
            session.commit()
        except Exception:
            session.rollback()
            self.attachments.delete(screenshot_path)
            raise
        return feedback

    def list_feedback(
        self,
        session: Session,
        *,
        status: str | None,
        category: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[FeedbackItem], int]:
        filters = []
        if status:
            filters.append(FeedbackItem.status == status)
        if category:
            filters.append(FeedbackItem.category == category)
        total = int(session.scalar(select(func.count(FeedbackItem.id)).where(*filters)) or 0)
        items = list(
            session.scalars(
                select(FeedbackItem)
                .where(*filters)
                .order_by(FeedbackItem.created_at.desc(), FeedbackItem.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return items, total

    def feedback_analytics(self, session: Session) -> FeedbackAnalytics:
        items = list(session.scalars(select(FeedbackItem)))

        def bucket(records: list[FeedbackItem]) -> QualityBucket:
            total = len(records)
            negative = sum(item.sentiment == "negative" for item in records)
            elapsed = [item.elapsed_ms for item in records if item.elapsed_ms is not None]
            return QualityBucket(
                total=total,
                negative=negative,
                negative_rate=round(negative / total, 4) if total else 0.0,
                average_elapsed_ms=(sum(elapsed) / len(elapsed)) if elapsed else None,
            )

        overall = bucket(items)
        categories: dict[str, list[FeedbackItem]] = {}
        versions: dict[str, list[FeedbackItem]] = {}
        for item in items:
            categories.setdefault(item.category, []).append(item)
            versions.setdefault(item.app_version, []).append(item)
        return FeedbackAnalytics(
            total=overall.total,
            negative=overall.negative,
            negative_rate=overall.negative_rate,
            average_elapsed_ms=overall.average_elapsed_ms,
            by_category={key: bucket(value) for key, value in sorted(categories.items())},
            by_version={key: bucket(value) for key, value in sorted(versions.items())},
        )

    def feedback_detail(self, session: Session, feedback_id: str) -> FeedbackItem:
        item = session.get(FeedbackItem, feedback_id)
        if item is None:
            raise CloudServiceError("feedback_not_found", 404)
        return item

    def update_feedback(
        self, session: Session, feedback_id: str, payload: FeedbackUpdate
    ) -> FeedbackItem:
        item = self.feedback_detail(session, feedback_id)
        item.status = payload.status
        if payload.category is not None:
            item.category = payload.category
        item.updated_at = utc_now()
        session.commit()
        return item

    def delete_installation_data(self, session: Session, installation: Installation) -> None:
        screenshot_paths = list(
            session.scalars(
                select(FeedbackItem.screenshot_path).where(
                    FeedbackItem.installation_id == installation.id,
                    FeedbackItem.screenshot_path.is_not(None),
                )
            )
        )
        session.delete(installation)
        session.commit()
        for path in screenshot_paths:
            self.attachments.delete(path)

    def purge_expired_feedback(self, session: Session) -> int:
        cutoff = utc_now() - timedelta(days=self.settings.retention_days)
        expired = list(
            session.scalars(select(FeedbackItem).where(FeedbackItem.created_at < cutoff))
        )
        for item in expired:
            self.attachments.delete(item.screenshot_path)
            session.delete(item)
        session.commit()
        return len(expired)

    def purge_expired_improvement_samples(self, session: Session) -> int:
        cutoff = utc_now() - timedelta(days=self.settings.retention_days)
        expired = list(
            session.scalars(
                select(ImprovementSample).where(ImprovementSample.created_at < cutoff)
            )
        )
        for item in expired:
            session.delete(item)
        session.commit()
        return len(expired)


def _add_usage(target: dict[str, int], values: dict[str, int]) -> None:
    for key, value in values.items():
        target[key] += value
