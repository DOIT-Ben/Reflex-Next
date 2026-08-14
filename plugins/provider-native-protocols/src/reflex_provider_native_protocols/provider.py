"""Anthropic Messages and Gemini GenerateContent Provider adapters."""

from __future__ import annotations

import codecs
import json
import ssl
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from reflex_core import CancellationToken, OperationCancelled, OptimizeRequest, ProviderEvent


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STREAM_EVENTS = 50_000
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (0.25, 0.5)

_SAFE_MESSAGES = {
    "provider_auth_failed": "Provider authentication failed.",
    "provider_rate_limited": "Provider rate limit reached.",
    "provider_timeout": "Provider request timed out.",
    "provider_network_error": "Provider network request failed.",
    "provider_service_error": "Provider service is unavailable.",
    "provider_invalid_response": "Provider response was invalid.",
    "provider_empty_response": "Provider returned no content.",
}


class NativeProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool,
        provider_error_type: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(_SAFE_MESSAGES.get(code, "Provider request failed."))
        self.code = code
        self.retryable = retryable
        self.provider_error_type = provider_error_type
        self.request_id = request_id

    def __repr__(self) -> str:
        return f"NativeProviderError(code={self.code!r}, retryable={self.retryable!r})"


class ProtocolError(ValueError):
    def __init__(self) -> None:
        super().__init__(_SAFE_MESSAGES["provider_invalid_response"])


@dataclass(frozen=True)
class NativeFactory:
    id: str
    display_name: str
    default_model: str
    models: tuple[str, ...]
    default_base_url: str
    provider_type: type["NativeProvider"]
    version: str = "1"
    required_secret: str = "api_key"
    permissions: tuple[str, ...] = ("network",)
    protocol: str = "anthropic_messages"
    accepts_custom_models: bool = False
    model_capabilities: dict[str, object] = field(default_factory=dict)

    def create(self, secret: str, config: Any) -> "NativeProvider":
        return self.provider_type(self, secret, config)


def anthropic() -> NativeFactory:
    return NativeFactory(
        id="anthropic",
        display_name="Anthropic",
        default_model="claude-sonnet-4-20250514",
        models=("claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"),
        default_base_url="https://api.anthropic.com/v1/messages",
        provider_type=AnthropicProvider,
        protocol="anthropic_messages",
        accepts_custom_models=True,
    )


def gemini() -> NativeFactory:
    return NativeFactory(
        id="gemini",
        display_name="Google Gemini",
        default_model="gemini-2.5-flash",
        models=("gemini-2.5-flash", "gemini-2.5-pro"),
        default_base_url="https://generativelanguage.googleapis.com/v1beta",
        provider_type=GeminiProvider,
        protocol="gemini_generate_content",
    )


class NativeProvider:
    def __init__(
        self,
        spec: NativeFactory,
        secret: str,
        config: Any,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        normalized_secret = secret.strip() if isinstance(secret, str) else ""
        if not normalized_secret:
            raise NativeProviderError("provider_auth_failed", retryable=False)
        self.id = spec.id
        self.protocol = spec.protocol
        self.model = _config_string(config, "model")
        self._models = spec.models
        self._accepts_custom_models = spec.accepts_custom_models
        self._secret = normalized_secret
        self._base_url = _config_https_url(config, "base_url")
        self._timeout = _config_timeout(config)
        self._ca = _optional_config_string(config, "ca_bundle_path")
        if getattr(config, "tls_verify", True) is not True or (
            self.model not in self._models and not self._accepts_custom_models
        ):
            raise NativeProviderError("provider_invalid_response", retryable=False)
        self._transport = transport
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"{type(self).__name__}(id={self.id!r}, model={self.model!r})"

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        if cancellation.is_cancelled:
            return
        model = request.model or self.model
        if model not in self._models and not self._accepts_custom_models:
            raise NativeProviderError("provider_invalid_response", retryable=False)
        url, headers, payload = self._build_request(rendered_request, request, model)
        idempotency_key = str(uuid.uuid4())
        headers = {**headers, "Idempotency-Key": idempotency_key}
        yielded_content = False
        client: httpx.Client | None = None
        unregister_client: Callable[[], None] = lambda: None
        try:
            client = self._build_client()
            unregister_client = cancellation.register(client.close)
            cancellation.raise_if_cancelled()
            for attempt in range(MAX_ATTEMPTS):
                try:
                    attempt_had_content = False
                    for content in self._stream_once(
                        client, url, headers, payload, request.stream, cancellation
                    ):
                        attempt_had_content = True
                        yielded_content = True
                        yield content
                    if not attempt_had_content:
                        raise NativeProviderError("provider_empty_response", retryable=False)
                    return
                except NativeProviderError as error:
                    if cancellation.is_cancelled:
                        return
                    if yielded_content or not error.retryable or attempt == MAX_ATTEMPTS - 1:
                        raise
                    if self._wait_for_retry(cancellation, RETRY_DELAYS_SECONDS[attempt]):
                        return
        except OperationCancelled:
            return
        except NativeProviderError:
            raise
        except httpx.TimeoutException:
            raise NativeProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise NativeProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError):
            raise NativeProviderError("provider_invalid_response", retryable=False) from None
        finally:
            unregister_client()
            if client is not None:
                _close_quietly(client)

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[ProviderEvent]:
        """Project the native stream into the Core lifecycle contract."""
        if cancellation.is_cancelled:
            return
        yield ProviderEvent.started(
            provider=self.id,
            model=request.model or self.model,
            protocol=self.protocol,
        )
        for text in self.stream(rendered_request, request, cancellation):
            yield ProviderEvent.text(text)
        if not cancellation.is_cancelled:
            yield ProviderEvent.completed(finish_reason="stop")

    def _build_request(
        self, rendered_request: Any, request: OptimizeRequest, model: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        raise NotImplementedError

    def _iter_stream_content(self, chunks: Iterable[bytes]) -> Iterator[str]:
        raise NotImplementedError

    def _parse_json_content(self, chunks: Iterable[bytes]) -> str:
        raise NotImplementedError

    def _stream_once(
        self,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        cancellation: CancellationToken,
    ) -> Iterator[str]:
        try:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                unregister_response = cancellation.register(response.close)
                try:
                    cancellation.raise_if_cancelled()
                    status_error = _error_for_status(response.status_code)
                    if status_error is not None:
                        raise status_error
                    content_type = response.headers.get("content-type", "").lower()
                    if not stream or "json" in content_type:
                        content = self._parse_json_content(response.iter_bytes())
                        cancellation.raise_if_cancelled()
                        if content:
                            yield content
                        return
                    for content in self._iter_stream_content(response.iter_bytes()):
                        cancellation.raise_if_cancelled()
                        if content:
                            yield content
                finally:
                    unregister_response()
        except OperationCancelled:
            raise
        except NativeProviderError:
            raise
        except httpx.TimeoutException:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_network_error", retryable=True) from None
        except ProtocolError:
            raise NativeProviderError("provider_invalid_response", retryable=False) from None
        except (httpx.HTTPError, OSError, ValueError):
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_invalid_response", retryable=False) from None

    def _build_client(self) -> httpx.Client:
        verify: bool | ssl.SSLContext = True
        if self._ca:
            try:
                verify = ssl.create_default_context(cafile=self._ca)
            except (OSError, ssl.SSLError):
                raise NativeProviderError("provider_invalid_response", retryable=False) from None
        return httpx.Client(
            timeout=httpx.Timeout(self._timeout),
            verify=verify,
            transport=self._transport,
            follow_redirects=False,
        )

    def _wait_for_retry(self, cancellation: CancellationToken, delay: float) -> bool:
        if self._sleep is None:
            return cancellation.wait(delay)
        self._sleep(delay)
        return cancellation.is_cancelled


class AnthropicProvider(NativeProvider):
    def list_models(self) -> tuple[str, ...]:
        url = _anthropic_models_url(self._base_url)
        try:
            with self._build_client() as client:
                response = client.get(
                    url,
                    headers={
                        "x-api-key": self._secret,
                        "anthropic-version": "2023-06-01",
                        "Accept": "application/json",
                    },
                )
                status_error = _error_for_status(response.status_code)
                if status_error is not None:
                    raise status_error
                return _parse_native_models(response.content)
        except NativeProviderError:
            raise
        except httpx.TimeoutException:
            raise NativeProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise NativeProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError, UnicodeError):
            raise NativeProviderError("provider_invalid_response", retryable=False) from None

    def test_connection(self, model: str | None = None) -> bool:
        return isinstance(model, str) and model in self.list_models()

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        """Retain the legacy text-only projection for existing Core consumers."""
        for event in self.stream_events(rendered_request, request, cancellation):
            if event.kind == "text_delta":
                text = event.data.get("text")
                if isinstance(text, str) and text:
                    yield text
            elif event.kind == "error":
                raise NativeProviderError(
                    str(event.data.get("code", "provider_invalid_response")),
                    retryable=event.data.get("retryable") is True,
                    provider_error_type=_optional_event_string(
                        event.data.get("provider_error_type")
                    ),
                    request_id=_optional_event_string(event.data.get("request_id")),
                )
            elif event.kind == "cancelled":
                return

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[ProviderEvent]:
        """Emit the official Anthropic Messages lifecycle as Core Provider events."""
        if cancellation.is_cancelled:
            yield ProviderEvent.cancelled()
            return
        model = request.model or self.model
        if model not in self._models and not self._accepts_custom_models:
            yield ProviderEvent.started(
                provider=self.id, model=model, protocol=self.protocol
            )
            yield _provider_error_event(
                NativeProviderError("provider_invalid_response", retryable=False)
            )
            return
        try:
            url, headers, payload = self._build_request(rendered_request, request, model)
        except NativeProviderError as error:
            yield ProviderEvent.started(
                provider=self.id, model=model, protocol=self.protocol
            )
            yield _provider_error_event(error)
            return
        headers = {**headers, "Idempotency-Key": str(uuid.uuid4())}
        client: httpx.Client | None = None
        unregister_client: Callable[[], None] = lambda: None
        try:
            client = self._build_client()
            unregister_client = cancellation.register(client.close)
            cancellation.raise_if_cancelled()
            for attempt in range(MAX_ATTEMPTS):
                emitted_event = False
                try:
                    for event in self._stream_anthropic_once(
                        client, url, headers, payload, request.stream, cancellation, model
                    ):
                        emitted_event = True
                        yield event
                    return
                except NativeProviderError as error:
                    if cancellation.is_cancelled:
                        yield ProviderEvent.cancelled()
                        return
                    if emitted_event or not error.retryable or attempt == MAX_ATTEMPTS - 1:
                        if not emitted_event:
                            yield ProviderEvent.started(
                                provider=self.id, model=model, protocol=self.protocol
                            )
                        yield _provider_error_event(error)
                        return
                    if self._wait_for_retry(cancellation, RETRY_DELAYS_SECONDS[attempt]):
                        yield ProviderEvent.cancelled()
                        return
        except OperationCancelled:
            yield ProviderEvent.cancelled()
        except httpx.TimeoutException:
            yield ProviderEvent.started(
                provider=self.id, model=model, protocol=self.protocol
            )
            yield _provider_error_event(
                NativeProviderError("provider_timeout", retryable=True)
            )
        except httpx.NetworkError:
            yield ProviderEvent.started(
                provider=self.id, model=model, protocol=self.protocol
            )
            yield _provider_error_event(
                NativeProviderError("provider_network_error", retryable=True)
            )
        except (httpx.HTTPError, OSError, ValueError):
            yield ProviderEvent.started(
                provider=self.id, model=model, protocol=self.protocol
            )
            yield _provider_error_event(
                NativeProviderError("provider_invalid_response", retryable=False)
            )
        finally:
            unregister_client()
            if client is not None:
                _close_quietly(client)

    def _build_request(
        self, rendered_request: Any, request: OptimizeRequest, model: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        system, messages = _split_messages(rendered_request, assistant_role="assistant")
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
            "stream": request.stream,
        }
        return (
            self._base_url,
            {
                "x-api-key": self._secret,
                "anthropic-version": "2023-06-01",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            payload,
        )

    def _iter_stream_content(self, chunks: Iterable[bytes]) -> Iterator[str]:
        for event in self._iter_anthropic_sse_events(chunks, model=self.model, request_id=None):
            if event.kind == "text_delta":
                text = event.data.get("text")
                if isinstance(text, str) and text:
                    yield text

    def _parse_json_content(self, chunks: Iterable[bytes]) -> str:
        payload = _read_json(chunks)
        content = payload.get("content")
        if not isinstance(content, list):
            raise ProtocolError()
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            text = block.get("text")
            if not isinstance(text, str):
                raise ProtocolError()
            parts.append(text)
        return "".join(parts)

    def _stream_anthropic_once(
        self,
        client: httpx.Client,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        stream: bool,
        cancellation: CancellationToken,
        model: str,
    ) -> Iterator[ProviderEvent]:
        try:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                unregister_response = cancellation.register(response.close)
                try:
                    cancellation.raise_if_cancelled()
                    provider_request_id = _optional_event_string(
                        response.headers.get("request-id")
                    )
                    status_error = _error_for_status(response.status_code)
                    if status_error is not None:
                        status_error.request_id = provider_request_id
                        raise status_error
                    content_type = response.headers.get("content-type", "").lower()
                    if not stream or "application/json" in content_type:
                        for event in self._parse_anthropic_message_events(
                            _read_json(response.iter_bytes()),
                            model=model,
                            request_id=provider_request_id,
                        ):
                            cancellation.raise_if_cancelled()
                            yield event
                        return
                    if "text/event-stream" not in content_type:
                        raise ProtocolError()
                    for event in self._iter_anthropic_sse_events(
                        response.iter_bytes(), model=model, request_id=provider_request_id
                    ):
                        cancellation.raise_if_cancelled()
                        yield event
                finally:
                    unregister_response()
        except OperationCancelled:
            raise
        except NativeProviderError:
            raise
        except httpx.TimeoutException:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_network_error", retryable=True) from None
        except ProtocolError:
            raise NativeProviderError("provider_invalid_response", retryable=False) from None
        except (httpx.HTTPError, OSError, ValueError):
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise NativeProviderError("provider_invalid_response", retryable=False) from None

    def _parse_anthropic_message_events(
        self,
        message: dict[str, Any],
        *,
        model: str,
        request_id: str | None,
    ) -> Iterator[ProviderEvent]:
        response_id, response_model, usage = _validate_anthropic_message(
            message, expected_model=model
        )
        yield _provider_started_event(
            self,
            response_model,
            response_id=response_id,
            request_id=request_id,
        )
        if usage:
            yield _usage_event(usage)
        content = message["content"]
        for block in content:
            if block.get("type") == "text":
                text = block.get("text")
                if not isinstance(text, str):
                    raise ProtocolError()
                if text:
                    yield ProviderEvent.text(text)
        finish_reason = message.get("stop_reason")
        if not isinstance(finish_reason, str) or not finish_reason:
            raise ProtocolError()
        completed = {
            "finish_reason": finish_reason,
            "response_id": response_id,
        }
        stop_sequence = message.get("stop_sequence")
        stop_details = message.get("stop_details")
        if stop_sequence is not None:
            if not isinstance(stop_sequence, str):
                raise ProtocolError()
            completed["stop_sequence"] = stop_sequence
        if stop_details is not None:
            if not isinstance(stop_details, dict):
                raise ProtocolError()
            completed["stop_details"] = dict(stop_details)
        if request_id:
            completed["request_id"] = request_id
        yield ProviderEvent("completed", completed)

    def _iter_anthropic_sse_events(
        self,
        chunks: Iterable[bytes],
        *,
        model: str,
        request_id: str | None,
    ) -> Iterator[ProviderEvent]:
        seen_start = False
        seen_message_delta = False
        terminal = False
        active_blocks: dict[int, str] = {}
        closed_blocks: set[int] = set()
        response_id: str | None = None
        response_model = model
        finish_reason: str | None = None
        stop_sequence: str | None = None
        stop_details: dict[str, Any] | None = None

        for event_name, payload in _iter_sse_json_events(chunks):
            payload_type = payload.get("type")
            effective_type = event_name or payload_type
            if event_name == "ping" or effective_type == "ping":
                continue
            if event_name == "error" or effective_type == "error":
                raise _anthropic_stream_error(payload, fallback_request_id=request_id)
            known_types = {
                "message_start",
                "content_block_start",
                "content_block_delta",
                "content_block_stop",
                "message_delta",
                "message_stop",
            }
            if effective_type not in known_types:
                continue
            if payload_type is not None and payload_type != effective_type:
                raise ProtocolError()

            if effective_type == "message_start":
                if seen_start:
                    raise ProtocolError()
                message = payload.get("message")
                if not isinstance(message, dict):
                    raise ProtocolError()
                response_id, response_model, usage = _validate_anthropic_message(
                    message, expected_model=model, streaming_start=True
                )
                seen_start = True
                yield _provider_started_event(
                    self,
                    response_model,
                    response_id=response_id,
                    request_id=request_id,
                )
                if usage:
                    yield _usage_event(usage)
                continue

            if not seen_start or terminal:
                raise ProtocolError()
            if effective_type == "content_block_start":
                index = _anthropic_block_index(payload)
                block = payload.get("content_block")
                if (
                    not isinstance(block, dict)
                    or not isinstance(block.get("type"), str)
                    or index in active_blocks
                    or index in closed_blocks
                    or seen_message_delta
                ):
                    raise ProtocolError()
                active_blocks[index] = block["type"]
            elif effective_type == "content_block_delta":
                index = _anthropic_block_index(payload)
                if index not in active_blocks or seen_message_delta:
                    raise ProtocolError()
                delta = payload.get("delta")
                if not isinstance(delta, dict) or not isinstance(delta.get("type"), str):
                    raise ProtocolError()
                delta_type = delta["type"]
                if delta_type == "text_delta":
                    text = delta.get("text")
                    if active_blocks[index] != "text" or not isinstance(text, str):
                        raise ProtocolError()
                    if text:
                        yield ProviderEvent.text(text)
                elif delta_type == "input_json_delta":
                    if not isinstance(delta.get("partial_json"), str):
                        raise ProtocolError()
                elif delta_type == "thinking_delta":
                    if not isinstance(delta.get("thinking"), str):
                        raise ProtocolError()
                elif delta_type == "signature_delta":
                    if not isinstance(delta.get("signature"), str):
                        raise ProtocolError()
                elif delta_type == "citations_delta":
                    if not isinstance(delta.get("citation"), dict):
                        raise ProtocolError()
                # Unknown future delta types are intentionally ignored.
            elif effective_type == "content_block_stop":
                index = _anthropic_block_index(payload)
                if index not in active_blocks or seen_message_delta:
                    raise ProtocolError()
                active_blocks.pop(index)
                closed_blocks.add(index)
            elif effective_type == "message_delta":
                if active_blocks:
                    raise ProtocolError()
                delta = payload.get("delta")
                usage = payload.get("usage")
                if not isinstance(delta, dict) or not isinstance(usage, dict):
                    raise ProtocolError()
                next_finish_reason = _optional_anthropic_string(delta.get("stop_reason"))
                if next_finish_reason is not None:
                    finish_reason = next_finish_reason
                next_stop_sequence = _optional_anthropic_string(delta.get("stop_sequence"))
                if next_stop_sequence is not None:
                    stop_sequence = next_stop_sequence
                raw_stop_details = delta.get("stop_details")
                if raw_stop_details is not None and not isinstance(raw_stop_details, dict):
                    raise ProtocolError()
                stop_details = (
                    dict(raw_stop_details) if isinstance(raw_stop_details, dict) else stop_details
                )
                seen_message_delta = True
                usage_snapshot = _validate_anthropic_usage(usage, partial=True)
                if usage_snapshot:
                    yield _usage_event(usage_snapshot)
            else:
                if active_blocks or not seen_message_delta or finish_reason is None:
                    raise ProtocolError()
                terminal = True
                completed: dict[str, Any] = {
                    "finish_reason": finish_reason,
                    "response_id": response_id,
                }
                if stop_sequence is not None:
                    completed["stop_sequence"] = stop_sequence
                if stop_details is not None:
                    completed["stop_details"] = stop_details
                if request_id:
                    completed["request_id"] = request_id
                yield ProviderEvent("completed", completed)
                break
        if not terminal:
            raise ProtocolError()


class GeminiProvider(NativeProvider):
    def _build_request(
        self, rendered_request: Any, request: OptimizeRequest, model: str
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        system, messages = _split_messages(rendered_request, assistant_role="model")
        suffix = "streamGenerateContent?alt=sse" if request.stream else "generateContent"
        url = f"{self._base_url.rstrip('/')}/models/{quote(model, safe='')}:{suffix}"
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": item["role"], "parts": [{"text": item["content"]}]}
                for item in messages
            ],
        }
        return (
            url,
            {
                "x-goog-api-key": self._secret,
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            payload,
        )

    def _iter_stream_content(self, chunks: Iterable[bytes]) -> Iterator[str]:
        terminal = False
        for payload in _iter_sse_json(chunks):
            candidate = _first_candidate(payload)
            yield from _gemini_candidate_text(candidate)
            finish_reason = candidate.get("finishReason")
            if finish_reason is not None:
                if not isinstance(finish_reason, str) or not finish_reason:
                    raise ProtocolError()
                terminal = True
                break
        if not terminal:
            raise ProtocolError()

    def _parse_json_content(self, chunks: Iterable[bytes]) -> str:
        return "".join(_gemini_candidate_text(_first_candidate(_read_json(chunks))))


def _anthropic_models_url(value: str) -> str:
    parsed = urlsplit(value)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments or segments[-1] != "messages":
        raise NativeProviderError("provider_invalid_response", retryable=False)
    segments[-1] = "models"
    return parsed._replace(path="/" + "/".join(segments)).geturl()


def _parse_native_models(raw: bytes) -> tuple[str, ...]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise NativeProviderError("provider_invalid_response", retryable=False)
    payload = json.loads(raw.decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise NativeProviderError("provider_invalid_response", retryable=False)
    models = tuple(
        sorted(
            {
                item["id"]
                for item in data
                if isinstance(item, dict)
                and item.get("type") in {None, "model"}
                and isinstance(item.get("id"), str)
                and 1 <= len(item["id"]) <= 256
                and item["id"] == item["id"].strip()
                and all(char.isascii() and char.isprintable() for char in item["id"])
            }
        )
    )
    if not models or len(models) > 256:
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return models


def _split_messages(
    rendered_request: Any, *, assistant_role: str
) -> tuple[str, list[dict[str, str]]]:
    if not isinstance(rendered_request, dict):
        raise NativeProviderError("provider_invalid_response", retryable=False)
    raw_messages = rendered_request.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise NativeProviderError("provider_invalid_response", retryable=False)
    system_parts: list[str] = []
    messages: list[dict[str, str]] = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            raise NativeProviderError("provider_invalid_response", retryable=False)
        role = raw.get("role")
        content = raw.get("content")
        if not isinstance(content, str) or role not in {"system", "user", "assistant"}:
            raise NativeProviderError("provider_invalid_response", retryable=False)
        if role == "system":
            system_parts.append(content)
        else:
            messages.append(
                {"role": assistant_role if role == "assistant" else "user", "content": content}
            )
    if not messages:
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return "\n\n".join(system_parts), messages


def _iter_sse_json(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    count = 0
    for data in _iter_event_data(chunks):
        count += 1
        if count > MAX_STREAM_EVENTS:
            raise ProtocolError()
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise ProtocolError() from None
        if not isinstance(payload, dict):
            raise ProtocolError()
        yield payload


def _iter_sse_json_events(
    chunks: Iterable[bytes],
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    count = 0
    for event_name, data in _iter_sse_events(chunks):
        count += 1
        if count > MAX_STREAM_EVENTS:
            raise ProtocolError()
        try:
            payload = json.loads(data)
        except (TypeError, json.JSONDecodeError):
            raise ProtocolError() from None
        if not isinstance(payload, dict):
            raise ProtocolError()
        yield event_name, payload


def _iter_sse_events(chunks: Iterable[bytes]) -> Iterator[tuple[str | None, str]]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    pending_data: list[str] = []
    pending_event: list[str | None] = [None]
    total = 0
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ProtocolError()
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise ProtocolError()
            buffer += decoder.decode(chunk)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                event = _consume_sse_event_line(
                    line.rstrip("\r"), pending_event, pending_data
                )
                if event is not None:
                    yield event
        buffer += decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        raise ProtocolError() from None
    if buffer:
        event = _consume_sse_event_line(buffer.rstrip("\r"), pending_event, pending_data)
        if event is not None:
            yield event
    if pending_data:
        yield pending_event[0], "\n".join(pending_data)


def _consume_sse_event_line(
    line: str,
    pending_event: list[str | None],
    pending_data: list[str],
) -> tuple[str | None, str] | None:
    if not line:
        if not pending_data:
            pending_event[0] = None
            return None
        event = pending_event[0], "\n".join(pending_data)
        pending_event[0] = None
        pending_data.clear()
        return event
    if line.startswith(":"):
        return None
    field, separator, value = line.partition(":")
    if separator and value.startswith(" "):
        value = value[1:]
    if field == "event":
        pending_event[0] = value or None
    elif field == "data":
        pending_data.append(value)
    return None


def _iter_event_data(chunks: Iterable[bytes]) -> Iterator[str]:
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    buffer = ""
    pending_data: list[str] = []
    total = 0
    try:
        for chunk in chunks:
            if not isinstance(chunk, bytes):
                raise ProtocolError()
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
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


def _read_json(chunks: Iterable[bytes]) -> dict[str, Any]:
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes):
            raise ProtocolError()
        total += len(chunk)
        if total > MAX_RESPONSE_BYTES:
            raise ProtocolError()
        parts.append(chunk)
    try:
        payload = json.loads(b"".join(parts).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtocolError() from None
    if not isinstance(payload, dict):
        raise ProtocolError()
    return payload


def _first_candidate(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise ProtocolError()
    return candidates[0]


def _gemini_candidate_text(candidate: dict[str, Any]) -> Iterator[str]:
    content = candidate.get("content")
    if content is None:
        return
    if not isinstance(content, dict):
        raise ProtocolError()
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ProtocolError()
    for part in parts:
        if not isinstance(part, dict):
            raise ProtocolError()
        text = part.get("text")
        if not isinstance(text, str):
            raise ProtocolError()
        if text:
            yield text


def _error_for_status(status: int) -> NativeProviderError | None:
    if 200 <= status < 300:
        return None
    if status in {401, 403}:
        return NativeProviderError("provider_auth_failed", retryable=False)
    if status in {408, 504}:
        return NativeProviderError("provider_timeout", retryable=True)
    if status == 429:
        return NativeProviderError("provider_rate_limited", retryable=True)
    if status in {500, 502, 503, 529}:
        return NativeProviderError("provider_service_error", retryable=True)
    return NativeProviderError("provider_invalid_response", retryable=False)


def _provider_error_event(error: NativeProviderError) -> ProviderEvent:
    data: dict[str, Any] = {"code": error.code, "retryable": error.retryable}
    if error.provider_error_type:
        data["provider_error_type"] = error.provider_error_type
    if error.request_id:
        data["request_id"] = error.request_id
    return ProviderEvent("error", data)


def _provider_started_event(
    provider: NativeProvider,
    model: str,
    *,
    response_id: str,
    request_id: str | None,
) -> ProviderEvent:
    data: dict[str, Any] = {
        "provider": provider.id,
        "model": model,
        "protocol": provider.protocol,
        "response_id": response_id,
    }
    if request_id:
        data["request_id"] = request_id
    return ProviderEvent("request_started", data)


def _usage_event(usage: dict[str, Any]) -> ProviderEvent:
    return ProviderEvent("usage", dict(usage))


def _validate_anthropic_message(
    message: dict[str, Any],
    *,
    expected_model: str,
    streaming_start: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    response_id = message.get("id")
    response_model = message.get("model")
    content = message.get("content")
    usage = message.get("usage")
    if (
        not isinstance(response_id, str)
        or not response_id
        or message.get("type") != "message"
        or message.get("role") != "assistant"
        or not isinstance(response_model, str)
        or not response_model
        or not isinstance(content, list)
        or not isinstance(usage, dict)
    ):
        raise ProtocolError()
    if streaming_start and (content or message.get("stop_reason") is not None):
        raise ProtocolError()
    if not streaming_start:
        for block in content:
            if not isinstance(block, dict) or not isinstance(block.get("type"), str):
                raise ProtocolError()
    # Providers may return an alias-resolved model name; preserve it rather than
    # falsely rejecting an otherwise valid response.
    _ = expected_model
    return response_id, response_model, _validate_anthropic_usage(usage, partial=False)


def _validate_anthropic_usage(
    usage: dict[str, Any], *, partial: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    required = ("output_tokens",) if partial else ("input_tokens", "output_tokens")
    for key in required:
        if key not in usage:
            raise ProtocolError()
    integer_fields = {
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
    for key, value in usage.items():
        if key in integer_fields:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ProtocolError()
            result[key] = value
        elif key in {
            "cache_creation",
            "output_tokens_details",
            "server_tool_use",
        }:
            if value is not None and not isinstance(value, dict):
                raise ProtocolError()
            if value is not None:
                result[key] = dict(value)
        elif key in {"inference_geo", "service_tier"}:
            if value is not None and not isinstance(value, str):
                raise ProtocolError()
            if value is not None:
                result[key] = value
        else:
            # Preserve additive usage fields introduced by future API versions.
            result[key] = value
    return result


def _anthropic_block_index(payload: dict[str, Any]) -> int:
    index = payload.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ProtocolError()
    return index


def _optional_anthropic_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ProtocolError()
    return value


def _optional_event_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _anthropic_stream_error(
    payload: dict[str, Any], *, fallback_request_id: str | None
) -> NativeProviderError:
    error = payload.get("error")
    if not isinstance(error, dict):
        raise ProtocolError()
    error_type = error.get("type")
    if not isinstance(error_type, str) or not error_type:
        raise ProtocolError()
    request_id = _optional_event_string(payload.get("request_id")) or fallback_request_id
    if error_type == "overloaded_error":
        code, retryable = "provider_service_error", True
    elif error_type == "rate_limit_error":
        code, retryable = "provider_rate_limited", True
    elif error_type == "authentication_error":
        code, retryable = "provider_auth_failed", False
    elif error_type in {"api_error", "timeout_error"}:
        code, retryable = "provider_service_error", True
    else:
        code, retryable = "provider_invalid_response", False
    return NativeProviderError(
        code,
        retryable=retryable,
        provider_error_type=error_type,
        request_id=request_id,
    )


def _config_string(config: Any, name: str) -> str:
    value = getattr(config, name, None)
    if not isinstance(value, str) or not value.strip():
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _optional_config_string(config: Any, name: str) -> str | None:
    value = getattr(config, name, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _config_https_url(config: Any, name: str) -> str:
    value = _config_string(config, name)
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return value


def _config_timeout(config: Any) -> float:
    value = getattr(config, "timeout_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NativeProviderError("provider_invalid_response", retryable=False)
    timeout = float(value)
    if timeout < 1.0 or timeout > 300.0:
        raise NativeProviderError("provider_invalid_response", retryable=False)
    return timeout


def _close_quietly(client: httpx.Client) -> None:
    try:
        client.close()
    except Exception:
        pass
