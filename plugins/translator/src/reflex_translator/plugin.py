"""Provider-backed streaming translator implementation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from reflex_core.safety import sanitize_text

from .contract import TranslationRequest, TranslatorPluginError

_TARGET_NAMES = {"zh": "Chinese", "en": "English"}


@dataclass(frozen=True)
class TranslatorDescriptor:
    plugin_id: str = "translator"
    display_name: str = "Translator"
    version: str = "1"
    kind: str = "transformer"
    permissions: tuple[str, ...] = ("network-via-provider",)
    operations: tuple[str, ...] = ("translate",)
    public_operations: tuple[str, ...] = ("translate",)


class TranslatorPlugin:
    descriptor = TranslatorDescriptor()

    def invoke(
        self,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
    ):
        if operation != "translate":
            raise TranslatorPluginError("translation_operation_unavailable")
        request = TranslationRequest.from_payload(payload)
        cancellation.raise_if_cancelled()
        gateway = services.get("provider_gateway") if isinstance(services, Mapping) else None
        if not callable(gateway):
            raise TranslatorPluginError("translation_service_unavailable")

        rendered = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"Translate the user text into {_TARGET_NAMES[request.target_language]}. "
                        "Preserve meaning, tone, paragraph breaks, lists, and code. "
                        "Return only the translation without explanations."
                    ),
                },
                {"role": "user", "content": request.text},
            ]
        }
        chunks: list[str] = []
        for raw_chunk in gateway(rendered, request.text, cancellation):
            cancellation.raise_if_cancelled()
            chunk = sanitize_text(raw_chunk)
            if not chunk:
                continue
            chunks.append(chunk)
            yield {"status": "chunk", "data": {"text": chunk}}

        cancellation.raise_if_cancelled()
        translated = sanitize_text("".join(chunks)).strip()
        if not translated:
            raise TranslatorPluginError("provider_empty_response")
        yield {
            "status": "result",
            "data": {
                "text": translated,
                "source_language": request.source_language,
                "target_language": request.target_language,
            },
        }


def plugin() -> TranslatorPlugin:
    return TranslatorPlugin()
