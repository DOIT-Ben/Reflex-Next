"""Dependency-light adapter for the official OpenAI Responses API."""

from __future__ import annotations

import codecs
import json
import ssl
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from reflex_core import (
    CancellationToken,
    OperationCancelled,
    OptimizeRequest,
    ProviderEvent,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_EVENTS = 50_000
_PROTOCOL = "openai_responses"


class ResponsesProviderError(RuntimeError):
    """A stable, redacted error that is safe to cross the Runtime boundary."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__("Provider request failed.")
        self.code = code
        self.retryable = retryable

    def __repr__(self) -> str:
        return (
            "ResponsesProviderError("
            f"code={self.code!r}, retryable={self.retryable!r})"
        )


@dataclass(frozen=True)
class ResponsesFactory:
    id: str = "openai-responses"
    display_name: str = "OpenAI Responses"
    version: str = "0.1.0"
    models: tuple[str, ...] = ("gpt-5.6-luna",)
    default_model: str = "gpt-5.6-luna"
    default_base_url: str = "https://api.openai.com/v1/responses"
    required_secret: str = "api_key"
    permissions: tuple[str, ...] = ("network",)
    protocol: str = _PROTOCOL
    accepts_custom_models: bool = True

    def create(self, secret: str, config: Any) -> "ResponsesProvider":
        return ResponsesProvider(self, secret, config)


def openai_responses() -> ResponsesFactory:
    return ResponsesFactory()


class ResponsesProvider:
    def __init__(
        self,
        spec: ResponsesFactory,
        secret: str,
        config: Any,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(secret, str) or not secret.strip():
            raise ResponsesProviderError("provider_auth_failed")
        self.id = spec.id
        self.protocol = spec.protocol
        self.model = _config_string(config, "model")
        self._url = _config_url(config, "base_url")
        self._secret = secret.strip()
        self._timeout = _config_timeout(config)
        self._ca = getattr(config, "ca_bundle_path", None)
        self._transport = transport

    def __repr__(self) -> str:
        return f"ResponsesProvider(id={self.id!r}, model={self.model!r})"

    def list_models(self) -> tuple[str, ...]:
        client = httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout),
            verify=self._verify(),
        )
        try:
            response = client.get(
                _models_url(self._url),
                headers={
                    "Authorization": f"Bearer {self._secret}",
                    "Accept": "application/json",
                },
            )
            status_error = _error_for_status(response.status_code)
            if status_error is not None:
                raise status_error
            return _parse_models(response.content)
        except ResponsesProviderError:
            raise
        except httpx.TimeoutException:
            raise ResponsesProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise ResponsesProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError, UnicodeError):
            raise ResponsesProviderError("provider_invalid_response") from None
        finally:
            _close_quietly(client)

    def test_connection(self, model: str | None = None) -> bool:
        return isinstance(model, str) and model in self.list_models()

    def _verify(self) -> ssl.SSLContext | bool:
        if self._ca:
            return ssl.create_default_context(cafile=self._ca)
        return True

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        """Retain the legacy text-only Provider contract."""
        for event in self.stream_events(rendered_request, request, cancellation):
            if event.kind == "text_delta":
                yield str(event.data.get("text", ""))
            elif event.kind == "error":
                raise ResponsesProviderError(
                    str(event.data.get("code", "provider_service_error")),
                    retryable=bool(event.data.get("retryable", False)),
                )

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterator[ProviderEvent]:
        if cancellation.is_cancelled:
            return

        model = request.model or self.model
        if not _valid_model_id(model):
            raise ResponsesProviderError("provider_invalid_response")
        payload = _request_payload(rendered_request, model, request.stream)
        client = httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout),
            verify=self._verify(),
        )
        unregister_client = cancellation.register(client.close)
        try:
            cancellation.raise_if_cancelled()
            with client.stream(
                "POST",
                self._url,
                headers={
                    "Authorization": f"Bearer {self._secret}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                unregister_response = cancellation.register(response.close)
                try:
                    cancellation.raise_if_cancelled()
                    status_error = _error_for_status(response.status_code)
                    if status_error is not None:
                        raise status_error
                    if request.stream:
                        yield from _iter_response_events(
                            response.iter_bytes(), model, self.id, cancellation
                        )
                    else:
                        body = _read_json(response.iter_bytes())
                        cancellation.raise_if_cancelled()
                        yield from _parse_response(body, model, self.id)
                finally:
                    unregister_response()
        except OperationCancelled:
            yield ProviderEvent.cancelled()
        except ResponsesProviderError:
            raise
        except httpx.TimeoutException:
            if cancellation.is_cancelled:
                yield ProviderEvent.cancelled()
                return
            raise ResponsesProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            if cancellation.is_cancelled:
                yield ProviderEvent.cancelled()
                return
            raise ResponsesProviderError(
                "provider_network_error", retryable=True
            ) from None
        except (httpx.HTTPError, OSError, ValueError, UnicodeError):
            if cancellation.is_cancelled:
                yield ProviderEvent.cancelled()
                return
            raise ResponsesProviderError("provider_invalid_response") from None
        finally:
            unregister_client()
            _close_quietly(client)


def _iter_response_events(
    chunks: Iterable[bytes],
    model: str,
    provider: str,
    cancellation: CancellationToken,
) -> Iterator[ProviderEvent]:
    started = False
    terminal = False
    response_id: str | None = None

    for raw in _iter_sse_data(chunks):
        cancellation.raise_if_cancelled()
        event_type = raw.get("type")
        if not isinstance(event_type, str):
            raise ResponsesProviderError("provider_invalid_response")

        event_response = _optional_response(raw)
        current_response_id = _response_id(event_response)
        if current_response_id is not None:
            response_id = current_response_id

        if event_type in {
            "response.created",
            "response.queued",
            "response.in_progress",
        }:
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            continue

        if event_type == "response.output_text.delta":
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            delta = raw.get("delta")
            if not isinstance(delta, str):
                raise ResponsesProviderError("provider_invalid_response")
            if delta:
                yield ProviderEvent.text(delta)
            continue

        if event_type == "response.completed":
            if event_response is None:
                raise ResponsesProviderError("provider_invalid_response")
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            yield from _usage_events(event_response)
            yield ProviderEvent.completed(
                finish_reason="stop", response_id=response_id
            )
            terminal = True
            break

        if event_type == "response.incomplete":
            if event_response is None:
                raise ResponsesProviderError("provider_invalid_response")
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            yield from _usage_events(event_response)
            yield ProviderEvent.completed(
                finish_reason=_incomplete_finish_reason(event_response),
                response_id=response_id,
                incomplete=True,
            )
            terminal = True
            break

        if event_type == "response.failed":
            if event_response is None:
                raise ResponsesProviderError("provider_invalid_response")
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            yield from _usage_events(event_response)
            code, retryable = _response_error(event_response.get("error"))
            yield ProviderEvent.error(code, retryable=retryable)
            terminal = True
            break

        if event_type == "error":
            if not started:
                started = True
                yield ProviderEvent.started(
                    provider=provider,
                    model=model,
                    protocol=_PROTOCOL,
                    response_id=response_id,
                )
            code, retryable = _response_error(raw)
            yield ProviderEvent.error(code, retryable=retryable)
            terminal = True
            break

        # Other official semantic events carry structure, tool calls, reasoning,
        # or finalized text. Text is emitted only from output_text.delta so a
        # final output_text.done event cannot duplicate accumulated content.

    cancellation.raise_if_cancelled()
    if not terminal:
        raise ResponsesProviderError("provider_invalid_response")


def _parse_response(
    body: dict[str, Any], model: str, provider: str
) -> Iterator[ProviderEvent]:
    response_id = _response_id(body)
    yield ProviderEvent.started(
        provider=provider,
        model=model,
        protocol=_PROTOCOL,
        response_id=response_id,
    )

    status = body.get("status", "completed")
    if not isinstance(status, str):
        raise ResponsesProviderError("provider_invalid_response")
    text = _response_text(body)
    if text:
        yield ProviderEvent.text(text)
    yield from _usage_events(body)

    if status == "completed":
        yield ProviderEvent.completed(
            finish_reason="stop", response_id=response_id
        )
        return
    if status == "incomplete":
        yield ProviderEvent.completed(
            finish_reason=_incomplete_finish_reason(body),
            response_id=response_id,
            incomplete=True,
        )
        return
    if status == "failed":
        code, retryable = _response_error(body.get("error"))
        yield ProviderEvent.error(code, retryable=retryable)
        return
    if status == "cancelled":
        yield ProviderEvent.cancelled(reason="provider")
        return
    raise ResponsesProviderError("provider_invalid_response")


def _request_payload(
    rendered: Any, model: str, stream: bool
) -> dict[str, object]:
    input_items, instructions = _input_from_rendered(rendered)
    payload: dict[str, object] = {
        "model": model,
        "input": input_items,
        "stream": stream,
    }
    if instructions:
        payload["instructions"] = instructions
    return payload


def _input_from_rendered(
    rendered: Any,
) -> tuple[list[dict[str, str]], str | None]:
    if not isinstance(rendered, Mapping):
        raise ResponsesProviderError("provider_invalid_response")

    messages = rendered.get("messages")
    if isinstance(messages, list) and messages:
        input_items: list[dict[str, str]] = []
        instructions: list[str] = []
        for item in messages:
            if not isinstance(item, Mapping):
                raise ResponsesProviderError("provider_invalid_response")
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "developer", "user", "assistant"} or not isinstance(
                content, str
            ):
                raise ResponsesProviderError("provider_invalid_response")
            if role in {"system", "developer"}:
                if content:
                    instructions.append(content)
            elif content:
                input_items.append({"role": role, "content": content})
        if not input_items:
            raise ResponsesProviderError("provider_invalid_response")
        return input_items, "\n\n".join(instructions) or None

    system = rendered.get("system")
    user = rendered.get("user")
    if isinstance(user, str) and user:
        instructions = system if isinstance(system, str) and system else None
        return [{"role": "user", "content": user}], instructions

    text = rendered.get("text")
    if isinstance(text, str) and text:
        return [{"role": "user", "content": text}], None
    raise ResponsesProviderError("provider_invalid_response")


def _iter_sse_data(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    pending_data: list[str] = []
    total = 0
    event_count = 0

    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ResponsesProviderError("provider_invalid_response")
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ResponsesProviderError("provider_invalid_response")
            buffer += decoder.decode(chunk)
            while True:
                line_result = _pop_sse_line(buffer)
                if line_result is None:
                    break
                line, buffer = line_result
                data = _consume_sse_line(line, pending_data)
                if data is not None:
                    event_count += 1
                    if event_count > MAX_EVENTS:
                        raise ResponsesProviderError("provider_invalid_response")
                    payload = _decode_sse_payload(data)
                    if payload is not None:
                        yield payload
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise ResponsesProviderError("provider_invalid_response") from None

    while buffer:
        line_result = _pop_sse_line(buffer, final=True)
        if line_result is None:
            line, buffer = buffer, ""
        else:
            line, buffer = line_result
        data = _consume_sse_line(line, pending_data)
        if data is not None:
            event_count += 1
            if event_count > MAX_EVENTS:
                raise ResponsesProviderError("provider_invalid_response")
            payload = _decode_sse_payload(data)
            if payload is not None:
                yield payload
    if pending_data:
        event_count += 1
        if event_count > MAX_EVENTS:
            raise ResponsesProviderError("provider_invalid_response")
        payload = _decode_sse_payload("\n".join(pending_data))
        if payload is not None:
            yield payload


def _pop_sse_line(buffer: str, *, final: bool = False) -> tuple[str, str] | None:
    for index, character in enumerate(buffer):
        if character == "\n":
            return buffer[:index], buffer[index + 1 :]
        if character == "\r":
            if index + 1 == len(buffer) and not final:
                return None
            offset = 2 if buffer[index + 1 : index + 2] == "\n" else 1
            return buffer[:index], buffer[index + offset :]
    return None


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


def _decode_sse_payload(data: str) -> dict[str, Any] | None:
    # Some compatible gateways append the Chat Completions sentinel. It is
    # harmless after a real Responses terminal event and is never terminal by
    # itself here.
    if data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        raise ResponsesProviderError("provider_invalid_response") from None
    if not isinstance(payload, dict):
        raise ResponsesProviderError("provider_invalid_response")
    return payload


def _read_json(chunks: Iterable[bytes]) -> dict[str, Any]:
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise ResponsesProviderError("provider_invalid_response")
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ResponsesProviderError("provider_invalid_response")
        parts.append(chunk)
    try:
        payload = json.loads(b"".join(parts).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ResponsesProviderError("provider_invalid_response") from None
    if not isinstance(payload, dict):
        raise ResponsesProviderError("provider_invalid_response")
    return payload


def _response_text(body: Mapping[str, Any]) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text
    if output_text is not None:
        raise ResponsesProviderError("provider_invalid_response")

    output = body.get("output", [])
    if not isinstance(output, list):
        raise ResponsesProviderError("provider_invalid_response")
    parts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            raise ResponsesProviderError("provider_invalid_response")
        content = item.get("content", [])
        if not isinstance(content, list):
            raise ResponsesProviderError("provider_invalid_response")
        for part in content:
            if not isinstance(part, Mapping):
                raise ResponsesProviderError("provider_invalid_response")
            if part.get("type") == "output_text":
                text = part.get("text")
                if not isinstance(text, str):
                    raise ResponsesProviderError("provider_invalid_response")
                parts.append(text)
    return "".join(parts)


def _usage_events(response: Mapping[str, Any]) -> Iterator[ProviderEvent]:
    raw_usage = response.get("usage")
    if raw_usage is None:
        return
    if not isinstance(raw_usage, Mapping):
        raise ResponsesProviderError("provider_invalid_response")
    values: dict[str, int] = {}
    for source, target in (
        ("input_tokens", "input_tokens"),
        ("output_tokens", "output_tokens"),
        ("total_tokens", "total_tokens"),
    ):
        raw_value = raw_usage.get(source)
        if raw_value is None:
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
            raise ResponsesProviderError("provider_invalid_response")
        values[target] = raw_value
    if values:
        yield ProviderEvent.usage(**values)


def _optional_response(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    response = raw.get("response")
    if response is None:
        return None
    if not isinstance(response, dict):
        raise ResponsesProviderError("provider_invalid_response")
    return response


def _response_id(response: Mapping[str, Any] | None) -> str | None:
    if response is None:
        return None
    value = response.get("id")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ResponsesProviderError("provider_invalid_response")
    return value


def _incomplete_finish_reason(response: Mapping[str, Any]) -> str:
    details = response.get("incomplete_details")
    if details is None:
        return "incomplete"
    if not isinstance(details, Mapping):
        raise ResponsesProviderError("provider_invalid_response")
    reason = details.get("reason")
    if reason == "max_output_tokens":
        return "length"
    if reason == "content_filter":
        return "content_filter"
    return "incomplete"


def _response_error(raw_error: Any) -> tuple[str, bool]:
    if not isinstance(raw_error, Mapping):
        return "provider_service_error", False
    raw_code = raw_error.get("code")
    if not isinstance(raw_code, str):
        return "provider_service_error", False
    if raw_code in {"rate_limit_exceeded", "rate_limit_error"}:
        return "provider_rate_limited", True
    if raw_code in {"server_error", "vector_store_timeout", "overloaded_error"}:
        return "provider_service_error", True
    if raw_code in {"request_timeout", "timeout"}:
        return "provider_timeout", True
    return "provider_invalid_response", False


def _error_for_status(status_code: int) -> ResponsesProviderError | None:
    if 200 <= status_code < 300:
        return None
    if status_code in {401, 403}:
        return ResponsesProviderError("provider_auth_failed")
    if status_code == 429:
        return ResponsesProviderError("provider_rate_limited", retryable=True)
    if status_code in {408, 504}:
        return ResponsesProviderError("provider_timeout", retryable=True)
    if status_code == 529 or 500 <= status_code < 600:
        return ResponsesProviderError("provider_service_error", retryable=True)
    return ResponsesProviderError("provider_invalid_response")


def _valid_model_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 256
        and value == value.strip()
        and all(character.isascii() and character.isprintable() for character in value)
    )


def _models_url(value: str) -> str:
    parsed = urlsplit(value)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments or segments[-1] != "responses":
        raise ResponsesProviderError("provider_invalid_response")
    segments[-1] = "models"
    return parsed._replace(path="/" + "/".join(segments)).geturl()


def _parse_models(raw: bytes) -> tuple[str, ...]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ResponsesProviderError("provider_invalid_response")
    payload = json.loads(raw.decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ResponsesProviderError("provider_invalid_response")
    models = tuple(
        sorted(
            {
                item["id"]
                for item in data
                if isinstance(item, dict) and _valid_model_id(item.get("id"))
            }
        )
    )
    if not models or len(models) > 256:
        raise ResponsesProviderError("provider_invalid_response")
    return models


def _config_string(config: Any, field: str) -> str:
    value = getattr(config, field, None)
    if not isinstance(value, str) or not value.strip():
        raise ResponsesProviderError("provider_invalid_response")
    return value.strip()


def _config_url(config: Any, field: str) -> str:
    value = _config_string(config, field)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ResponsesProviderError("provider_invalid_response")
    return value


def _config_timeout(config: Any) -> float:
    value = getattr(config, "timeout_seconds", 60.0)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not 1 <= float(value) <= 300
    ):
        raise ResponsesProviderError("provider_invalid_response")
    return float(value)


def _close_quietly(resource: Any) -> None:
    try:
        resource.close()
    except (httpx.HTTPError, OSError, RuntimeError):
        pass
