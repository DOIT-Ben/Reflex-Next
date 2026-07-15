from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from threading import Lock
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import CloudSettings
from .models import (
    BudgetReservation,
    ConsentRecord,
    DailyBudgetLedger,
    DailyCostAggregate,
    DailyUsage,
    FeedbackItem,
    HourlyIpUsage,
    ImprovementSample,
    Installation,
    QualityExposure,
    QualityRelease,
    QualityReleaseSource,
    utc_now,
)
from .schemas import (
    CloudOptimizeRequest,
    ConsentUpdate,
    FeedbackAnalytics,
    FeedbackCreate,
    FeedbackUpdate,
    QualityBucket,
    QualityReleaseCreate,
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
        self._quality_release_lock = Lock()

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
                policy_version=self.settings.privacy_policy_version,
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
        if record.policy_version != self.settings.privacy_policy_version:
            record = ConsentRecord(
                installation_id=installation_id,
                usage_metrics=False,
                improvement_data=False,
                feedback_attachments=False,
                policy_version=self.settings.privacy_policy_version,
            )
            session.add(record)
            session.commit()
        return record

    def update_consent(
        self, session: Session, installation: Installation, payload: ConsentUpdate
    ) -> ConsentRecord:
        if payload.policy_version != self.settings.privacy_policy_version:
            raise CloudServiceError("consent_outdated", 409)
        record = ConsentRecord(
            installation_id=installation.id,
            usage_metrics=payload.usage_metrics,
            improvement_data=payload.improvement_data,
            feedback_attachments=payload.feedback_attachments,
            policy_version=self.settings.privacy_policy_version,
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

    def reserve_request(
        self,
        session: Session,
        installation: Installation,
        *,
        client_ip: str | None,
        input_chars: int,
    ) -> str | None:
        """Atomically reserve all admission controls for one optimization."""
        with self._quota_lock:
            try:
                self._reserve_quota_locked(
                    session, installation, input_chars=input_chars
                )
                self._reserve_ip_quota_locked(session, client_ip)
                reservation_id = self._reserve_budget_locked(
                    session, input_chars=input_chars
                )
                session.commit()
                return reservation_id
            except Exception:
                session.rollback()
                raise

    def reserve_quota(
        self, session: Session, installation: Installation, *, input_chars: int
    ) -> DailyUsage:
        with self._quota_lock:
            try:
                usage = self._reserve_quota_locked(
                    session, installation, input_chars=input_chars
                )
                session.commit()
                return usage
            except Exception:
                session.rollback()
                raise

    def _reserve_quota_locked(
        self, session: Session, installation: Installation, *, input_chars: int
    ) -> DailyUsage:
        if input_chars < 0 or input_chars > self.settings.free_input_chars_per_day:
            raise CloudServiceError("quota_input_too_large", 413)
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
            candidate = DailyUsage(installation_id=installation.id, usage_date=today)
            try:
                with session.begin_nested():
                    session.add(candidate)
                    session.flush()
            except IntegrityError:
                usage = session.scalar(
                    select(DailyUsage)
                    .where(
                        DailyUsage.installation_id == installation.id,
                        DailyUsage.usage_date == today,
                    )
                    .with_for_update()
                )
                if usage is None:
                    raise CloudServiceError("quota_unavailable", 503) from None
            else:
                usage = candidate
        if (
            usage.request_count >= self.settings.free_requests_per_day
            or usage.input_chars + input_chars > self.settings.free_input_chars_per_day
            or usage.output_chars >= self.settings.free_output_chars_per_day
        ):
            raise CloudServiceError("quota_exhausted", 429)
        usage.request_count += 1
        usage.input_chars += input_chars
        return usage

    def reserve_ip_quota(self, session: Session, client_ip: str | None) -> None:
        with self._quota_lock:
            try:
                self._reserve_ip_quota_locked(session, client_ip)
                session.commit()
            except Exception:
                session.rollback()
                raise

    def _reserve_ip_quota_locked(
        self, session: Session, client_ip: str | None
    ) -> None:
        if not client_ip:
            return
        window = utc_now().replace(minute=0, second=0, microsecond=0)
        ip_hash = token_hash(client_ip, self._pepper)
        usage = session.scalar(
            select(HourlyIpUsage)
            .where(
                HourlyIpUsage.ip_hash == ip_hash,
                HourlyIpUsage.window_start == window,
            )
            .with_for_update()
        )
        if usage is None:
            candidate = HourlyIpUsage(ip_hash=ip_hash, window_start=window)
            try:
                with session.begin_nested():
                    session.add(candidate)
                    session.flush()
            except IntegrityError:
                usage = session.scalar(
                    select(HourlyIpUsage)
                    .where(
                        HourlyIpUsage.ip_hash == ip_hash,
                        HourlyIpUsage.window_start == window,
                    )
                    .with_for_update()
                )
                if usage is None:
                    raise CloudServiceError("ip_quota_unavailable", 503) from None
            else:
                usage = candidate
        if usage.request_count >= self.settings.free_ip_requests_per_hour:
            raise CloudServiceError("ip_rate_limited", 429)
        usage.request_count += 1

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

    def reserve_budget(self, session: Session, *, input_chars: int) -> str | None:
        with self._quota_lock:
            try:
                reservation_id = self._reserve_budget_locked(
                    session, input_chars=input_chars
                )
                session.commit()
                return reservation_id
            except Exception:
                session.rollback()
                raise

    def _reserve_budget_locked(
        self, session: Session, *, input_chars: int
    ) -> str | None:
        if not self._budget_enabled():
            return None
        if input_chars < 0:
            raise CloudServiceError("budget_input_invalid", 400)
        if self.settings.global_daily_cost_budget_microusd and not self._pricing_configured():
            raise CloudServiceError("budget_pricing_unconfigured", 503)

        now = utc_now()
        today = date.today()
        estimated_cost = self.estimate_provider_cost(
            input_chars=input_chars,
            output_chars=self.settings.budget_max_output_chars_per_request,
        )
        ledger = self._get_or_create_budget_ledger(session, today)
        self._expire_budget_reservations(session, ledger, now)

        request_limit = self.settings.global_daily_request_limit
        if request_limit and ledger.admitted_requests + 1 > request_limit:
            raise CloudServiceError("global_request_budget_exhausted", 429)

        cost_budget = self.settings.global_daily_cost_budget_microusd
        committed_cost = ledger.settled_cost_microusd + ledger.reserved_cost_microusd
        if cost_budget and committed_cost + estimated_cost > cost_budget:
            raise CloudServiceError("global_cost_budget_exhausted", 429)

        reservation_id = str(uuid4())
        ledger.admitted_requests += 1
        ledger.reserved_cost_microusd += estimated_cost
        session.add(
            BudgetReservation(
                id=reservation_id,
                usage_date=today,
                estimated_cost_microusd=estimated_cost,
                expires_at=now
                + timedelta(seconds=self.settings.budget_reservation_ttl_seconds),
            )
        )
        return reservation_id

    def release_budget(self, session: Session, reservation_id: str | None) -> bool:
        if not reservation_id:
            return False
        reservation = session.get(BudgetReservation, reservation_id)
        if reservation is None or reservation.status != "reserved":
            session.rollback()
            return False
        usage_date = reservation.usage_date
        session.rollback()
        with self._quota_lock:
            ledger = self._get_or_create_budget_ledger(session, usage_date)
            reservation = session.scalar(
                select(BudgetReservation)
                .where(BudgetReservation.id == reservation_id)
                .with_for_update()
            )
            if reservation is None or reservation.status != "reserved":
                session.rollback()
                return False
            ledger.admitted_requests = max(0, ledger.admitted_requests - 1)
            ledger.reserved_cost_microusd = max(
                0, ledger.reserved_cost_microusd - reservation.estimated_cost_microusd
            )
            reservation.status = "released"
            session.commit()
            return True

    def settle_budget(
        self,
        session: Session,
        reservation_id: str | None,
        *,
        actual_cost_microusd: int,
    ) -> bool:
        if not reservation_id:
            return False
        if actual_cost_microusd < 0:
            raise CloudServiceError("budget_cost_invalid", 400)
        reservation = session.get(BudgetReservation, reservation_id)
        if reservation is None or reservation.status != "reserved":
            session.rollback()
            return False
        usage_date = reservation.usage_date
        session.rollback()
        with self._quota_lock:
            ledger = self._get_or_create_budget_ledger(session, usage_date)
            reservation = session.scalar(
                select(BudgetReservation)
                .where(BudgetReservation.id == reservation_id)
                .with_for_update()
            )
            if reservation is None or reservation.status != "reserved":
                session.rollback()
                return False
            ledger.reserved_cost_microusd = max(
                0, ledger.reserved_cost_microusd - reservation.estimated_cost_microusd
            )
            ledger.settled_cost_microusd += actual_cost_microusd
            reservation.settled_cost_microusd = actual_cost_microusd
            reservation.status = "settled"
            session.commit()
            return True

    def estimate_provider_cost(self, *, input_chars: int, output_chars: int) -> int:
        if input_chars < 0 or output_chars < 0:
            raise CloudServiceError("usage_chars_invalid", 400)
        return self._estimate_cost(
            self._estimate_tokens(input_chars), self._estimate_tokens(output_chars)
        )

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
        estimated_cost = self.estimate_provider_cost(
            input_chars=input_chars, output_chars=output_chars
        )
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

    def _budget_enabled(self) -> bool:
        return bool(
            self.settings.global_daily_request_limit
            or self.settings.global_daily_cost_budget_microusd
        )

    def _pricing_configured(self) -> bool:
        return bool(
            self.settings.provider_pricing_version != "unconfigured"
            and self.settings.provider_input_usd_per_million_tokens > 0
            and self.settings.provider_output_usd_per_million_tokens > 0
        )

    def _get_or_create_budget_ledger(
        self, session: Session, usage_date: date
    ) -> DailyBudgetLedger:
        query = (
            select(DailyBudgetLedger)
            .where(DailyBudgetLedger.usage_date == usage_date)
            .with_for_update()
        )
        ledger = session.scalar(query)
        if ledger is not None:
            return ledger

        aggregate_values = session.execute(
            select(
                func.coalesce(func.sum(DailyCostAggregate.request_count), 0),
                func.coalesce(func.sum(DailyCostAggregate.estimated_cost_microusd), 0),
            ).where(DailyCostAggregate.usage_date == usage_date)
        ).one()
        candidate = DailyBudgetLedger(
            usage_date=usage_date,
            admitted_requests=int(aggregate_values[0] or 0),
            settled_cost_microusd=int(aggregate_values[1] or 0),
        )
        try:
            with session.begin_nested():
                session.add(candidate)
                session.flush()
        except IntegrityError:
            pass
        else:
            return candidate

        ledger = session.scalar(query)
        if ledger is None:
            raise CloudServiceError("budget_unavailable", 503)
        return ledger

    def _expire_budget_reservations(
        self, session: Session, ledger: DailyBudgetLedger, now: datetime
    ) -> int:
        expired = list(
            session.scalars(
                select(BudgetReservation)
                .where(
                    BudgetReservation.usage_date == ledger.usage_date,
                    BudgetReservation.status == "reserved",
                    BudgetReservation.expires_at <= now,
                )
                .with_for_update()
            )
        )
        for reservation in expired:
            ledger.reserved_cost_microusd = max(
                0, ledger.reserved_cost_microusd - reservation.estimated_cost_microusd
            )
            reservation.status = "expired"
        return len(expired)

    def _budget_snapshot(self, session: Session) -> dict[str, object]:
        today = date.today()
        ledger = session.get(DailyBudgetLedger, today)
        if ledger is None:
            aggregate_values = session.execute(
                select(
                    func.coalesce(func.sum(DailyCostAggregate.request_count), 0),
                    func.coalesce(func.sum(DailyCostAggregate.estimated_cost_microusd), 0),
                ).where(DailyCostAggregate.usage_date == today)
            ).one()
            requests_used = int(aggregate_values[0] or 0)
            cost_used = int(aggregate_values[1] or 0)
            cost_reserved = 0
        else:
            requests_used = ledger.admitted_requests
            cost_used = ledger.settled_cost_microusd
            cost_reserved = ledger.reserved_cost_microusd

        request_limit = self.settings.global_daily_request_limit or None
        cost_budget = self.settings.global_daily_cost_budget_microusd or None
        committed_cost = cost_used + cost_reserved
        request_remaining = (
            max(0, request_limit - requests_used) if request_limit is not None else None
        )
        cost_remaining = (
            max(0, cost_budget - committed_cost) if cost_budget is not None else None
        )
        request_ratio = (
            round(requests_used / request_limit, 4) if request_limit is not None else None
        )
        cost_ratio = (
            round(committed_cost / cost_budget, 4) if cost_budget is not None else None
        )
        exceeded = bool(
            (request_limit is not None and requests_used > request_limit)
            or (cost_budget is not None and committed_cost > cost_budget)
        )
        return {
            "daily_budget_date": today.isoformat(),
            "daily_request_limit": request_limit,
            "daily_requests_used": requests_used,
            "daily_requests_remaining": request_remaining,
            "daily_request_usage_ratio": request_ratio,
            "daily_cost_budget_microusd": cost_budget,
            "daily_cost_used_microusd": cost_used,
            "daily_cost_reserved_microusd": cost_reserved,
            "daily_cost_committed_microusd": committed_cost,
            "daily_cost_remaining_microusd": cost_remaining,
            "daily_cost_usage_ratio": cost_ratio,
            "budget_exceeded": exceeded,
        }

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
            **self._budget_snapshot(session),
            from_date=start.isoformat(),
            to_date=today.isoformat(),
            pricing_configured=self._pricing_configured(),
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

    def create_quality_release(
        self, session: Session, payload: QualityReleaseCreate
    ) -> QualityRelease:
        curated_values = (
            payload.title,
            payload.summary,
            payload.global_guidance,
            *payload.scene_guidance.values(),
        )
        if any(redact_text(value) != value for value in curated_values):
            raise CloudServiceError("quality_release_sensitive_content", 422)
        if session.scalar(
            select(QualityRelease.id).where(
                QualityRelease.release_version == payload.release_version
            )
        ):
            raise CloudServiceError("quality_release_version_conflict", 409)

        source_ids = list(payload.source_feedback_ids)
        sources = list(
            session.scalars(select(FeedbackItem).where(FeedbackItem.id.in_(source_ids)))
        )
        if {item.id for item in sources} != set(source_ids):
            raise CloudServiceError("quality_release_source_not_found", 404)

        release = QualityRelease(
            id=str(uuid4()),
            release_version=payload.release_version,
            template_pack_version=payload.template_pack_version,
            title=payload.title,
            summary=payload.summary,
            global_guidance=payload.global_guidance,
            scene_guidance_json=json.dumps(
                payload.scene_guidance,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            status="draft",
        )
        try:
            session.add(release)
            session.flush()
            session.add_all(
                QualityReleaseSource(release_id=release.id, feedback_id=feedback_id)
                for feedback_id in source_ids
            )
            session.commit()
        except IntegrityError:
            session.rollback()
            raise CloudServiceError("quality_release_version_conflict", 409) from None
        return release

    def quality_release_detail(
        self, session: Session, release_id: str
    ) -> QualityRelease:
        release = session.get(QualityRelease, release_id)
        if release is None:
            raise CloudServiceError("quality_release_not_found", 404)
        return release

    def _quality_release_for_update(
        self, session: Session, release_id: str
    ) -> QualityRelease:
        release = session.scalar(
            select(QualityRelease)
            .where(QualityRelease.id == release_id)
            .with_for_update()
        )
        if release is None:
            raise CloudServiceError("quality_release_not_found", 404)
        return release

    def list_quality_releases(
        self, session: Session, *, limit: int, offset: int
    ) -> tuple[list[QualityRelease], int]:
        total = int(session.scalar(select(func.count(QualityRelease.id))) or 0)
        releases = list(
            session.scalars(
                select(QualityRelease)
                .order_by(QualityRelease.created_at.desc(), QualityRelease.id.desc())
                .offset(offset)
                .limit(limit)
            )
        )
        return releases, total

    def active_quality_release(self, session: Session) -> QualityRelease | None:
        return session.scalar(
            select(QualityRelease)
            .where(QualityRelease.status == "published")
            .order_by(QualityRelease.published_at.desc(), QualityRelease.id.desc())
            .limit(1)
        )

    def quality_release_source_ids(
        self, session: Session, release_id: str
    ) -> list[str]:
        return list(
            session.scalars(
                select(QualityReleaseSource.feedback_id)
                .where(QualityReleaseSource.release_id == release_id)
                .order_by(QualityReleaseSource.feedback_id.asc())
            )
        )

    def quality_release_source_count(self, session: Session, release_id: str) -> int:
        return int(
            session.scalar(
                select(func.count(QualityReleaseSource.feedback_id)).where(
                    QualityReleaseSource.release_id == release_id
                )
            )
            or 0
        )

    @staticmethod
    def quality_release_scene_guidance(release: QualityRelease) -> dict[str, str]:
        try:
            value = json.loads(release.scene_guidance_json)
        except (TypeError, ValueError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {
            key: guidance
            for key, guidance in value.items()
            if isinstance(key, str) and isinstance(guidance, str)
        }

    def publish_quality_release(
        self, session: Session, release_id: str
    ) -> QualityRelease:
        try:
            with self._quality_release_lock:
                release = self._quality_release_for_update(session, release_id)
                if release.status != "draft":
                    raise CloudServiceError("quality_release_state_invalid", 409)
                source_ids = self.quality_release_source_ids(session, release.id)
                if not source_ids:
                    raise CloudServiceError("quality_release_sources_not_ready", 409)
                sources = list(
                    session.scalars(
                        select(FeedbackItem).where(FeedbackItem.id.in_(source_ids))
                    )
                )
                if len(sources) != len(source_ids) or any(
                    source.status not in {"fixed", "released"} for source in sources
                ):
                    raise CloudServiceError("quality_release_sources_not_ready", 409)

                now = utc_now()
                current = session.scalar(
                    select(QualityRelease)
                    .where(QualityRelease.status == "published")
                    .order_by(
                        QualityRelease.published_at.desc(), QualityRelease.id.desc()
                    )
                    .with_for_update()
                    .limit(1)
                )
                if current is not None:
                    current.status = "superseded"
                    current.updated_at = now
                    session.flush()
                release.status = "published"
                release.published_at = now
                release.rolled_back_at = None
                release.updated_at = now
                for source in sources:
                    source.status = "released"
                    source.updated_at = now
                session.commit()
        except IntegrityError:
            session.rollback()
            raise CloudServiceError("quality_release_publish_conflict", 409) from None
        except Exception:
            session.rollback()
            raise
        return release

    def rollback_quality_release(
        self, session: Session, release_id: str
    ) -> QualityRelease | None:
        try:
            with self._quality_release_lock:
                release = self._quality_release_for_update(session, release_id)
                if release.status != "published":
                    raise CloudServiceError("quality_release_state_invalid", 409)
                now = utc_now()
                release.status = "rolled_back"
                release.rolled_back_at = now
                release.updated_at = now
                session.flush()

                previous = session.scalar(
                    select(QualityRelease)
                    .where(QualityRelease.status == "superseded")
                    .order_by(
                        QualityRelease.published_at.desc(), QualityRelease.id.desc()
                    )
                    .with_for_update()
                    .limit(1)
                )
                if previous is not None:
                    previous.status = "published"
                    previous.updated_at = now
                session.commit()
        except IntegrityError:
            session.rollback()
            raise CloudServiceError("quality_release_publish_conflict", 409) from None
        except Exception:
            session.rollback()
            raise
        return previous

    def record_quality_exposure(
        self,
        session: Session,
        installation_id: str,
        request_id: str,
        release: QualityRelease | None,
    ) -> bool:
        try:
            consent = self.latest_consent(session, installation_id)
            if not consent.usage_metrics:
                return False
            release_version = release.release_version if release else "baseline"
            existing = session.scalar(
                select(QualityExposure).where(
                    QualityExposure.installation_id == installation_id,
                    QualityExposure.request_id == request_id,
                )
            )
            if existing is not None:
                return existing.release_version == release_version
            exposure = QualityExposure(
                id=str(uuid4()),
                installation_id=installation_id,
                quality_release_id=release.id if release else None,
                request_id=request_id,
                release_version=release_version,
            )
            session.add(exposure)
            session.commit()
        except Exception:
            session.rollback()
            return False
        return True

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
        consent = self.latest_consent(session, installation.id)
        if payload.consent_version != consent.policy_version:
            raise CloudServiceError("consent_outdated", 409)
        if (
            (payload.include_prompt or payload.include_result)
            and not consent.improvement_data
        ):
            raise CloudServiceError("consent_required", 403)

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
        exposure_versions = {
            (installation_id, request_id): release_version
            for installation_id, request_id, release_version in session.execute(
                select(
                    QualityExposure.installation_id,
                    QualityExposure.request_id,
                    QualityExposure.release_version,
                )
            )
        }

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
        quality_releases: dict[str, list[FeedbackItem]] = {}
        for item in items:
            categories.setdefault(item.category, []).append(item)
            versions.setdefault(item.app_version, []).append(item)
            quality_release = exposure_versions.get(
                (item.installation_id, item.request_id)
            )
            if quality_release:
                quality_releases.setdefault(quality_release, []).append(item)
        return FeedbackAnalytics(
            total=overall.total,
            negative=overall.negative,
            negative_rate=overall.negative_rate,
            average_elapsed_ms=overall.average_elapsed_ms,
            by_category={key: bucket(value) for key, value in sorted(categories.items())},
            by_version={key: bucket(value) for key, value in sorted(versions.items())},
            by_quality_release={
                key: bucket(value) for key, value in sorted(quality_releases.items())
            },
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

    def purge_expired_budget_reservations(self, session: Session) -> int:
        now = utc_now()
        with self._quota_lock:
            usage_dates = list(
                session.scalars(
                    select(BudgetReservation.usage_date)
                    .where(
                        BudgetReservation.status == "reserved",
                        BudgetReservation.expires_at <= now,
                    )
                    .distinct()
                )
            )
            expired_count = 0
            for usage_date in sorted(usage_dates):
                ledger = session.scalar(
                    select(DailyBudgetLedger)
                    .where(DailyBudgetLedger.usage_date == usage_date)
                    .with_for_update()
                )
                rows = list(
                    session.scalars(
                        select(BudgetReservation)
                        .where(
                            BudgetReservation.usage_date == usage_date,
                            BudgetReservation.status == "reserved",
                            BudgetReservation.expires_at <= now,
                        )
                        .with_for_update()
                    )
                )
                for reservation in rows:
                    if ledger is not None:
                        ledger.reserved_cost_microusd = max(
                            0,
                            ledger.reserved_cost_microusd
                            - reservation.estimated_cost_microusd,
                        )
                    reservation.status = "expired"
                expired_count += len(rows)
            terminal_cutoff = now - timedelta(days=2)
            terminal_rows = list(
                session.scalars(
                    select(BudgetReservation).where(
                        BudgetReservation.status != "reserved",
                        BudgetReservation.created_at <= terminal_cutoff,
                    )
                )
            )
            for reservation in terminal_rows:
                session.delete(reservation)
            session.commit()
            return expired_count + len(terminal_rows)

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
