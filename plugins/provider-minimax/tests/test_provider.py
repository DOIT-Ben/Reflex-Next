from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest, ProviderEvent
from reflex_provider_minimax import plugin
from reflex_provider_minimax import provider as provider_module
from reflex_provider_minimax.provider import MiniMaxProvider, MiniMaxProviderError


FIXTURES = Path(__file__).parent / "fixtures"
STREAM_BYTES = (FIXTURES / "stream_success.jsonl").read_bytes()
JSON_BYTES = (FIXTURES / "json_success.json").read_bytes()
PRIVATE_SENTINEL = "fixture-private-credential"


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


def provider_config(**overrides):
    values = {
        "model": "MiniMax-M2.7-highspeed",
        "base_url": "https://api.example.test/v1/chat/completions",
        "timeout_seconds": 10.0,
        "tls_verify": True,
        "ca_bundle_path": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def request(*, stream=True, model="MiniMax-M2.7-highspeed"):
    return OptimizeRequest(text="一段待优化内容", stream=stream, provider="minimax", model=model)


def test_factory_metadata_and_create_contract():
    factory = plugin()

    assert factory.id == "minimax"
    assert factory.default_model == "MiniMax-M2.7-highspeed"
    assert factory.default_model in factory.models
    assert factory.required_secret == "api_key"
    assert factory.permissions == ("network",)
    assert isinstance(factory.create(PRIVATE_SENTINEL, provider_config()), MiniMaxProvider)


def test_stream_maps_request_and_yields_incremental_content_without_repr_leakage():
    captured: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured.append(http_request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=STREAM_BYTES,
        )

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    chunks = list(
        provider.stream(
            {"system": "仅返回结果", "user": "一段待优化内容"},
            request(),
            CancellationToken(),
        )
    )

    assert chunks == ["第一段", "第二段"]
    assert len(captured) == 1
    assert captured[0].headers["Authorization"] == f"Bearer {PRIVATE_SENTINEL}"
    payload = json.loads(captured[0].content)
    assert payload == {
        "model": "MiniMax-M2.7-highspeed",
        "messages": [
            {"role": "system", "content": "仅返回结果"},
            {"role": "user", "content": "一段待优化内容"},
        ],
        "stream": True,
    }
    assert PRIVATE_SENTINEL not in repr(provider)


def test_stream_events_exposes_core_provider_event_contract():
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=STREAM_BYTES,
            )
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, request(), CancellationToken()
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "text_delta",
        "text_delta",
        "completed",
    ]
    assert all(isinstance(event, ProviderEvent) for event in events)


def test_stream_events_reports_the_effective_request_model(monkeypatch):
    override_model = "fixture-model-override"
    monkeypatch.setattr(
        provider_module,
        "SUPPORTED_MODELS",
        (provider_module.DEFAULT_MODEL, override_model),
    )
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=STREAM_BYTES,
            )
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"},
            request(model=override_model),
            CancellationToken(),
        )
    )

    assert events[0].data["model"] == override_model


def test_stream_accepts_minimax_finish_reason_without_done_marker():
    content = (
        b'data: {"choices":[{"delta":{"content":"first"},"index":0}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"last"},"finish_reason":"stop","index":0}]}\n\n'
    )
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=content,
            )
        ),
    )

    assert list(
        provider.stream({"text": "input"}, request(), CancellationToken())
    ) == ["first", "last"]


def test_stream_filters_thought_blocks_across_content_chunks():
    content = (
        b'data: {"choices":[{"delta":{"content":"<thi"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"nk>private reasoning"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"</thi"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"nk>\\n\\nFinal result"},"finish_reason":"stop"}]}\n\n'
    )
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=content,
            )
        ),
    )

    chunks = list(provider.stream({"text": "input"}, request(), CancellationToken()))

    assert "".join(chunks) == "Final result"
    assert "private reasoning" not in "".join(chunks)


def test_stream_preserves_visible_content_around_fenced_thought_block():
    content = (
        b'data: {"choices":[{"delta":{"content":"Before ```thi"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"nk\\nprivate\\n```After"},"finish_reason":"stop"}]}\n\n'
    )
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=content,
            )
        ),
    )

    assert "".join(
        provider.stream({"text": "input"}, request(), CancellationToken())
    ) == "Before After"


def test_complete_json_response_is_supported():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=JSON_BYTES,
        )
    )
    provider = MiniMaxProvider(PRIVATE_SENTINEL, provider_config(), transport=transport)

    assert list(
        provider.stream(
            {"text": "一段待优化内容"},
            request(stream=False),
            CancellationToken(),
        )
    ) == ["完整结果"]


def test_complete_json_response_filters_thought_block():
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "choices": [
                    {"message": {"content": "<think>private</think>\n\n完整结果"}}
                ]
            },
        )
    )
    provider = MiniMaxProvider(PRIVATE_SENTINEL, provider_config(), transport=transport)

    assert list(
        provider.stream(
            {"text": "一段待优化内容"},
            request(stream=False),
            CancellationToken(),
        )
    ) == ["完整结果"]


def test_json_and_sse_response_limits_are_enforced_before_success(monkeypatch):
    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 64)
    oversized_json = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b'{"choices":[{"message":{"content":"' + b"x" * 100 + b'"}}]}',
            )
        ),
        sleep=lambda _: None,
    )
    with pytest.raises(MiniMaxProviderError) as caught:
        list(
            oversized_json.stream(
                {"text": "input"}, request(stream=False), CancellationToken()
            )
        )
    assert caught.value.code == "provider_invalid_response"

    monkeypatch.setattr(provider_module, "MAX_RESPONSE_BYTES", 2048)
    monkeypatch.setattr(provider_module, "MAX_STREAM_EVENTS", 1)
    too_many_events = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    b'data: {"choices":[{"delta":{"content":"one"}}]}\n\n'
                    b'data: {"choices":[{"delta":{"content":"two"}}]}\n\n'
                    b"data: [DONE]\n\n"
                ),
            )
        ),
        sleep=lambda _: None,
    )
    stream = too_many_events.stream(
        {"text": "input"}, request(), CancellationToken()
    )
    assert next(stream) == "one"
    with pytest.raises(MiniMaxProviderError) as caught:
        list(stream)
    assert caught.value.code == "provider_invalid_response"


@pytest.mark.parametrize(
    "content",
    [
        b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n',
        b"data: \xff\n\n",
    ],
)
def test_truncated_or_invalid_utf8_stream_is_a_safe_protocol_error(content):
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=content,
            )
        ),
        sleep=lambda _: None,
    )
    stream = provider.stream({"text": "input"}, request(), CancellationToken())
    if b"partial" in content:
        assert next(stream) == "partial"
    with pytest.raises(MiniMaxProviderError) as caught:
        list(stream)
    assert caught.value.code == "provider_invalid_response"


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "provider_auth_failed", False),
        (403, "provider_auth_failed", False),
        (429, "provider_rate_limited", True),
        (500, "provider_service_error", True),
        (400, "provider_invalid_response", False),
    ],
)
def test_http_statuses_map_to_safe_codes(status, code, retryable):
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, content=b'{"private":"response-body"}')

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(MiniMaxProviderError) as caught:
        list(provider.stream({"text": "input"}, request(), CancellationToken()))

    assert caught.value.code == code
    assert caught.value.retryable is retryable
    assert attempts == (3 if retryable else 1)
    assert PRIVATE_SENTINEL not in str(caught.value)
    assert "response-body" not in repr(caught.value)


def test_retries_transient_failures_before_first_content_then_succeeds():
    attempts = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=STREAM_BYTES)

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
    )

    assert list(provider.stream({"text": "input"}, request(), CancellationToken())) == [
        "第一段",
        "第二段",
    ]
    assert attempts == 3
    assert sleeps == [0.25, 0.5]


def test_does_not_retry_after_the_first_content_chunk():
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                b'data: {private-invalid-json\n\n'
            ),
        )

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    stream = provider.stream({"text": "input"}, request(), CancellationToken())

    assert next(stream) == "first"
    with pytest.raises(MiniMaxProviderError) as caught:
        list(stream)

    assert caught.value.code == "provider_invalid_response"
    assert attempts == 1


def test_cancellation_before_send_avoids_the_network_and_after_first_chunk_stops_iteration():
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=STREAM_BYTES)

    provider = MiniMaxProvider(PRIVATE_SENTINEL, provider_config(), transport=httpx.MockTransport(handler))
    cancelled = CancellationToken()
    cancelled.cancel()
    assert list(provider.stream({"text": "input"}, request(), cancelled)) == []
    assert attempts == 0

    token = CancellationToken()
    stream = provider.stream({"text": "input"}, request(), token)
    assert next(stream) == "第一段"
    token.cancel()
    assert list(stream) == []
    assert attempts == 1


def test_cancellation_closes_a_blocked_response_without_yielding_late_content():
    blocked = BlockingByteStream(
        b'data: {"choices":[{"delta":{"content":"late-private-content"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=blocked,
            )
        ),
    )
    token = CancellationToken()
    chunks: list[str] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            chunks.extend(provider.stream({"text": "input"}, request(), token))
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
    token = ObservedCancellationToken()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
    )
    chunks: list[str] = []
    thread = Thread(
        target=lambda: chunks.extend(
            provider.stream({"text": "input"}, request(), token)
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


def test_empty_successful_response_is_a_stable_error_without_retry():
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"data: [DONE]\n\n")

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(MiniMaxProviderError) as caught:
        list(provider.stream({"text": "input"}, request(), CancellationToken()))

    assert caught.value.code == "provider_empty_response"
    assert attempts == 1


@pytest.mark.parametrize(
    ("raised", "code"),
    [
        (httpx.ConnectError("private network detail"), "provider_network_error"),
        (httpx.ReadTimeout("private timeout detail"), "provider_timeout"),
    ],
)
def test_transport_errors_map_without_raw_details(raised, code):
    def handler(request: httpx.Request) -> httpx.Response:
        raised.request = request
        raise raised

    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    with pytest.raises(MiniMaxProviderError) as caught:
        list(provider.stream({"text": "input"}, request(), CancellationToken()))

    assert caught.value.code == code
    assert "private" not in str(caught.value)


def test_missing_ca_bundle_maps_to_safe_error_without_path_leakage():
    private_path = r"C:\private-provider-config\missing-ca.pem"
    provider = MiniMaxProvider(
        PRIVATE_SENTINEL,
        provider_config(ca_bundle_path=private_path),
    )

    with pytest.raises(MiniMaxProviderError) as caught:
        list(provider.stream({"text": "input"}, request(), CancellationToken()))

    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert private_path not in str(caught.value)
    assert private_path not in repr(caught.value)
