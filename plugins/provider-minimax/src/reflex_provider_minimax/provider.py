"""Synchronous MiniMax Provider implementation for the Reflex Core contract."""

from __future__ import annotations

import ssl
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import Any

import httpx

from reflex_core import CancellationToken, OptimizeRequest

from .sse import SseProtocolError, extract_json_content, iter_content_chunks

DEFAULT_BASE_URL = "https://api.minimaxi.com/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.7-highspeed"
SUPPORTED_MODELS = (DEFAULT_MODEL,)

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


class MiniMaxProvider:
    id = "minimax"

    def __init__(
        self,
        secret: str,
        config: Any,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
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

        try:
            with self._build_client() as client:
                for attempt in range(3):
                    try:
                        attempt_had_content = False
                        for chunk in self._stream_once(client, payload, cancellation):
                            if cancellation.is_cancelled:
                                return
                            attempt_had_content = True
                            yielded_content = True
                            yield chunk
                        if cancellation.is_cancelled:
                            return
                        if not attempt_had_content:
                            raise MiniMaxProviderError("provider_empty_response", retryable=False)
                        return
                    except MiniMaxProviderError as error:
                        if cancellation.is_cancelled:
                            return
                        if yielded_content or not error.retryable or attempt == 2:
                            raise
                        self._sleep((0.25, 0.5)[attempt])
        except MiniMaxProviderError:
            raise
        except httpx.TimeoutException:
            raise MiniMaxProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise MiniMaxProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError):
            raise MiniMaxProviderError("provider_invalid_response", retryable=False) from None

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
                status_error = _error_for_status(response.status_code)
                if status_error is not None:
                    raise status_error
                if cancellation.is_cancelled:
                    response.close()
                    return

                content_type = response.headers.get("content-type", "").lower()
                if "application/json" in content_type:
                    try:
                        parsed = response.json()
                    except ValueError:
                        raise MiniMaxProviderError(
                            "provider_invalid_response", retryable=False
                        ) from None
                    payloads = parsed if isinstance(parsed, list) else [parsed]
                    for item in payloads:
                        if cancellation.is_cancelled:
                            response.close()
                            return
                        content = extract_json_content(item)
                        if content:
                            yield content
                    return

                try:
                    for content in iter_content_chunks(response.iter_lines()):
                        if cancellation.is_cancelled:
                            response.close()
                            return
                        yield content
                except SseProtocolError:
                    raise MiniMaxProviderError(
                        "provider_invalid_response", retryable=False
                    ) from None
        except MiniMaxProviderError:
            raise
        except httpx.TimeoutException:
            raise MiniMaxProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise MiniMaxProviderError("provider_network_error", retryable=True) from None

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
