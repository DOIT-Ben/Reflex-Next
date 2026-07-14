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


logger = logging.getLogger("reflex_cloud")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


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
        version="0.1.0",
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
        checks = {
            "database": "ok" if database_ready else "unavailable",
            "provider": "configured" if cloud_optimizer.configured else "unconfigured",
        }
        status_code = 200 if database_ready and cloud_optimizer.configured else 503
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
        return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code}})

    @app.exception_handler(CloudOptimizerError)
    async def optimizer_error(_: Request, error: CloudOptimizerError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"error": {"code": error.code}})

    @app.exception_handler(AttachmentError)
    async def attachment_error(_: Request, error: AttachmentError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": str(error)}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": {"code": "request_invalid"}})

    return app
