from __future__ import annotations

import importlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from reflex_core import CancellationToken, OperationCancelled
from reflex_markdown_preview.plugin import MarkdownPreviewError, MarkdownPreviewPlugin


_ATTACK_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "markdown_attacks.json").read_text(
        encoding="utf-8"
    )
)
_ALLOWED_OUTPUT_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}
_PLUGIN_MODULE = importlib.import_module("reflex_markdown_preview.plugin")


class OutputAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str, str | None]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.tags.append(tag)
        self.attributes.extend((tag, name, value) for name, value in attrs)

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.handle_starttag(tag, attrs)


def invoke(text: str) -> dict[str, str]:
    return MarkdownPreviewPlugin().invoke(
        "preview", {"text": text}, {}, CancellationToken()
    )


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
    html = invoke(
        "[site](https://example.com/path?q=1#section \"Example\") "
        "[email](mailto:reader@example.com)"
    )["html"]
    assert 'href="https://example.com/path?q=1#section"' in html
    assert 'href="mailto:reader@example.com"' in html
    assert "onclick" not in html


@pytest.mark.parametrize(
    "case",
    _ATTACK_FIXTURES["dangerous_urls"],
    ids=lambda case: case["id"],
)
def test_dangerous_or_local_urls_never_become_navigation(case: dict[str, str]) -> None:
    html = invoke(case["source"])["html"]
    parser = OutputAuditParser()
    parser.feed(html)
    assert not [
        value
        for tag, name, value in parser.attributes
        if tag == "a" and name == "href"
    ]


@pytest.mark.parametrize(
    "case",
    _ATTACK_FIXTURES["active_markup"],
    ids=lambda case: case["id"],
)
def test_active_html_and_svg_leave_no_executable_surface(case: dict[str, str]) -> None:
    html = invoke(case["source"])["html"]
    parser = OutputAuditParser()
    parser.feed(html)

    assert set(parser.tags) <= _ALLOWED_OUTPUT_TAGS
    assert all(not name.lower().startswith("on") for _, name, _ in parser.attributes)
    assert all(
        (tag == "a" and name in {"href", "title"})
        or (tag == "code" and name == "class")
        for tag, name, _ in parser.attributes
    )
    for tag, name, value in parser.attributes:
        if tag != "a" or name != "href" or value is None:
            continue
        parsed = urlsplit(value)
        assert parsed.scheme in {"http", "https", "mailto"}
        assert parsed.username is None
        assert parsed.password is None


def test_export_applies_the_same_html_safety_boundary() -> None:
    plugin = MarkdownPreviewPlugin()
    result = plugin.invoke(
        "export",
        {"text": "[local](../secret) <iframe src='file:///etc/passwd'></iframe>"},
        {},
        CancellationToken(),
    )
    assert "href=" not in result["html"]
    assert "iframe" not in result["html"]
    assert result["source"].startswith("[local]")


@pytest.mark.parametrize("payload", [{}, {"text": "x", "extra": True}, {"text": ""}])
def test_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(MarkdownPreviewError, match="markdown_payload_invalid"):
        MarkdownPreviewPlugin().invoke("preview", payload, {}, CancellationToken())


def test_honors_cancellation_before_rendering() -> None:
    token = CancellationToken()
    token.cancel()
    with pytest.raises(OperationCancelled):
        MarkdownPreviewPlugin().invoke("preview", {"text": "# x"}, {}, token)


def test_rejects_oversized_input_with_a_specific_safe_error() -> None:
    with pytest.raises(MarkdownPreviewError) as caught:
        invoke("x" * 100_001)
    assert caught.value.code == "markdown_input_too_large"
    assert "x" * 20 not in str(caught.value)


def test_rejects_oversized_utf8_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _PLUGIN_MODULE.markdown,
        "markdown",
        lambda *_args, **_kwargs: "\u00e9" * 1_048_577,
    )
    with pytest.raises(MarkdownPreviewError) as caught:
        invoke("small source")
    assert caught.value.code == "markdown_output_too_large"


def test_render_failure_does_not_echo_exception_or_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "credential-in-attacker-input"

    def fail_render(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError(f"renderer failed for {secret}")

    monkeypatch.setattr(_PLUGIN_MODULE.markdown, "markdown", fail_render)
    with pytest.raises(MarkdownPreviewError) as caught:
        invoke(secret)
    assert caught.value.code == "markdown_render_failed"
    assert secret not in str(caught.value)
