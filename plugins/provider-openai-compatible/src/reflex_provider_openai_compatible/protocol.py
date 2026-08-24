"""Bounded parsing for OpenAI-compatible JSON and SSE responses."""

from __future__ import annotations

import codecs
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any


class ProtocolError(ValueError):
    def __init__(self) -> None:
        super().__init__("Provider response was invalid.")

    def __repr__(self) -> str:
        return "ProtocolError()"


@dataclass(frozen=True)
class ChatCompletionPart:
    response_id: str | None = None
    text: str | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass(frozen=True)
class ChatCompletionResponse:
    response_id: str | None
    text: str
    finish_reason: str
    usage: dict[str, int] | None


def parse_chat_completion(chunks: Iterable[bytes], *, max_bytes: int) -> ChatCompletionResponse:
    raw = _read_bounded(chunks, max_bytes=max_bytes)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtocolError() from None
    choice = _first_choice(payload)
    content = _choice_content(choice, "message")
    finish_reason = _finish_reason(choice) or "stop"
    return ChatCompletionResponse(
        response_id=_response_id(payload),
        text=content or "",
        finish_reason=finish_reason,
        usage=_usage(payload),
    )


def iter_chat_completion_parts(
    chunks: Iterable[bytes], *, max_bytes: int, max_events: int
) -> Iterator[ChatCompletionPart]:
    event_count = 0
    saw_done = False
    saw_finish_reason = False
    for data in _iter_event_data(chunks, max_bytes=max_bytes):
        if data == "[DONE]":
            saw_done = True
            break
        event_count += 1
        if event_count > max_events:
            raise ProtocolError()
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise ProtocolError() from None
        if not isinstance(payload, dict):
            raise ProtocolError()

        usage = _usage(payload)
        choices = payload.get("choices")
        if not isinstance(choices, list):
            raise ProtocolError()
        if not choices:
            if usage is None:
                raise ProtocolError()
            yield ChatCompletionPart(response_id=_response_id(payload), usage=usage)
            continue
        if not isinstance(choices[0], dict):
            raise ProtocolError()

        choice = choices[0]
        text = _choice_content(choice, "delta")
        finish_reason = _finish_reason(choice)
        if finish_reason is not None:
            saw_finish_reason = True
        yield ChatCompletionPart(
            response_id=_response_id(payload),
            text=text,
            finish_reason=finish_reason,
            usage=usage,
        )
    if not saw_done and not saw_finish_reason:
        raise ProtocolError()


def parse_json_content(chunks: Iterable[bytes], *, max_bytes: int) -> str:
    return parse_chat_completion(chunks, max_bytes=max_bytes).text


def iter_sse_content(
    chunks: Iterable[bytes], *, max_bytes: int, max_events: int
) -> Iterator[str]:
    event_count = 0
    saw_done = False
    for data in _iter_event_data(chunks, max_bytes=max_bytes):
        if data == "[DONE]":
            saw_done = True
            break
        event_count += 1
        if event_count > max_events:
            raise ProtocolError()
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise ProtocolError() from None
        content = _extract_content(payload)
        if content:
            yield content
        if _is_terminal_payload(payload):
            saw_done = True
            break
    if not saw_done:
        raise ProtocolError()


def _extract_content(payload: Any) -> str | None:
    choice = _first_choice(payload)
    for container_name in ("delta", "message"):
        if container_name not in choice:
            continue
        return _choice_content(choice, container_name)

    if "text" in choice:
        text = choice["text"]
        if not isinstance(text, str):
            raise ProtocolError()
        return text
    raise ProtocolError()


def _is_terminal_payload(payload: Any) -> bool:
    choice = _first_choice(payload)
    return _finish_reason(choice) is not None


def _choice_content(choice: dict[str, Any], container_name: str) -> str | None:
    container = choice.get(container_name)
    if not isinstance(container, dict):
        raise ProtocolError()
    content = container.get("content")
    if content is None:
        return None
    if not isinstance(content, str):
        raise ProtocolError()
    return content


def _finish_reason(choice: dict[str, Any]) -> str | None:
    finish_reason = choice.get("finish_reason")
    if finish_reason is None:
        return None
    if (
        not isinstance(finish_reason, str)
        or not finish_reason
        or len(finish_reason) > 64
        or not all(character.isascii() and character.isprintable() for character in finish_reason)
    ):
        raise ProtocolError()
    return finish_reason


def _response_id(payload: dict[str, Any]) -> str | None:
    response_id = payload.get("id")
    if response_id is None:
        return None
    if (
        not isinstance(response_id, str)
        or not response_id
        or len(response_id) > 256
        or not all(character.isascii() and character.isprintable() for character in response_id)
    ):
        raise ProtocolError()
    return response_id


def _usage(payload: dict[str, Any]) -> dict[str, int] | None:
    raw_usage = payload.get("usage")
    if raw_usage is None:
        return None
    if not isinstance(raw_usage, dict):
        raise ProtocolError()
    names = {
        "prompt_tokens": "input_tokens",
        "completion_tokens": "output_tokens",
        "total_tokens": "total_tokens",
    }
    usage: dict[str, int] = {}
    for source, target in names.items():
        value = raw_usage.get(source)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProtocolError()
        usage[target] = value
    if not usage:
        raise ProtocolError()
    return usage


def _first_choice(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ProtocolError()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProtocolError()
    return choices[0]


def _read_bounded(chunks: Iterable[bytes], *, max_bytes: int) -> bytes:
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise ProtocolError()
        total += len(chunk)
        if total > max_bytes:
            raise ProtocolError()
        parts.append(chunk)
    return b"".join(parts)


def _iter_event_data(
    chunks: Iterable[bytes], *, max_bytes: int
) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    pending_data: list[str] = []
    total = 0

    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ProtocolError()
            total += len(chunk)
            if total > max_bytes:
                raise ProtocolError()
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                data = _consume_sse_line(line.rstrip("\r"), pending_data)
                if data is not None:
                    yield data
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise ProtocolError() from None

    if buffer:
        data = _consume_sse_line(buffer.rstrip("\r"), pending_data)
        if data is not None:
            yield data
    if pending_data:
        yield "\n".join(pending_data)


def _consume_sse_line(line: str, pending_data: list[str]) -> str | None:
    if not line:
        if not pending_data:
            return None
        data = "\n".join(pending_data)
        pending_data.clear()
        return data
    if line.startswith(":"):
        return None

    field, separator, value = line.partition(":")
    if field != "data":
        return None
    if separator and value.startswith(" "):
        value = value[1:]
    pending_data.append(value)
    return None
