"""FastAPI application exposing the runtime sidecar as an SSE service."""

from __future__ import annotations

import json
import os
import queue
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from reflex_core.template import FileTemplatePack

from .gateway import GatewayError, SidecarGateway, is_terminal_event

REQUEST_TIMEOUT_SECONDS = float(
    os.environ.get("REFLEX_HTTP_REQUEST_TIMEOUT", "120")
)
MAX_OPTIMIZE_TEXT = 1_000_000

_TEMPLATE_PACK_ROOT = Path(
    os.environ.get(
        "REFLEX_TEMPLATE_PACK_ROOT",
        str(Path(__file__).resolve().parents[4] / "template-packs" / "builtin"),
    )
)


def _load_template_pack() -> FileTemplatePack | None:
    try:
        return FileTemplatePack.load(_TEMPLATE_PACK_ROOT)
    except Exception:
        return None

_ALLOWED_MODES = frozenset({"content", "prompt"})
_SSE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}


class OptimizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_OPTIMIZE_TEXT)
    style: str | None = None
    mode: str | None = None
    scene: str | None = None
    scene_policy: str | None = None
    stream: bool | None = None
    provider: str | None = None
    model: str | None = None
    metadata: dict[str, object] | None = None
    request_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Optional client-chosen request id (ASCII alnum, -_.:).",
    )


def _safe_request_id(value: str) -> bool:
    return all(
        character.isascii() and (character.isalnum() or character in "-_.:")
        for character in value
    )


def _authorize(request: Request) -> None:
    token = os.environ.get("REFLEX_HTTP_TOKEN")
    if not token:
        return
    header = request.headers.get("Authorization", "")
    if header != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="unauthorized")


def _stream_events(gateway: SidecarGateway, request_id: str):
    subscription = gateway.subscribe(request_id)
    deadline = time.monotonic() + gateway.request_timeout_seconds
    terminal = False
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    gateway.cancel(request_id)
                except GatewayError:
                    pass
                error = {
                    "version": 1,
                    "request_id": request_id,
                    "event": {
                        "type": "error",
                        "data": {"code": "request_timeout", "message": "Request timed out."},
                    },
                }
                yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
                return
            try:
                envelope = subscription.queue.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            yield f"data: {json.dumps(envelope, ensure_ascii=False)}\n\n"
            if is_terminal_event(envelope):
                terminal = True
                return
    finally:
        if not terminal:
            try:
                gateway.cancel(request_id)
            except GatewayError:
                pass
        gateway.unsubscribe(request_id)


def create_app(gateway: SidecarGateway | None = None) -> FastAPI:
    owned_gateway = gateway is None
    gateway = gateway or SidecarGateway()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        gateway.start()
        _app.state.template_pack = _load_template_pack()
        yield
        gateway.close()

    app = FastAPI(title="Reflex Next HTTP Host", version="0.7.0-alpha.8", lifespan=lifespan)

    @app.get("/v1/health")
    def health(_: Request = Depends(_authorize)) -> dict[str, object]:
        return {"ok": gateway.is_alive()}

    @app.get("/v1/scenes")
    def scene_catalog(_: Request = Depends(_authorize)) -> dict[str, object]:
        """Scene library catalog grouped by first-level category."""
        pack = getattr(app.state, "template_pack", None)
        if pack is None:
            raise HTTPException(status_code=503, detail="template pack unavailable")
        categories = []
        for category_id in pack.category_ids:
            scenes = sorted(
                scene_id
                for scene_id, category in pack.scene_categories.items()
                if category == category_id
            )
            categories.append({"id": category_id, "scenes": scenes})
        unclassified = sorted(
            scene_id
            for scene_id in pack.scene_ids
            if scene_id not in pack.scene_categories
        )
        return {
            "categories": categories,
            "scenes": [
                {"id": scene_id, "category": pack.scene_categories.get(scene_id)}
                for scene_id in pack.scene_ids
            ],
            "unclassified": unclassified,
        }

    @app.post("/v1/ping")
    def ping(_: Request = Depends(_authorize)) -> dict[str, object]:
        request_id = gateway.send_command("ping")
        subscription = gateway.subscribe(request_id)
        deadline = time.monotonic() + 5.0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HTTPException(status_code=504, detail="ping timeout")
                try:
                    envelope = subscription.queue.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if envelope.get("request_id") != request_id:
                    continue
                event = envelope.get("event")
                if isinstance(event, dict) and event.get("type") == "status":
                    if event.get("data", {}).get("phase") == "completed":
                        return {"pong": True, "request_id": request_id}
                    if event.get("data", {}).get("phase") == "error":
                        raise HTTPException(status_code=503, detail="runtime error")
        finally:
            gateway.unsubscribe(request_id)

    @app.get("/v1/providers")
    def list_providers(_: Request = Depends(_authorize)) -> dict[str, object]:
        request_id = gateway.send_command("list_providers")
        subscription = gateway.subscribe(request_id)
        deadline = time.monotonic() + 5.0
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HTTPException(status_code=504, detail="provider list timeout")
                try:
                    envelope = subscription.queue.get(timeout=min(0.2, remaining))
                except queue.Empty:
                    continue
                if envelope.get("request_id") != request_id:
                    continue
                if envelope.get("type") == "provider_catalog":
                    return {"providers": envelope.get("providers", [])}
                event = envelope.get("event")
                if isinstance(event, dict) and event.get("type") == "error":
                    raise HTTPException(status_code=503, detail="runtime error")
        finally:
            gateway.unsubscribe(request_id)

    @app.post("/v1/optimize")
    def optimize(
        payload: OptimizeRequest,
        _: Request = Depends(_authorize),
    ) -> StreamingResponse:
        command_payload: dict[str, object] = {"text": payload.text}
        if payload.style is not None:
            command_payload["style"] = payload.style
        if payload.mode is not None:
            command_payload["mode"] = payload.mode
        if payload.scene is not None:
            command_payload["scene"] = payload.scene
        if payload.scene_policy is not None:
            command_payload["scene_policy"] = payload.scene_policy
        if payload.stream is not None:
            command_payload["stream"] = payload.stream
        if payload.provider is not None:
            command_payload["provider"] = payload.provider
        if payload.model is not None:
            command_payload["model"] = payload.model
        if payload.metadata is not None:
            command_payload["metadata"] = payload.metadata
        if payload.request_id is not None and not _safe_request_id(payload.request_id):
            raise HTTPException(status_code=422, detail="invalid request_id")
        try:
            request_id = gateway.send_command(
                "optimize",
                command_payload,
                request_id=payload.request_id,
            )
        except GatewayError as error:
            raise HTTPException(status_code=503, detail=error.safe_message) from error
        return StreamingResponse(
            _stream_events(gateway, request_id),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    @app.post("/v1/requests/{request_id}/cancel")
    def cancel_request(
        request_id: str,
        _: Request = Depends(_authorize),
    ) -> dict[str, object]:
        try:
            gateway.cancel(request_id)
        except GatewayError as error:
            raise HTTPException(status_code=503, detail=error.safe_message) from error
        return {"cancelled": True, "request_id": request_id}

    app.state.gateway = gateway
    return app
