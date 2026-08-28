"""Synchronous MiniMax Provider implementation for the Reflex Core contract."""

from __future__ import annotations

import ssl
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

import httpx

from reflex_core import (
    CancellationToken,
    OperationCancelled,
    OptimizeRequest,
    ProviderEvent,
)

from .sse import (
    SseProtocolError,
    extract_json_content,
    iter_sse_payloads,
    read_json_payload,
)

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.7-highspeed"
SUPPORTED_MODELS = (DEFAULT_MODEL,)
RETRY_DELAYS_SECONDS = (0.25, 0.5)
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STREAM_EVENTS = 50_000
_THOUGHT_OPENERS = (("<think>", "</think>"), ("```think", "```"))

_SAFE_MESSAGES = {
    "provider_auth_failed": "Provider authentication failed.",
    "provider_rate_limited": "Provider rate limit reached.",
    "provider_timeout": "Provider request timed out.",
    "provider_network_error": "Provider network request failed.",
    "provider_service_error": "Provider service is unavailable.",
    "provider_invalid_response": "Provider response was invalid.",
    "provider_empty_response": "Provider returned no content.",
}


class MiniMaxProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(_SAFE_MESSAGES.get(code, "Provider request failed."))
        self.code = code
        self.retryable = retryable

    def __repr__(self) -> str:
        return f"MiniMaxProviderError(code={self.code!r}, retryable={self.retryable!r})"


class _ThoughtBlockFilter:
    def __init__(self) -> None:
        self._buffer = ""
        self._closing_marker: str | None = None

    def feed(self, chunk: str) -> list[str]:
        self._buffer += chunk
        visible: list[str] = []

        while self._buffer:
            if self._closing_marker is not None:
                lower = self._buffer.lower()
                closing_at = lower.find(self._closing_marker)
                if closing_at < 0:
                    _, self._buffer = _split_before_possible_marker(
                        self._buffer, (self._closing_marker,)
                    )
                    break
                self._buffer = self._buffer[
                    closing_at + len(self._closing_marker) :
                ].lstrip("\r\n")
                self._closing_marker = None
                continue

            lower = self._buffer.lower()
            opening_matches = [
                (lower.find(opener), opener, closer)
                for opener, closer in _THOUGHT_OPENERS
                if lower.find(opener) >= 0
            ]
            if opening_matches:
                opening_at, opener, closer = min(opening_matches, key=lambda item: item[0])
                if opening_at:
                    visible.append(self._buffer[:opening_at])
                self._buffer = self._buffer[opening_at + len(opener) :]
                self._closing_marker = closer
                continue

            released, self._buffer = _split_before_possible_marker(
                self._buffer, tuple(opener for opener, _ in _THOUGHT_OPENERS)
            )
            if released:
                visible.append(released)
            break

        return visible

    def finish(self) -> list[str]:
        if self._closing_marker is not None:
            self._buffer = ""
            return []
        trailing = self._buffer
        self._buffer = ""
        return [trailing] if trailing else []


def _split_before_possible_marker(text: str, markers: tuple[str, ...]) -> tuple[str, str]:
    lower = text.lower()
    max_suffix = min(len(text), max(len(marker) for marker in markers) - 1)
    for suffix_length in range(max_suffix, 0, -1):
        suffix = lower[-suffix_length:]
        if any(marker.startswith(suffix) for marker in markers):
            return text[:-suffix_length], text[-suffix_length:]
    return text, ""


class MiniMaxProvider:
    id = "minimax"

    def __init__(
        self,
        secret: str,
        config: Any,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        normalized_secret = secret.strip() if isinstance(secret, str) else ""
        if not normalized_secret:
            raise MiniMaxProviderError("provider_auth_failed", retryable=False)
        self._secret = normalized_secret
        self.model = _config_string(config, "model")
        self._base_url = _config_string(config, "base_url")
        self._timeout_seconds = _config_timeout(config)
        self._tls_verify = getattr(config, "tls_verify", True) is True
        self._ca_bundle_path = _optional_config_string(config, "ca_bundle_path")
        if self.model not in SUPPORTED_MODELS or not self._tls_verify:
            raise MiniMaxProviderError("provider_invalid_response", retryable=False)
        self._transport = transport
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"MiniMaxProvider(id={self.id!r}, model={self.model!r})"

    def stream_events(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterator[ProviderEvent]:
        """Expose MiniMax through Core's structured provider stream."""

        yield ProviderEvent.started(
            provider=self.id,
            model=request.model or self.model,
            protocol="openai_chat_completions",
        )
        for chunk in self.stream(rendered_request, request, cancellation):
            yield ProviderEvent.text(chunk)
        if cancellation.is_cancelled:
            yield ProviderEvent.cancelled()
            return
        yield ProviderEvent.completed(finish_reason="stop")

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        if cancellation.is_cancelled:
            return
        payload = self._request_payload(rendered_request, request)
        yielded_content = False

        client: httpx.Client | None = None
        unregister_client: Callable[[], None] = lambda: None
        try:
            client = self._build_client()
            unregister_client = cancellation.register(client.close)
            cancellation.raise_if_cancelled()
            for attempt in range(3):
                try:
                    attempt_had_content = False
                    thought_filter = _ThoughtBlockFilter()
                    raw_chunks = self._stream_once(client, payload, cancellation)
                    visible_chunks = (
                        visible
                        for raw_chunk in raw_chunks
                        for visible in thought_filter.feed(raw_chunk)
                    )
                    for chunk in visible_chunks:
                        if cancellation.is_cancelled:
                            return
                        attempt_had_content = True
                        yielded_content = True
                        yield chunk
                    for chunk in thought_filter.finish():
                        if cancellation.is_cancelled:
                            return
                        attempt_had_content = True
                        yielded_content = True
                        yield chunk
                    if cancellation.is_cancelled:
                        return
                    if not attempt_had_content:
                        raise MiniMaxProviderError(
                            "provider_empty_response", retryable=False
                        )
                    return
                except MiniMaxProviderError as error:
                    if cancellation.is_cancelled:
                        return
                    if yielded_content or not error.retryable or attempt == 2:
                        raise
                    if self._wait_for_retry(
                        cancellation, RETRY_DELAYS_SECONDS[attempt]
                    ):
                        return
        except OperationCancelled:
            return
        except MiniMaxProviderError:
            raise
        except httpx.TimeoutException:
            raise MiniMaxProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise MiniMaxProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError):
            raise MiniMaxProviderError("provider_invalid_response", retryable=False) from None
        finally:
            unregister_client()
            if client is not None:
                _close_quietly(client)

    def _stream_once(
        self,
        client: httpx.Client,
        payload: dict[str, object],
        cancellation: CancellationToken,
    ) -> Iterator[str]:
        try:
            with client.stream(
                "POST",
                self._base_url,
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

                    content_type = response.headers.get("content-type", "").lower()
                    if "application/json" in content_type:
                        try:
                            parsed = read_json_payload(
                                response.iter_bytes(), max_bytes=MAX_RESPONSE_BYTES
                            )
                        except SseProtocolError:
                            if cancellation.is_cancelled:
                                raise OperationCancelled("operation cancelled") from None
                            raise MiniMaxProviderError(
                                "provider_invalid_response", retryable=False
                            ) from None
                        payloads = parsed if isinstance(parsed, list) else [parsed]
                        for item in payloads:
                            cancellation.raise_if_cancelled()
                            content = extract_json_content(item)
                            if content:
                                cancellation.raise_if_cancelled()
                                yield content
                        return

                    try:
                        for parsed in iter_sse_payloads(
                            response.iter_bytes(),
                            max_bytes=MAX_RESPONSE_BYTES,
                            max_events=MAX_STREAM_EVENTS,
                        ):
                            cancellation.raise_if_cancelled()
                            payloads = parsed if isinstance(parsed, list) else [parsed]
                            for item in payloads:
                                content = extract_json_content(item)
                                if content:
                                    cancellation.raise_if_cancelled()
                                    yield content
                    except SseProtocolError:
                        if cancellation.is_cancelled:
                            raise OperationCancelled("operation cancelled") from None
                        raise MiniMaxProviderError(
                            "provider_invalid_response", retryable=False
                        ) from None
                finally:
                    unregister_response()
        except OperationCancelled:
            raise
        except MiniMaxProviderError:
            raise
        except httpx.TimeoutException:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise MiniMaxProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise MiniMaxProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError):
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise MiniMaxProviderError("provider_invalid_response", retryable=False) from None

    def _wait_for_retry(
        self, cancellation: CancellationToken, delay_seconds: float
    ) -> bool:
        if self._sleep is None:
            return cancellation.wait(delay_seconds)
        self._sleep(delay_seconds)
        return cancellation.is_cancelled

    def _request_payload(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
    ) -> dict[str, object]:
        model = request.model or self.model
        if model not in SUPPORTED_MODELS:
            raise MiniMaxProviderError("provider_invalid_response", retryable=False)
        return {
            "model": model,
            "messages": _messages_from_rendered(rendered_request),
            "stream": request.stream,
        }

    def _build_client(self) -> httpx.Client:
        verify: ssl.SSLContext | bool = True
        if self._ca_bundle_path:
            verify = ssl.create_default_context(cafile=self._ca_bundle_path)
        return httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout_seconds),
            verify=verify,
        )


def _messages_from_rendered(rendered_request: Any) -> list[dict[str, str]]:
    if not isinstance(rendered_request, Mapping):
        raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    raw_messages = rendered_request.get("messages")
    if isinstance(raw_messages, list):
        messages: list[dict[str, str]] = []
        for item in raw_messages:
            if not isinstance(item, Mapping):
                raise MiniMaxProviderError("provider_invalid_response", retryable=False)
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise MiniMaxProviderError("provider_invalid_response", retryable=False)
            messages.append({"role": role, "content": content})
        if messages:
            return messages

    messages = []
    system = rendered_request.get("system")
    user = rendered_request.get("user")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})
    if isinstance(user, str) and user:
        messages.append({"role": "user", "content": user})
    if messages:
        return messages

    text = rendered_request.get("text")
    if isinstance(text, str) and text:
        return [{"role": "user", "content": text}]
    raise MiniMaxProviderError("provider_invalid_response", retryable=False)


def _error_for_status(status_code: int) -> MiniMaxProviderError | None:
    if 200 <= status_code < 300:
        return None
    if status_code in {401, 403}:
        return MiniMaxProviderError("provider_auth_failed", retryable=False)
    if status_code == 429:
        return MiniMaxProviderError("provider_rate_limited", retryable=True)
    if status_code in {408, 504}:
        return MiniMaxProviderError("provider_timeout", retryable=True)
    if status_code >= 500:
        return MiniMaxProviderError("provider_service_error", retryable=True)
    return MiniMaxProviderError("provider_invalid_response", retryable=False)


def _config_string(config: Any, field_name: str) -> str:
    value = getattr(config, field_name, None)
    if not isinstance(value, str) or not value.strip():
        raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _optional_config_string(config: Any, field_name: str) -> str | None:
    value = getattr(config, field_name, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _config_timeout(config: Any) -> float:
    value = getattr(config, "timeout_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    timeout = float(value)
    if not 1.0 <= timeout <= 300.0:
        raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    return timeout


def _close_quietly(resource: Any) -> None:
    try:
        resource.close()
    except Exception:
        pass
