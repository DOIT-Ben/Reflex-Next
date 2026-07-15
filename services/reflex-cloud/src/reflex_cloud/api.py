from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from .models import ConsentRecord, FeedbackItem, Installation
from .optimizer import CloudOptimizer, CloudOptimizerError
from .schemas import (
    ConsentUpdate,
    ConsentView,
    CloudOptimizeRequest,
    DeleteResult,
    FeedbackCreate,
    FeedbackCreated,
    FeedbackDetail,
    FeedbackAnalytics,
    FeedbackPage,
    FeedbackSummary,
    FeedbackUpdate,
    InstallationCreated,
    OptimizeCancelRequest,
    OptimizeCancelResult,
    QuotaView,
    UsageAnalytics,
)
from .security import secure_equals
from .service import CloudService, CloudServiceError


public_router = APIRouter(prefix="/v1")
admin_router = APIRouter(prefix="/v1/admin")


def get_session(request: Request):
    yield from request.app.state.database.session()


def get_service(request: Request) -> CloudService:
    return request.app.state.cloud_service


def get_optimizer(request: Request) -> CloudOptimizer:
    return request.app.state.optimizer


SessionDependency = Annotated[Session, Depends(get_session)]
ServiceDependency = Annotated[CloudService, Depends(get_service)]
OptimizerDependency = Annotated[CloudOptimizer, Depends(get_optimizer)]


def current_installation(
    session: SessionDependency,
    service: ServiceDependency,
    installation_token: Annotated[str, Header(alias="X-Reflex-Installation-Token")],
) -> Installation:
    return service.authenticate_installation(session, installation_token)


InstallationDependency = Annotated[Installation, Depends(current_installation)]


def require_admin(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.admin_token.get_secret_value()
    prefix = "Bearer "
    provided = authorization[len(prefix) :] if authorization and authorization.startswith(prefix) else ""
    if not provided or not secure_equals(provided, expected):
        raise CloudServiceError("admin_unauthorized", 401)


AdminDependency = Annotated[None, Depends(require_admin)]


@public_router.post("/installations", response_model=InstallationCreated, status_code=201)
def create_installation(session: SessionDependency, service: ServiceDependency) -> InstallationCreated:
    installation, token = service.create_installation(session)
    return InstallationCreated(installation_id=installation.id, token=token)


@public_router.get("/privacy/consent", response_model=ConsentView)
def get_consent(
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConsentView:
    return _consent_view(service.latest_consent(session, installation.id))


@public_router.put("/privacy/consent", response_model=ConsentView)
def update_consent(
    payload: ConsentUpdate,
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> ConsentView:
    return _consent_view(service.update_consent(session, installation, payload))


@public_router.get("/quota", response_model=QuotaView)
def get_quota(
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> QuotaView:
    return service.quota(session, installation)


@public_router.post("/optimize")
def optimize(
    payload: CloudOptimizeRequest,
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
    optimizer: OptimizerDependency,
    request: Request,
) -> StreamingResponse:
    optimizer.claim(payload.request_id, installation.id)
    budget_reservation_id: str | None = None
    try:
        budget_reservation_id = service.reserve_request(
            session,
            installation,
            client_ip=request.client.host if request.client else None,
            input_chars=len(payload.text),
        )
    except Exception:
        optimizer.release(payload.request_id)
        raise

    def event_stream() -> Iterator[str]:
        output_chars = 0
        output_chunks: list[str] = []
        completed = False
        final_scene = payload.scene or "general"
        try:
            for envelope in optimizer.stream(payload):
                event = envelope.get("event")
                if isinstance(event, dict) and event.get("type") == "chunk":
                    data = event.get("data")
                    if isinstance(data, dict) and isinstance(data.get("text"), str):
                        output_chars += len(data["text"])
                        output_chunks.append(data["text"])
                if isinstance(event, dict) and event.get("type") == "done":
                    data = event.get("data")
                    if isinstance(data, dict):
                        completed = True
                        if isinstance(data.get("scene"), str):
                            final_scene = data["scene"]
                yield f"data: {json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))}\n\n"
        finally:
            optimizer.release(payload.request_id)
            actual_cost = service.estimate_provider_cost(
                input_chars=len(payload.text), output_chars=output_chars
            )
            try:
                with request.app.state.database.sessions() as usage_session:
                    if output_chars:
                        service.record_output_usage(
                            usage_session, installation.id, output_chars=output_chars
                        )
                    service.record_provider_usage(
                        usage_session,
                        input_chars=len(payload.text),
                        output_chars=output_chars,
                        completed=completed,
                    )
                    if output_chars and completed:
                        service.store_improvement_sample(
                            usage_session,
                            installation.id,
                            payload,
                            output_text="".join(output_chunks),
                            scene=final_scene,
                        )
            finally:
                if budget_reservation_id is not None:
                    with request.app.state.database.sessions() as budget_session:
                        service.settle_budget(
                            budget_session,
                            budget_reservation_id,
                            actual_cost_microusd=actual_cost,
                        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@public_router.post("/optimize/cancel", response_model=OptimizeCancelResult)
def cancel_optimize(
    payload: OptimizeCancelRequest,
    installation: InstallationDependency,
    optimizer: OptimizerDependency,
) -> OptimizeCancelResult:
    return OptimizeCancelResult(
        cancelled=optimizer.cancel(payload.request_id, installation.id)
    )


@public_router.delete("/privacy/data", response_model=DeleteResult)
def delete_data(
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> DeleteResult:
    service.delete_installation_data(session, installation)
    return DeleteResult(deleted=True)


@public_router.post("/feedback", response_model=FeedbackCreated, status_code=201)
def create_feedback(
    payload: FeedbackCreate,
    installation: InstallationDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> FeedbackCreated:
    item = service.submit_feedback(session, installation, payload)
    return FeedbackCreated(id=item.id, status=item.status, created_at=item.created_at)


@admin_router.get("/feedback", response_model=FeedbackPage)
def list_feedback(
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
    status: str | None = Query(default=None, max_length=32),
    category: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FeedbackPage:
    items, total = service.list_feedback(
        session, status=status, category=category, limit=limit, offset=offset
    )
    return FeedbackPage(items=[_feedback_summary(item) for item in items], total=total)


@admin_router.get("/analytics/feedback", response_model=FeedbackAnalytics)
def get_feedback_analytics(
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> FeedbackAnalytics:
    return service.feedback_analytics(session)


@admin_router.get("/analytics/usage", response_model=UsageAnalytics)
def get_usage_analytics(
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
    days: int = Query(default=7, ge=1, le=90),
) -> UsageAnalytics:
    return service.usage_analytics(session, days=days)


@admin_router.get("/feedback/{feedback_id}", response_model=FeedbackDetail)
def get_feedback(
    feedback_id: str,
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> FeedbackDetail:
    return _feedback_detail(service.feedback_detail(session, feedback_id))


@admin_router.patch("/feedback/{feedback_id}", response_model=FeedbackDetail)
def patch_feedback(
    feedback_id: str,
    payload: FeedbackUpdate,
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> FeedbackDetail:
    return _feedback_detail(service.update_feedback(session, feedback_id, payload))


@admin_router.get("/feedback/{feedback_id}/screenshot")
def get_feedback_screenshot(
    feedback_id: str,
    _: AdminDependency,
    session: SessionDependency,
    service: ServiceDependency,
) -> FileResponse:
    item = service.feedback_detail(session, feedback_id)
    path = service.attachments.path_for(item.screenshot_path or "")
    if path is None or item.screenshot_media_type is None:
        raise CloudServiceError("feedback_screenshot_not_found", 404)
    return FileResponse(path, media_type=item.screenshot_media_type)


def _consent_view(record: ConsentRecord) -> ConsentView:
    return ConsentView(
        usage_metrics=record.usage_metrics,
        improvement_data=record.improvement_data,
        feedback_attachments=record.feedback_attachments,
        policy_version=record.policy_version,
        updated_at=record.created_at,
    )


def _feedback_summary(item: FeedbackItem) -> FeedbackSummary:
    return FeedbackSummary(
        id=item.id,
        sentiment=item.sentiment,
        category=item.category,
        status=item.status,
        app_version=item.app_version,
        provider=item.provider,
        model=item.model,
        error_code=item.error_code,
        has_prompt=item.prompt_text is not None,
        has_result=item.result_text is not None,
        has_screenshot=item.screenshot_path is not None,
        created_at=item.created_at,
    )


def _feedback_detail(item: FeedbackItem) -> FeedbackDetail:
    summary = _feedback_summary(item)
    return FeedbackDetail(
        **summary.model_dump(),
        message=item.message,
        expected_output=item.expected_output,
        contact=item.contact,
        context={
            "app_version": item.app_version,
            "os_version": item.os_version,
            "provider": item.provider,
            "model": item.model,
            "mode": item.mode,
            "style": item.style,
            "scene": item.scene,
            "request_id": item.request_id,
            "diagnostic_id": item.diagnostic_id,
            "error_code": item.error_code,
            "elapsed_ms": item.elapsed_ms,
        },
        prompt_text=item.prompt_text,
        result_text=item.result_text,
        screenshot_url=(f"/v1/admin/feedback/{item.id}/screenshot" if item.screenshot_path else None),
        consent_version=item.consent_version,
    )
