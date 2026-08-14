from __future__ import annotations

import json
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_openai_compatible import deepseek, qwen, siliconflow, zhipu
from reflex_provider_openai_compatible import provider as provider_module
from reflex_provider_openai_compatible.provider import (
    CompatibleProvider,
    CompatibleProviderError,
)


FACTORIES = (deepseek, qwen, zhipu, siliconflow)
PRIVATE_SENTINEL = "fixture-private-credential"
PRIVATE_RESPONSE = "private-response-body"


class BlockingByteStream(httpx.SyncByteStream):
    def __init__(self, late_content: bytes) -> None:
        self.started = Event()
        self.closed = Event()
        self.close_calls = 0
        self._late_content = late_content

    def __iter__(self):
        self.started.set()
        assert self.closed.wait(5.0)
        yield self._late_content

    def close(self) -> None:
        self.close_calls += 1
        self.closed.set()


class ObservedCancellationToken(CancellationToken):
    def __init__(self) -> None:
        super().__init__()
        self.waiting = Event()

    def wait(self, timeout: float | None = None) -> bool:
        self.waiting.set()
        return super().wait(timeout)


def provider_config(factory, **overrides):
    values = {
        "model": factory.default_model,
        "base_url": factory.default_base_url,
        "timeout_seconds": 10.0,
        "tls_verify": True,
        "ca_bundle_path": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def optimize_request(factory, *, stream=True, model=None):
    return OptimizeRequest(
        text="一段待优化内容",
        stream=stream,
        provider=factory.id,
        model=model or factory.default_model,
    )


def sse(*contents: str, done: bool = True) -> bytes:
    events = [
        f'data: {json.dumps({"choices": [{"delta": {"content": content}}]}, ensure_ascii=False)}\n\n'
        for content in contents
    ]
    if done:
        events.append("data: [DONE]\n\n")
    return "".join(events).encode()


def build_provider(factory, handler, *, sleeps=None):
    return CompatibleProvider(
        factory,
        PRIVATE_SENTINEL,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
        sleep=(sleeps.append if sleeps is not None else lambda _: None),
    )


def test_model_discovery_uses_official_models_endpoint_and_authentication():
    factory = deepseek()
    captured = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"data": [{"id": "model-z"}, {"id": "model-a"}]})

    provider = build_provider(factory, handler)

    assert provider.list_models() == ("model-a", "model-z")
    assert captured[0].url == httpx.URL("https://api.deepseek.com/models")
    assert captured[0].headers["Authorization"] == f"Bearer {PRIVATE_SENTINEL}"


@pytest.mark.parametrize("build", FACTORIES)
def test_factory_has_a_fixed_safe_contract(build):
    factory = build()

    assert factory.id in {"deepseek", "qwen", "zhipu", "siliconflow"}
    assert factory.default_model in factory.models
    assert factory.default_base_url.startswith("https://")
    assert isinstance(
        factory.create(PRIVATE_SENTINEL, provider_config(factory)),
        CompatibleProvider,
    )


def test_stream_maps_openai_request_and_does_not_leak_secret():
    factory = deepseek()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("第一段", "第二段"),
        )

    provider = build_provider(factory, handler)
    chunks = list(
        provider.stream(
            {"system": "仅返回结果", "user": "一段待优化内容"},
            optimize_request(factory),
            CancellationToken(),
        )
    )

    assert chunks == ["第一段", "第二段"]
    assert len(captured) == 1
    assert captured[0].headers["Authorization"] == f"Bearer {PRIVATE_SENTINEL}"
    assert captured[0].headers["Idempotency-Key"]
    assert json.loads(captured[0].content) == {
        "model": factory.default_model,
        "messages": [
            {"role": "system", "content": "仅返回结果"},
            {"role": "user", "content": "一段待优化内容"},
        ],
        "stream": True,
    }
    assert PRIVATE_SENTINEL not in repr(provider)


def test_complete_json_response_is_supported():
    factory = qwen()
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": "完整结果"}}]},
        ),
    )

    assert list(
        provider.stream(
            {"text": "一段待优化内容"},
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    ) == ["完整结果"]


def test_stream_events_map_official_chat_completion_chunks_and_usage():
    factory = deepseek()
    response_id = "chatcmpl-contract-1"
    payloads = [
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": "第一段"}, "finish_reason": None}],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {"content": "第二段"}, "finish_reason": "length"}],
        },
        {
            "id": response_id,
            "object": "chat.completion.chunk",
            "choices": [],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        },
    ]
    body = b"".join(
        f"data: {json.dumps(payload)}\n\n".encode() for payload in payloads
    ) + b"data: [DONE]\n\n"
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=body,
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, optimize_request(factory), CancellationToken()
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "text_delta",
        "text_delta",
        "usage",
        "completed",
    ]
    assert events[0].data == {
        "provider": factory.id,
        "model": factory.default_model,
        "protocol": "openai_chat_completions",
        "response_id": response_id,
    }
    assert [events[1].data["text"], events[2].data["text"]] == ["第一段", "第二段"]
    assert events[3].data == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert events[4].data == {
        "finish_reason": "length",
        "response_id": response_id,
    }


def test_stream_events_map_non_stream_chat_completion_metadata():
    factory = qwen()
    response_id = "chatcmpl-contract-2"
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": response_id,
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "完整结果"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"},
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "text_delta",
        "usage",
        "completed",
    ]
    assert events[0].data["response_id"] == response_id
    assert events[1].data == {"text": "完整结果"}
    assert events[2].data == {
        "input_tokens": 5,
        "output_tokens": 3,
        "total_tokens": 8,
    }
    assert events[3].data == {
        "finish_reason": "stop",
        "response_id": response_id,
    }


def test_safe_custom_model_id_is_forwarded_without_a_static_allowlist():
    factory = deepseek()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    custom_model = "gpt-5.6-luna"
    provider = CompatibleProvider(
        factory,
        PRIVATE_SENTINEL,
        provider_config(factory, model=custom_model),
        transport=httpx.MockTransport(handler),
    )

    assert list(
        provider.stream(
            {"text": "input"},
            optimize_request(factory, stream=False, model=custom_model),
            CancellationToken(),
        )
    ) == ["ok"]
    assert json.loads(captured[0].content)["model"] == custom_model


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "http://api.example.test"},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"tls_verify": False},
        {"ca_bundle_path": 42},
    ],
)
def test_rejects_invalid_configuration_before_network(overrides):
    factory = zhipu()

    with pytest.raises(CompatibleProviderError) as caught:
        CompatibleProvider(
            factory,
            PRIVATE_SENTINEL,
            provider_config(factory, **overrides),
        )

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False


def test_rejects_empty_secret_as_authentication_error():
    factory = deepseek()

    with pytest.raises(CompatibleProviderError) as caught:
        CompatibleProvider(factory, "  ", provider_config(factory))

    assert caught.value.code == "provider_auth_failed"
    assert caught.value.retryable is False


@pytest.mark.parametrize(
    ("status", "code", "retryable", "attempts"),
    [
        (401, "provider_auth_failed", False, 1),
        (403, "provider_auth_failed", False, 1),
        (408, "provider_timeout", True, 3),
        (429, "provider_rate_limited", True, 3),
        (500, "provider_service_error", True, 3),
        (502, "provider_service_error", True, 3),
        (503, "provider_service_error", True, 3),
        (504, "provider_timeout", True, 3),
        (501, "provider_invalid_response", False, 1),
        (400, "provider_invalid_response", False, 1),
    ],
)
def test_http_statuses_map_to_safe_codes(status, code, retryable, attempts):
    factory = deepseek()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, content=PRIVATE_RESPONSE.encode())

    provider = build_provider(factory, handler)

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert calls == attempts
    assert PRIVATE_SENTINEL not in str(caught.value)
    assert PRIVATE_RESPONSE not in repr(caught.value)


def test_retries_only_before_content_with_stable_idempotency_key():
    factory = siliconflow()
    calls = 0
    keys: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        keys.append(request.headers["Idempotency-Key"])
        if calls < 3:
            return httpx.Response(503)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("成功"),
        )

    provider = build_provider(factory, handler, sleeps=sleeps)

    assert list(
        provider.stream(
            {"text": "input"},
            optimize_request(factory),
            CancellationToken(),
        )
    ) == ["成功"]
    assert calls == 3
    assert len(set(keys)) == 1
    assert sleeps == [0.25, 0.5]


def test_does_not_retry_after_first_content_when_stream_breaks():
    factory = deepseek()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("first", done=False),
        )

    provider = build_provider(factory, handler)
    stream = provider.stream(
        {"text": "input"}, optimize_request(factory), CancellationToken()
    )

    assert next(stream) == "first"
    with pytest.raises(CompatibleProviderError) as caught:
        list(stream)

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert calls == 1


def test_finish_reason_is_accepted_as_a_terminal_stream_event_without_done_marker():
    factory = deepseek()
    terminal = json.dumps(
        {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    )
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("complete", done=False) + f"data: {terminal}\n\n".encode(),
        ),
    )

    assert list(
        provider.stream(
            {"text": "input"}, optimize_request(factory), CancellationToken()
        )
    ) == ["complete"]


def test_cancellation_during_retry_backoff_prevents_the_next_request():
    factory = deepseek()
    token = CancellationToken()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    def cancel_during_sleep(_: float) -> None:
        token.cancel()

    provider = CompatibleProvider(
        factory,
        PRIVATE_SENTINEL,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
        sleep=cancel_during_sleep,
    )

    assert list(
        provider.stream({"text": "input"}, optimize_request(factory), token)
    ) == []
    assert calls == 1


@pytest.mark.parametrize(
    ("exception_type", "code"),
    [
        (httpx.ConnectError, "provider_network_error"),
        (httpx.ReadTimeout, "provider_timeout"),
    ],
)
def test_transport_errors_are_retryable_and_do_not_expose_raw_details(
    exception_type, code
):
    factory = qwen()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exception_type("private network detail", request=request)

    provider = build_provider(factory, handler)

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )

    assert caught.value.code == code
    assert caught.value.retryable is True
    assert calls == 3
    assert "private" not in str(caught.value)
    assert "private" not in repr(caught.value)


def test_missing_ca_bundle_maps_to_safe_error_without_path_leakage():
    factory = qwen()
    private_path = r"C:\private-provider-config\missing-ca.pem"
    provider = CompatibleProvider(
        factory,
        PRIVATE_SENTINEL,
        provider_config(factory, ca_bundle_path=private_path),
    )

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert private_path not in str(caught.value)
    assert private_path not in repr(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"{private-invalid-json",
        ),
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"private": PRIVATE_RESPONSE},
        ),
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: {private-invalid-json\n\n",
        ),
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: \xff\n\n",
        ),
    ],
)
def test_malformed_json_and_sse_are_non_retryable_protocol_errors(response):
    factory = zhipu()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    provider = build_provider(factory, handler)

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert calls == 1
    assert PRIVATE_RESPONSE not in str(caught.value)
    assert PRIVATE_RESPONSE not in repr(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": ""}}]},
        ),
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n\n",
        ),
    ],
)
def test_empty_successful_response_has_a_stable_error_without_retry(response):
    factory = deepseek()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    provider = build_provider(factory, handler)

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )

    assert caught.value.code == "provider_empty_response"
    assert caught.value.retryable is False
    assert calls == 1


def test_json_response_size_is_bounded(monkeypatch):
    factory = deepseek()
    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 64)
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"choices": [{"message": {"content": "x" * 100}}]},
        ),
    )

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            provider.stream(
                {"text": "input"},
                optimize_request(factory, stream=False),
                CancellationToken(),
            )
        )

    assert caught.value.code == "provider_invalid_response"


def test_sse_response_size_and_event_count_are_bounded(monkeypatch):
    factory = deepseek()
    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 128)
    oversized = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("x" * 200),
        ),
    )

    with pytest.raises(CompatibleProviderError) as caught:
        list(
            oversized.stream(
                {"text": "input"},
                optimize_request(factory),
                CancellationToken(),
            )
        )
    assert caught.value.code == "provider_invalid_response"

    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 2048)
    monkeypatch.setattr(provider_module, "MAX_STREAM_EVENTS", 1)
    too_many_events = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("one", "two"),
        ),
    )
    stream = too_many_events.stream(
        {"text": "input"}, optimize_request(factory), CancellationToken()
    )

    assert next(stream) == "one"
    with pytest.raises(CompatibleProviderError) as caught:
        list(stream)
    assert caught.value.code == "provider_invalid_response"


def test_cancellation_before_send_and_after_content_stops_cleanly():
    factory = siliconflow()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse("first", "second"),
        )

    provider = build_provider(factory, handler)
    cancelled = CancellationToken()
    cancelled.cancel()
    assert list(
        provider.stream(
            {"text": "input"}, optimize_request(factory), cancelled
        )
    ) == []
    assert calls == 0

    token = CancellationToken()
    stream = provider.stream(
        {"text": "input"}, optimize_request(factory), token
    )
    assert next(stream) == "first"
    token.cancel()
    assert list(stream) == []
    assert calls == 1


def test_cancellation_closes_a_blocked_response_without_yielding_late_content():
    factory = deepseek()
    blocked = BlockingByteStream(sse("late-private-content"))
    provider = build_provider(
        factory,
        lambda _: httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=blocked,
        ),
    )
    token = CancellationToken()
    chunks: list[str] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            chunks.extend(
                provider.stream({"text": "input"}, optimize_request(factory), token)
            )
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=consume, daemon=True)
    thread.start()
    assert blocked.started.wait(1.0)

    token.cancel()

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert blocked.close_calls >= 1
    assert chunks == []
    assert errors == []


def test_cancellation_interrupts_retry_backoff_immediately(monkeypatch):
    monkeypatch.setattr(provider_module, "RETRY_DELAYS_SECONDS", (30.0, 30.0))
    factory = deepseek()
    token = ObservedCancellationToken()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    provider = CompatibleProvider(
        factory,
        PRIVATE_SENTINEL,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
    )
    chunks: list[str] = []
    thread = Thread(
        target=lambda: chunks.extend(
            provider.stream({"text": "input"}, optimize_request(factory), token)
        ),
        daemon=True,
    )
    thread.start()
    assert token.waiting.wait(1.0)

    token.cancel()

    thread.join(timeout=1.0)
    assert not thread.is_alive()
    assert calls == 1
    assert chunks == []
