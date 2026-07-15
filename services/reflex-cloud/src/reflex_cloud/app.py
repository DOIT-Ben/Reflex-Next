from __future__ import annotations

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import admin_router, public_router
from .config import CloudSettings
from .database import Database
from .optimizer import CloudOptimizer, CloudOptimizerError
from .service import CloudService, CloudServiceError
from .storage import AttachmentError, AttachmentStore
from .version import __version__


logger = logging.getLogger("reflex_cloud")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


_ERROR_MESSAGES = {
    "request_invalid": "请求内容无效，请检查后重试。",
    "installation_unauthorized": "安装身份已失效，请重新打开应用。",
    "quota_exhausted": "今日免费额度已用完，可明天再试或使用自备 Provider。",
    "quota_input_too_large": "输入内容过长，请缩短后重试。",
    "quota_unavailable": "免费额度服务暂时不可用，请稍后再试。",
    "ip_rate_limited": "当前网络请求过于频繁，请稍后再试。",
    "ip_quota_unavailable": "网络限流服务暂时不可用，请稍后再试。",
    "global_request_budget_exhausted": "今日云端请求额度已用完，请明天再试或切换到自备 Provider。",
    "global_cost_budget_exhausted": "今日云端服务预算已用完，请稍后再试或切换到自备 Provider。",
    "budget_pricing_unconfigured": "云端计费配置暂不可用，请稍后再试。",
    "budget_unavailable": "云端预算服务暂时不可用，请稍后再试。",
    "cloud_provider_unconfigured": "云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。",
    "cloud_capacity_reached": "云端当前繁忙，请稍后重试。",
    "installation_concurrency_reached": "当前安装已有请求处理中，请等待完成。",
    "optimize_request_conflict": "该请求正在处理中，请勿重复提交。",
    "feedback_rate_limited": "反馈提交过于频繁，请稍后再试。",
    "consent_required": "请先在隐私设置中开启对应的数据改进授权。",
    "consent_outdated": "隐私授权版本已更新，请刷新授权设置后再提交。",
    "quality_release_sensitive_content": "质量发布内容包含敏感信息，请清理后重试。",
    "quality_release_version_conflict": "该质量发布版本已存在，请使用新版本号。",
    "quality_release_source_not_found": "部分来源反馈不存在或已删除。",
    "quality_release_not_found": "质量发布不存在。",
    "quality_release_sources_not_ready": "来源反馈尚未全部完成修复，暂不能发布。",
    "quality_release_state_invalid": "当前质量发布状态不允许执行此操作。",
    "quality_release_publish_conflict": "质量发布发生并发冲突，请刷新后重试。",
    "admin_unauthorized": "管理身份验证失败。",
}


def _error_response(code: str, status_code: int) -> JSONResponse:
    error = {
        "code": code,
        "message": _ERROR_MESSAGES.get(code, "请求未能处理，请稍后重试。"),
    }
    return JSONResponse(status_code=status_code, content={"error": error})


def create_app(
    settings: CloudSettings | None = None, optimizer: CloudOptimizer | None = None
) -> FastAPI:
    current_settings = settings or CloudSettings()
    database = Database(current_settings.database_url)
    attachments = AttachmentStore(
        current_settings.upload_directory, current_settings.max_screenshot_bytes
    )
    cloud_service = CloudService(current_settings, attachments)
    cloud_optimizer = optimizer or CloudOptimizer(current_settings)

    def purge_expired_data() -> None:
        with database.sessions() as session:
            cloud_service.purge_expired_budget_reservations(session)
            cloud_service.purge_expired_feedback(session)
            cloud_service.purge_expired_improvement_samples(session)

    async def retention_loop(stop: asyncio.Event) -> None:
        while True:
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=current_settings.retention_cleanup_interval_seconds,
                )
                return
            except TimeoutError:
                try:
                    purge_expired_data()
                except Exception:
                    logger.exception("retention_cleanup_failed")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_schema()
        purge_expired_data()
        retention_stop = asyncio.Event()
        retention_task = asyncio.create_task(retention_loop(retention_stop))
        try:
            yield
        finally:
            retention_stop.set()
            await retention_task
            database.close()

    app = FastAPI(
        title="Reflex Cloud",
        version=__version__,
        docs_url=None if current_settings.environment == "production" else "/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = current_settings
    app.state.database = database
    app.state.cloud_service = cloud_service
    app.state.optimizer = cloud_optimizer

    app.include_router(public_router)
    app.include_router(admin_router)
    static_directory = Path(__file__).with_name("static")
    app.mount("/admin-static", StaticFiles(directory=static_directory), name="admin-static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/v1/admin"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    @app.get("/health/live")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "reflex-cloud"}

    @app.get("/health/ready", response_model=None)
    def ready() -> JSONResponse:
        try:
            database_ready = database.ping()
        except Exception:
            database_ready = False
        budget_configured = bool(
            current_settings.global_daily_request_limit
            and current_settings.global_daily_cost_budget_microusd
        )
        checks = {
            "database": "ok" if database_ready else "unavailable",
            "provider": "configured" if cloud_optimizer.configured else "unconfigured",
            "budget": "configured" if budget_configured else "disabled",
        }
        production_budget_ready = (
            current_settings.environment != "production" or budget_configured
        )
        status_code = (
            200
            if database_ready and cloud_optimizer.configured and production_budget_ready
            else 503
        )
        status = "ready" if status_code == 200 else "not_ready"
        return JSONResponse(
            status_code=status_code,
            content={"status": status, "checks": checks},
        )

    @app.get("/admin", include_in_schema=False)
    def admin_page() -> FileResponse:
        return FileResponse(static_directory / "admin.html", media_type="text/html")

    @app.exception_handler(CloudServiceError)
    async def cloud_service_error(_: Request, error: CloudServiceError) -> JSONResponse:
        return _error_response(error.code, error.status_code)

    @app.exception_handler(CloudOptimizerError)
    async def optimizer_error(_: Request, error: CloudOptimizerError) -> JSONResponse:
        return _error_response(error.code, error.status_code)

    @app.exception_handler(AttachmentError)
    async def attachment_error(_: Request, error: AttachmentError) -> JSONResponse:
        return _error_response(str(error), 422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response("request_invalid", 422)

    return app
