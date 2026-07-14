"""Strict, body-safe parsing for MiniMax SSE and JSON responses."""

from __future__ import annotations

import codecs
import json
from collections.abc import Iterable, Iterator
from typing import Any


class SseProtocolError(ValueError):
    def __init__(self) -> None:
        super().__init__("Provider response was invalid.")

    def __repr__(self) -> str:
        return "SseProtocolError()"


def read_json_payload(chunks: Iterable[bytes], *, max_bytes: int) -> Any:
    raw = _read_bounded(chunks, max_bytes=max_bytes)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SseProtocolError() from None


def iter_sse_payloads(
    chunks: Iterable[bytes], *, max_bytes: int, max_events: int
) -> Iterator[Any]:
    event_count = 0
    saw_done = False
    saw_terminal_payload = False
    for data in _iter_byte_event_data(chunks, max_bytes=max_bytes):
        if data == "[DONE]":
            saw_done = True
            break
        event_count += 1
        if event_count > max_events:
            raise SseProtocolError()
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise SseProtocolError() from None
        yield payload
        if _has_terminal_finish_reason(payload):
            saw_terminal_payload = True
    if not saw_done and not saw_terminal_payload:
        raise SseProtocolError()


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


def _has_terminal_finish_reason(payload: Any) -> bool:
    payloads = payload if isinstance(payload, list) else [payload]
    for item in payloads:
        if not isinstance(item, dict):
            continue
        choices = item.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            finish_reason = choice.get("finish_reason")
            if (
                isinstance(finish_reason, str)
                and finish_reason.strip()
                and len(finish_reason) <= 64
            ):
                return True
    return False


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


def _read_bounded(chunks: Iterable[bytes], *, max_bytes: int) -> bytes:
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise SseProtocolError()
        total += len(chunk)
        if total > max_bytes:
            raise SseProtocolError()
        parts.append(chunk)
    return b"".join(parts)


def _iter_byte_event_data(
    chunks: Iterable[bytes], *, max_bytes: int
) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    pending: list[str] = []
    total = 0
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise SseProtocolError()
            total += len(chunk)
            if total > max_bytes:
                raise SseProtocolError()
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                data = _consume_sse_line(line.rstrip("\r"), pending)
                if data is not None:
                    yield data
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise SseProtocolError() from None

    if buffer:
        data = _consume_sse_line(buffer.rstrip("\r"), pending)
        if data is not None:
            yield data
    if pending:
        yield "\n".join(pending)


def _consume_sse_line(line: str, pending: list[str]) -> str | None:
    if not line:
        if not pending:
            return None
        data = "\n".join(pending)
        pending.clear()
        return data
    if line.startswith(":"):
        return None
    field, separator, value = line.partition(":")
    if field != "data":
        return None
    if separator and value.startswith(" "):
        value = value[1:]
    pending.append(value)
    return None
