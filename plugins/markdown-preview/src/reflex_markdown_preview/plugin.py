"""Sanitized Markdown preview capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

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
_ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})
_MAX_INPUT_CHARS = 100_000
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024


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
                attributes=_allow_attribute,
                protocols=_ALLOWED_PROTOCOLS,
                strip=True,
                strip_comments=True,
            ).strip()
            output_size = len(clean_html.encode("utf-8"))
        except Exception:
            raise MarkdownPreviewError("markdown_render_failed") from None
        cancellation.raise_if_cancelled()
        if output_size > _MAX_OUTPUT_BYTES:
            raise MarkdownPreviewError("markdown_output_too_large")
        if operation == "export":
            return {"html": clean_html, "source": text}
        return {"html": clean_html}


def _validated_text(payload: object) -> str:
    if not isinstance(payload, dict) or set(payload) != {"text"}:
        raise MarkdownPreviewError("markdown_payload_invalid")
    text = payload.get("text")
    if not isinstance(text, str):
        raise MarkdownPreviewError("markdown_payload_invalid")
    if len(text) > _MAX_INPUT_CHARS:
        raise MarkdownPreviewError("markdown_input_too_large")
    try:
        return validate_input(text, max_length=_MAX_INPUT_CHARS)
    except (InputValidationError, TypeError):
        raise MarkdownPreviewError("markdown_payload_invalid") from None


def _allow_attribute(tag: str, name: str, value: str) -> bool:
    if tag == "code":
        return name == "class"
    if tag != "a":
        return False
    if name == "title":
        return True
    return name == "href" and _is_safe_link(value)


def _is_safe_link(value: str) -> bool:
    if not value or "\\" in value:
        return False
    if any(
        character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
        for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        hostname = parsed.hostname
        username = parsed.username
        password = parsed.password
    except (TypeError, ValueError):
        return False

    scheme = parsed.scheme.lower()
    if scheme in {"http", "https"}:
        return bool(
            parsed.netloc
            and hostname
            and username is None
            and password is None
            and (port is None or 0 < port <= 65_535)
        )
    if scheme == "mailto":
        return not parsed.netloc and bool(parsed.path)
    return False


def plugin() -> MarkdownPreviewPlugin:
    return MarkdownPreviewPlugin()
