"""Strict OpenAI-compatible Provider adapter with no vendor SDK dependency."""
from __future__ import annotations

import ssl
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_minimax.provider import MiniMaxProviderError, _error_for_status, _messages_from_rendered
from reflex_provider_minimax.sse import SseProtocolError, extract_json_content, iter_content_chunks

SPECS = {
    "deepseek": ("DeepSeek", "deepseek-chat", ("deepseek-chat", "deepseek-reasoner"), "https://api.deepseek.com/chat/completions"),
    "qwen": ("通义千问", "qwen-turbo", ("qwen-turbo", "qwen-plus", "qwen-max"), "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
    "zhipu": ("智谱 GLM", "glm-4.5-air", ("glm-4.5-air", "glm-4.7"), "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
    "siliconflow": ("SiliconFlow", "deepseek-ai/DeepSeek-V3", ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"), "https://api.siliconflow.cn/v1/chat/completions"),
}

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
    def create(self, secret: str, config: Any): return CompatibleProvider(self, secret, config)

def factory(provider_id: str) -> CompatibleFactory:
    name, model, models, base_url = SPECS[provider_id]
    return CompatibleFactory(provider_id, name, model, models, base_url)

class CompatibleProvider:
    def __init__(self, spec: CompatibleFactory, secret: str, config: Any, *, transport: httpx.BaseTransport | None = None):
        self.id, self.model = spec.id, getattr(config, "model", "")
        self._models, self._secret = spec.models, secret.strip() if isinstance(secret, str) else ""
        self._url, self._timeout = getattr(config, "base_url", ""), getattr(config, "timeout_seconds", 0)
        self._ca = getattr(config, "ca_bundle_path", None)
        self._transport = transport
        if not self._secret or self.model not in self._models or not isinstance(self._url, str) or not self._url.startswith("https://") or not isinstance(self._timeout, (int, float)):
            raise MiniMaxProviderError("provider_invalid_response", retryable=False)
    def __repr__(self): return f"CompatibleProvider(id={self.id!r}, model={self.model!r})"
    def stream(self, rendered_request: Any, request: OptimizeRequest, cancellation: CancellationToken) -> Iterable[str]:
        if cancellation.is_cancelled: return
        model = request.model or self.model
        if model not in self._models: raise MiniMaxProviderError("provider_invalid_response", retryable=False)
        payload = {"model": model, "messages": _messages_from_rendered(rendered_request), "stream": request.stream}
        verify: ssl.SSLContext | bool = ssl.create_default_context(cafile=self._ca) if self._ca else True
        try:
            with httpx.Client(transport=self._transport, timeout=httpx.Timeout(float(self._timeout)), verify=verify) as client:
                with client.stream("POST", self._url, headers={"Authorization": f"Bearer {self._secret}", "Accept": "application/json, text/event-stream"}, json=payload) as response:
                    error = _error_for_status(response.status_code)
                    if error: raise error
                    if "application/json" in response.headers.get("content-type", "").lower():
                        content = extract_json_content(response.json())
                        if content: yield content
                        return
                    for content in iter_content_chunks(response.iter_lines()):
                        if cancellation.is_cancelled: return
                        yield content
        except MiniMaxProviderError: raise
        except httpx.TimeoutException: raise MiniMaxProviderError("provider_timeout", retryable=True) from None
        except httpx.NetworkError: raise MiniMaxProviderError("provider_network_error", retryable=True) from None
        except (httpx.HTTPError, OSError, ValueError, SseProtocolError): raise MiniMaxProviderError("provider_invalid_response", retryable=False) from None
