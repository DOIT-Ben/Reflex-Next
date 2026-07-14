from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .models import ConsentRecord, FeedbackItem, Installation
from .schemas import (
    ConsentUpdate,
    ConsentView,
    DeleteResult,
    FeedbackCreate,
    FeedbackCreated,
    FeedbackDetail,
    FeedbackPage,
    FeedbackSummary,
    FeedbackUpdate,
    InstallationCreated,
)
from .security import secure_equals
from .service import CloudService, CloudServiceError


public_router = APIRouter(prefix="/v1")
admin_router = APIRouter(prefix="/v1/admin")


def get_session(request: Request):
    yield from request.app.state.database.session()


def get_service(request: Request) -> CloudService:
    return request.app.state.cloud_service


SessionDependency = Annotated[Session, Depends(get_session)]
ServiceDependency = Annotated[CloudService, Depends(get_service)]


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
