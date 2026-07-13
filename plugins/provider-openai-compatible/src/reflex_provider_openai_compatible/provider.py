"""Reliable OpenAI-compatible Provider adapter without vendor SDKs."""

from __future__ import annotations

import ssl
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from reflex_core import CancellationToken, OperationCancelled, OptimizeRequest

from .protocol import ProtocolError, iter_sse_content, parse_json_content


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_STREAM_EVENTS = 50_000
MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (0.25, 0.5)

SPECS = {
    "deepseek": (
        "DeepSeek",
        "deepseek-chat",
        ("deepseek-chat", "deepseek-reasoner"),
        "https://api.deepseek.com/chat/completions",
    ),
    "qwen": (
        "通义千问",
        "qwen-turbo",
        ("qwen-turbo", "qwen-plus", "qwen-max"),
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    ),
    "zhipu": (
        "智谱 GLM",
        "glm-4.5-air",
        ("glm-4.5-air", "glm-4.7"),
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    ),
    "siliconflow": (
        "SiliconFlow",
        "deepseek-ai/DeepSeek-V3",
        ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"),
        "https://api.siliconflow.cn/v1/chat/completions",
    ),
}

_SAFE_MESSAGES = {
    "provider_auth_failed": "Provider authentication failed.",
    "provider_rate_limited": "Provider rate limit reached.",
    "provider_timeout": "Provider request timed out.",
    "provider_network_error": "Provider network request failed.",
    "provider_service_error": "Provider service is unavailable.",
    "provider_invalid_response": "Provider response was invalid.",
    "provider_empty_response": "Provider returned no content.",
}


class CompatibleProviderError(RuntimeError):
    """Expose only a stable error code and retry decision to the Runtime."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(_SAFE_MESSAGES.get(code, "Provider request failed."))
        self.code = code
        self.retryable = retryable

    def __repr__(self) -> str:
        return (
            "CompatibleProviderError("
            f"code={self.code!r}, retryable={self.retryable!r})"
        )


# Preserve the accidental module-level import used by early 0.1.x callers.
MiniMaxProviderError = CompatibleProviderError


@dataclass(frozen=True)
class CompatibleFactory:
    id: str
    display_name: str
    default_model: str
    models: tuple[str, ...]
    default_base_url: str
    version: str = "1"
    required_secret: str = "api_key"
    permissions: tuple[str, ...] = ("network",)

    def create(self, secret: str, config: Any) -> "CompatibleProvider":
        return CompatibleProvider(self, secret, config)


def factory(provider_id: str) -> CompatibleFactory:
    name, model, models, base_url = SPECS[provider_id]
    return CompatibleFactory(provider_id, name, model, models, base_url)


class CompatibleProvider:
    def __init__(
        self,
        spec: CompatibleFactory,
        secret: str,
        config: Any,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        normalized_secret = secret.strip() if isinstance(secret, str) else ""
        if not normalized_secret:
            raise CompatibleProviderError("provider_auth_failed", retryable=False)

        self.id = spec.id
        self.model = _config_string(config, "model")
        self._models = spec.models
        self._secret = normalized_secret
        self._url = _config_https_url(config, "base_url")
        self._timeout = _config_timeout(config)
        self._ca = _optional_config_string(config, "ca_bundle_path")
        if getattr(config, "tls_verify", True) is not True:
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            )
        if self.model not in self._models:
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            )
        self._transport = transport
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"CompatibleProvider(id={self.id!r}, model={self.model!r})"

    def stream(
        self,
        rendered_request: Any,
        request: OptimizeRequest,
        cancellation: CancellationToken,
    ) -> Iterable[str]:
        if cancellation.is_cancelled:
            return

        payload = self._request_payload(rendered_request, request)
        idempotency_key = str(uuid.uuid4())
        yielded_content = False

        client: httpx.Client | None = None
        unregister_client: Callable[[], None] = lambda: None
        try:
            client = self._build_client()
            unregister_client = cancellation.register(client.close)
            cancellation.raise_if_cancelled()
            for attempt in range(MAX_ATTEMPTS):
                if cancellation.is_cancelled:
                    return
                try:
                    attempt_had_content = False
                    for content in self._stream_once(
                        client,
                        payload,
                        idempotency_key,
                        cancellation,
                    ):
                        if cancellation.is_cancelled:
                            return
                        attempt_had_content = True
                        yielded_content = True
                        yield content
                    if cancellation.is_cancelled:
                        return
                    if not attempt_had_content:
                        raise CompatibleProviderError(
                            "provider_empty_response", retryable=False
                        )
                    return
                except CompatibleProviderError as error:
                    if cancellation.is_cancelled:
                        return
                    if (
                        yielded_content
                        or not error.retryable
                        or attempt == MAX_ATTEMPTS - 1
                    ):
                        raise
                    if self._wait_for_retry(
                        cancellation, RETRY_DELAYS_SECONDS[attempt]
                    ):
                        return
        except OperationCancelled:
            return
        except CompatibleProviderError:
            raise
        except httpx.TimeoutException:
            raise CompatibleProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            raise CompatibleProviderError(
                "provider_network_error", retryable=True
            ) from None
        except (httpx.HTTPError, OSError, ValueError):
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        finally:
            unregister_client()
            if client is not None:
                _close_quietly(client)

    def _stream_once(
        self,
        client: httpx.Client,
        payload: dict[str, object],
        idempotency_key: str,
        cancellation: CancellationToken,
    ) -> Iterator[str]:
        try:
            with client.stream(
                "POST",
                self._url,
                headers={
                    "Authorization": f"Bearer {self._secret}",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
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
                    if "json" in content_type or not payload["stream"]:
                        content = parse_json_content(
                            response.iter_bytes(), max_bytes=MAX_RESPONSE_BYTES
                        )
                        cancellation.raise_if_cancelled()
                        if content:
                            yield content
                        return

                    for content in iter_sse_content(
                        response.iter_bytes(),
                        max_bytes=MAX_RESPONSE_BYTES,
                        max_events=MAX_STREAM_EVENTS,
                    ):
                        cancellation.raise_if_cancelled()
                        yield content
                finally:
                    unregister_response()
        except OperationCancelled:
            raise
        except CompatibleProviderError:
            raise
        except httpx.TimeoutException:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise CompatibleProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise CompatibleProviderError(
                "provider_network_error", retryable=True
            ) from None
        except ProtocolError:
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            ) from None
        except (httpx.HTTPError, OSError, ValueError):
            if cancellation.is_cancelled:
                raise OperationCancelled("operation cancelled") from None
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            ) from None

    def _wait_for_retry(
        self, cancellation: CancellationToken, delay_seconds: float
    ) -> bool:
        if self._sleep is None:
            return cancellation.wait(delay_seconds)
        self._sleep(delay_seconds)
        return cancellation.is_cancelled

    def _request_payload(
        self, rendered_request: Any, request: OptimizeRequest
    ) -> dict[str, object]:
        model = request.model or self.model
        if model not in self._models:
            raise CompatibleProviderError(
                "provider_invalid_response", retryable=False
            )
        return {
            "model": model,
            "messages": _messages_from_rendered(rendered_request),
            "stream": request.stream,
        }

    def _build_client(self) -> httpx.Client:
        verify: ssl.SSLContext | bool = True
        if self._ca:
            verify = ssl.create_default_context(cafile=self._ca)
        return httpx.Client(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout),
            verify=verify,
        )


def _messages_from_rendered(rendered_request: Any) -> list[dict[str, str]]:
    if not isinstance(rendered_request, Mapping):
        raise CompatibleProviderError("provider_invalid_response", retryable=False)

    raw_messages = rendered_request.get("messages")
    if isinstance(raw_messages, list):
        messages: list[dict[str, str]] = []
        for item in raw_messages:
            if not isinstance(item, Mapping):
                raise CompatibleProviderError(
                    "provider_invalid_response", retryable=False
                )
            role = item.get("role")
            content = item.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(
                content, str
            ):
                raise CompatibleProviderError(
                    "provider_invalid_response", retryable=False
                )
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
    raise CompatibleProviderError("provider_invalid_response", retryable=False)


def _error_for_status(status_code: int) -> CompatibleProviderError | None:
    if 200 <= status_code < 300:
        return None
    if status_code in {401, 403}:
        return CompatibleProviderError("provider_auth_failed", retryable=False)
    if status_code == 429:
        return CompatibleProviderError("provider_rate_limited", retryable=True)
    if status_code in {408, 504}:
        return CompatibleProviderError("provider_timeout", retryable=True)
    if status_code in {500, 502, 503}:
        return CompatibleProviderError("provider_service_error", retryable=True)
    return CompatibleProviderError("provider_invalid_response", retryable=False)


def _config_string(config: Any, field_name: str) -> str:
    value = getattr(config, field_name, None)
    if not isinstance(value, str) or not value.strip():
        raise CompatibleProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _config_https_url(config: Any, field_name: str) -> str:
    value = _config_string(config, field_name)
    try:
        url = httpx.URL(value)
    except (TypeError, ValueError):
        raise CompatibleProviderError(
            "provider_invalid_response", retryable=False
        ) from None
    if (
        url.scheme != "https"
        or not url.host
        or url.username
        or url.password
        or url.fragment
    ):
        raise CompatibleProviderError("provider_invalid_response", retryable=False)
    return str(url)


def _optional_config_string(config: Any, field_name: str) -> str | None:
    value = getattr(config, field_name, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CompatibleProviderError("provider_invalid_response", retryable=False)
    return value.strip()


def _config_timeout(config: Any) -> float:
    value = getattr(config, "timeout_seconds", None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CompatibleProviderError("provider_invalid_response", retryable=False)
    timeout = float(value)
    if not 1.0 <= timeout <= 300.0:
        raise CompatibleProviderError("provider_invalid_response", retryable=False)
    return timeout


def _close_quietly(resource: Any) -> None:
    try:
        resource.close()
    except Exception:
        pass
