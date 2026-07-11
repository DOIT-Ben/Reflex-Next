"""Sanitized Markdown preview capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bleach
import markdown
from reflex_core.safety import InputValidationError, validate_input

_ALLOWED_TAGS = frozenset(
    {
        "a", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
        "h4", "h5", "h6", "hr", "li", "ol", "p", "pre", "strong",
        "table", "tbody", "td", "th", "thead", "tr", "ul",
    }
)
_ALLOWED_ATTRIBUTES = {"a": ["href", "title"], "code": ["class"]}
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})


class MarkdownPreviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MarkdownPreviewDescriptor:
    plugin_id: str = "markdown-preview"
    display_name: str = "Markdown Preview"
    version: str = "1"
    kind: str = "command"
    permissions: tuple[str, ...] = ()
    operations: tuple[str, ...] = ("preview", "export")
    public_operations: tuple[str, ...] = ("preview",)


class MarkdownPreviewPlugin:
    descriptor = MarkdownPreviewDescriptor()

    def invoke(
        self,
        operation: str,
        payload: dict[str, Any],
        services: Any,
        cancellation: Any,
    ) -> dict[str, Any]:
        if operation not in {"preview", "export"}:
            raise MarkdownPreviewError("markdown_operation_unavailable")
        text = _validated_text(payload)
        cancellation.raise_if_cancelled()
        try:
            rendered = markdown.markdown(
                text,
                extensions=("extra", "nl2br", "sane_lists"),
                output_format="html",
            )
            clean_html = bleach.clean(
                rendered,
                tags=_ALLOWED_TAGS,
                attributes=_ALLOWED_ATTRIBUTES,
                protocols=_ALLOWED_PROTOCOLS,
                strip=True,
                strip_comments=True,
            ).strip()
        except Exception:
            raise MarkdownPreviewError("markdown_render_failed") from None
        cancellation.raise_if_cancelled()
        if len(clean_html) > 2_000_000:
            raise MarkdownPreviewError("markdown_output_too_large")
        return {"html": clean_html, "source": text} if operation == "export" else {"html": clean_html}


def _validated_text(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"text"}:
        raise MarkdownPreviewError("markdown_payload_invalid")
    try:
        return validate_input(payload.get("text"))
    except (InputValidationError, TypeError):
        raise MarkdownPreviewError("markdown_payload_invalid") from None


def plugin() -> MarkdownPreviewPlugin:
    return MarkdownPreviewPlugin()
