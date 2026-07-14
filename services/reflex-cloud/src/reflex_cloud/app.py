from __future__ import annotations

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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_schema()
        with database.sessions() as session:
            cloud_service.purge_expired_feedback(session)
            cloud_service.purge_expired_improvement_samples(session)
        yield
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
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "reflex-cloud"}

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
