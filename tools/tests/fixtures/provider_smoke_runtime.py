"""Deterministic NDJSON fixture for the provider smoke tool contract tests."""

from __future__ import annotations

import json
import sys
import time


PROVIDERS = [
    {
        "id": "failure",
        "name": "Failure Fixture",
        "models": ["fixture-model"],
        "default_model": "fixture-model",
        "release_status": "experimental",
        "session_configured": False,
    },
    {
        "id": "late-chunk",
        "name": "Late Chunk Fixture",
        "models": ["fixture-model"],
        "default_model": "fixture-model",
        "release_status": "experimental",
        "session_configured": False,
    },
    {
        "id": "late-done",
        "name": "Late Done Fixture",
        "models": ["fixture-model"],
        "default_model": "fixture-model",
        "release_status": "experimental",
        "session_configured": False,
    },
    {
        "id": "minimax",
        "name": "MiniMax Fixture",
        "models": ["fixture-model"],
        "default_model": "fixture-model",
        "release_status": "supported",
        "session_configured": False,
    },
]


def emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def event(request_id: str, event_type: str, data: dict) -> None:
    emit(
        {
            "version": 1,
            "request_id": request_id,
            "event": {"type": event_type, "data": data},
        }
    )


def main() -> int:
    configured = False
    active_provider = None
    for line in sys.stdin:
        command = json.loads(line)
        request_id = command["request_id"]
        command_type = command["type"]
        if command_type == "list_providers":
            providers = [dict(provider) for provider in PROVIDERS]
            for provider in providers:
                provider["session_configured"] = configured
            emit(
                {
                    "version": 1,
                    "request_id": request_id,
                    "type": "provider_catalog",
                    "providers": providers,
                }
            )
        elif command_type == "configure_provider":
            configured = True
            event(request_id, "status", {"phase": "completed", "message": "configured"})
        elif command_type == "optimize":
            active_provider = command["payload"].get("provider")
            event(request_id, "status", {"phase": "connecting_provider", "message": "connecting"})
            if command["payload"].get("provider") == "failure":
                event(
                    request_id,
                    "error",
                    {
                        "code": "auth_error",
                        "message": "fixture-smoke-private-credential https://fixture.invalid/v1/chat/completions fixture-private-response-body",
                        "recoverable": True,
                        "action": "open_settings",
                    },
                )
                continue
            event(request_id, "request", {"provider": "minimax", "model": "fixture-model"})
            event(request_id, "chunk", {"text": "fixture-private-response-body"})
            if command["payload"].get("metadata", {}).get("smoke_operation") == "cancel":
                time.sleep(0.08)
                event(request_id, "chunk", {"text": "fixture-private-late-body"})
            else:
                event(
                    request_id,
                    "done",
                    {
                        "text": "fixture-private-response-body",
                        "scene": "general",
                        "style": "balanced",
                        "mode": "content",
                        "provider": "minimax",
                        "model": "fixture-model",
                    },
                )
        elif command_type == "cancel":
            event(request_id, "status", {"phase": "cancelled", "message": "cancelled"})
            if active_provider == "late-chunk":
                event(request_id, "chunk", {"text": "fixture-private-late-body"})
            elif active_provider == "late-done":
                event(
                    request_id,
                    "done",
                    {
                        "text": "fixture-private-late-body",
                        "scene": "general",
                        "style": "balanced",
                        "mode": "content",
                        "provider": "late-done",
                        "model": "fixture-model",
                    },
                )
        elif command_type == "shutdown":
            event(request_id, "status", {"phase": "completed", "message": "shutdown"})
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
