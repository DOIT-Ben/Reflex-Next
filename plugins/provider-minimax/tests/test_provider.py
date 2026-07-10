from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_minimax import plugin
from reflex_provider_minimax.provider import MiniMaxProvider, MiniMaxProviderError


FIXTURES = Path(__file__).parent / "fixtures"
STREAM_BYTES = (FIXTURES / "stream_success.jsonl").read_bytes()
JSON_BYTES = (FIXTURES / "json_success.json").read_bytes()
PRIVATE_SENTINEL = "fixture-private-credential"


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
