from __future__ import annotations

import pytest

from reflex_core import CancellationToken, OperationCancelled
from reflex_markdown_preview.plugin import MarkdownPreviewError, MarkdownPreviewPlugin


def invoke(text: str) -> dict[str, str]:
    return MarkdownPreviewPlugin().invoke("preview", {"text": text}, {}, CancellationToken())


def test_renders_common_markdown_without_permissions() -> None:
    plugin = MarkdownPreviewPlugin()
    result = invoke("# Title\n\n- one\n- two\n\n```py\nprint('ok')\n```")
    assert plugin.descriptor.permissions == ()
    assert "<h1>Title</h1>" in result["html"]
    assert "<li>one</li>" in result["html"]
    assert "language-py" in result["html"]


@pytest.mark.parametrize(
    "source, forbidden",
    [
        ("<script>alert(1)</script>", "<script"),
        ("<img src=x onerror=alert(1)>", "<img"),
        ("[bad](javascript:alert(1))", "javascript:"),
        ("<div style='background:url(https://example.test)'>x</div>", "style="),
        ("<!-- secret comment -->visible", "secret comment"),
    ],
)
def test_strips_active_or_remote_content(source: str, forbidden: str) -> None:
    assert forbidden not in invoke(source)["html"].lower()


def test_keeps_safe_links_but_no_event_attributes() -> None:
    html = invoke("[site](https://example.com \"Example\")")["html"]
    assert 'href="https://example.com"' in html
    assert "onclick" not in html


@pytest.mark.parametrize("payload", [{}, {"text": "x", "extra": True}, {"text": ""}])
def test_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(MarkdownPreviewError, match="markdown_payload_invalid"):
        MarkdownPreviewPlugin().invoke("preview", payload, {}, CancellationToken())


def test_honors_cancellation_before_rendering() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        MarkdownPreviewPlugin().invoke("preview", {"text": "# x"}, {}, token)
