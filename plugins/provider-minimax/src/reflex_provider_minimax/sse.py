"""Strict, body-safe parsing for MiniMax SSE and JSON responses."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any


class SseProtocolError(ValueError):
    def __init__(self) -> None:
        super().__init__("Provider response was invalid.")

    def __repr__(self) -> str:
        return "SseProtocolError()"


def iter_content_chunks(lines: Iterable[str]) -> Iterator[str]:
    for data in _iter_event_data(lines):
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise SseProtocolError() from None
        if isinstance(payload, list):
            for item in payload:
                content = extract_json_content(item)
                if content:
                    yield content
            continue
        content = extract_json_content(payload)
        if content:
            yield content


def extract_json_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    choice = choices[0]
    for container_name in ("delta", "message"):
        container = choice.get(container_name)
        if isinstance(container, dict):
            content = container.get("content")
            if isinstance(content, str):
                return content
    text = choice.get("text")
    return text if isinstance(text, str) else ""


def _iter_event_data(lines: Iterable[str]) -> Iterator[str]:
    pending: list[str] = []
    for raw_line in lines:
        if not isinstance(raw_line, str):
            raise SseProtocolError()
        line = raw_line.rstrip("\r\n")
        if not line:
            if pending:
                yield "\n".join(pending)
                pending.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            pending.append(line[5:].lstrip())
            continue
        if pending:
            yield "\n".join(pending)
            pending.clear()
        yield line.strip()
    if pending:
        yield "\n".join(pending)
