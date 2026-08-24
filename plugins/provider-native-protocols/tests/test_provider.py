from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_native_protocols import anthropic, gemini
from reflex_provider_native_protocols.provider import (
    AnthropicProvider,
    GeminiProvider,
    NativeProviderError,
)



PRIVATE_SECRET = "fixture-private-provider-credential"
PRIVATE_RESPONSE = "private-provider-response"


def anthropic_basic_stream(*, include_unknown=False):
    events = [
        'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_fixture","type":"message","role":"assistant","content":[],"model":"claude-sonnet-4-20250514","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":11,"output_tokens":1}}}\n\n',
        'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
        'event: ping\ndata: {"type":"ping"}\n\n',
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"first"}}\n\n',
    ]
    if include_unknown:
        events.append(
            'event: future_event\ndata: {"type":"future_event","value":"ignored"}\n\n'
        )
    events.extend(
        [
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"second"}}\n\n',
            'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
            'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},"usage":{"output_tokens":6}}\n\n',
            'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
    )
    return "".join(events).encode()


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


def rendered_request():
    return {
        "messages": [
            {"role": "system", "content": "仅返回最终文本"},
            {"role": "user", "content": "一段待优化内容"},
        ]
    }


def test_anthropic_model_discovery_uses_official_models_endpoint_and_headers():
    factory = anthropic()
    captured = []

    def handler(req):
        captured.append(req)
        return httpx.Response(
            200,
            json={"data": [{"type": "model", "id": "claude-z"}, {"type": "model", "id": "claude-a"}]},
        )

    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
    )

    assert provider.list_models() == ("claude-a", "claude-z")
    assert captured[0].url == httpx.URL("https://api.anthropic.com/v1/models")
    assert captured[0].headers["x-api-key"] == PRIVATE_SECRET
    assert captured[0].headers["anthropic-version"] == "2023-06-01"


@pytest.mark.parametrize("build", (anthropic, gemini))
def test_factories_expose_fixed_native_protocol_catalogs(build):
    factory = build()

    assert factory.id in {"anthropic", "gemini"}
    assert factory.default_model in factory.models
    assert factory.default_base_url.startswith("https://")
    assert factory.permissions == ("network",)


def test_anthropic_messages_request_and_stream_are_mapped_without_secret_leakage():
    factory = anthropic()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "request-id": "req_fixture"},
            content=anthropic_basic_stream(),
        )

    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    assert list(
        provider.stream(rendered_request(), optimize_request(factory), CancellationToken())
    ) == ["first", "second"]
    assert len(captured) == 1
    assert captured[0].url == factory.default_base_url
    assert captured[0].headers["x-api-key"] == PRIVATE_SECRET
    assert captured[0].headers["anthropic-version"] == "2023-06-01"
    assert json.loads(captured[0].content) == {
        "model": factory.default_model,
        "max_tokens": 4096,
        "system": "仅返回最终文本",
        "messages": [{"role": "user", "content": "一段待优化内容"}],
        "stream": True,
    }
    assert PRIVATE_SECRET not in repr(provider)


def test_anthropic_stream_events_preserve_official_lifecycle_metadata_and_usage():
    factory = anthropic()
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={
                    "content-type": "text/event-stream",
                    "request-id": "req_fixture",
                },
                content=anthropic_basic_stream(include_unknown=True),
            )
        ),
    )

    events = list(
        provider.stream_events(
            rendered_request(), optimize_request(factory), CancellationToken()
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "usage",
        "text_delta",
        "text_delta",
        "usage",
        "completed",
    ]
    assert events[0].data == {
        "provider": "anthropic",
        "model": factory.default_model,
        "protocol": "anthropic_messages",
        "response_id": "msg_fixture",
        "request_id": "req_fixture",
    }
    assert events[1].data == {"input_tokens": 11, "output_tokens": 1}
    assert events[4].data == {"output_tokens": 6}
    assert events[-1].data == {
        "finish_reason": "end_turn",
        "response_id": "msg_fixture",
        "request_id": "req_fixture",
    }


def test_anthropic_non_stream_events_preserve_response_and_cumulative_usage():
    factory = anthropic()
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json", "request-id": "req_json"},
                json={
                    "id": "msg_json",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "complete"}],
                    "model": factory.default_model,
                    "stop_reason": "max_tokens",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 10,
                        "cache_read_input_tokens": 3,
                        "output_tokens": 7,
                    },
                },
            )
        ),
    )

    events = list(
        provider.stream_events(
            rendered_request(),
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "usage",
        "text_delta",
        "completed",
    ]
    assert events[1].data == {
        "input_tokens": 10,
        "cache_read_input_tokens": 3,
        "output_tokens": 7,
    }
    assert events[-1].data["finish_reason"] == "max_tokens"


def test_anthropic_stream_refusal_is_completed_without_text_delta():
    factory = anthropic()
    refusal = b"".join(
        [
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_refusal","type":"message","role":"assistant","content":[],"model":"claude-sonnet-4-20250514","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":20,"output_tokens":1}}}\n\n',
            b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
            b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
            b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"refusal","stop_sequence":null,"stop_details":{"type":"refusal","category":"policy"}},"usage":{"output_tokens":0}}\n\n',
            b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        ]
    )
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=refusal
            )
        ),
    )

    events = list(
        provider.stream_events(
            rendered_request(), optimize_request(factory), CancellationToken()
        )
    )

    assert not [event for event in events if event.kind == "text_delta"]
    assert events[-1].kind == "completed"
    assert events[-1].data["finish_reason"] == "refusal"
    assert events[-1].data["stop_details"] == {
        "type": "refusal",
        "category": "policy",
    }


def test_anthropic_http_200_error_event_is_typed_and_terminates():
    factory = anthropic()
    content = b"".join(
        [
            b'event: message_start\ndata: {"type":"message_start","message":{"id":"msg_error","type":"message","role":"assistant","content":[],"model":"claude-sonnet-4-20250514","stop_reason":null,"stop_sequence":null,"usage":{"input_tokens":4,"output_tokens":1}}}\n\n',
            b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"private details"}}\n\n',
        ]
    )
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "text/event-stream", "request-id": "req_error"},
                content=content,
            )
        ),
    )

    events = list(
        provider.stream_events(
            rendered_request(), optimize_request(factory), CancellationToken()
        )
    )

    assert events[-1].kind == "error"
    assert events[-1].data == {
        "code": "provider_service_error",
        "retryable": True,
        "provider_error_type": "overloaded_error",
        "request_id": "req_error",
    }
    assert PRIVATE_RESPONSE not in repr(events[-1])


def test_anthropic_eof_without_message_stop_is_an_error():
    factory = anthropic()
    truncated = anthropic_basic_stream().replace(
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n', b""
    )
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, content=truncated
            )
        ),
    )

    events = list(
        provider.stream_events(
            rendered_request(), optimize_request(factory), CancellationToken()
        )
    )

    assert events[-1].kind == "error"
    assert events[-1].data == {
        "code": "provider_invalid_response",
        "retryable": False,
    }


def test_gemini_generate_content_request_and_stream_are_mapped_without_secret_leakage():
    factory = gemini()
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        content = b"".join(
            [
                b'data: {"candidates":[{"content":{"parts":[{"text":"first"}]}}]}\n\n',
                b'data: {"candidates":[{"content":{"parts":[{"text":"second"}]},"finishReason":"STOP"}]}\n\n',
            ]
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=content)

    provider = GeminiProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    assert list(
        provider.stream(rendered_request(), optimize_request(factory), CancellationToken())
    ) == ["first", "second"]
    assert len(captured) == 1
    assert captured[0].url.path.endswith(
        f"/models/{factory.default_model}:streamGenerateContent"
    )
    assert captured[0].url.params["alt"] == "sse"
    assert captured[0].headers["x-goog-api-key"] == PRIVATE_SECRET
    assert json.loads(captured[0].content) == {
        "systemInstruction": {"parts": [{"text": "仅返回最终文本"}]},
        "contents": [{"role": "user", "parts": [{"text": "一段待优化内容"}]}],
    }
    assert PRIVATE_SECRET not in repr(provider)


def test_anthropic_messages_non_streaming_response_is_parsed():
    factory = anthropic()
    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "id": "msg_non_stream",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "complete"}],
                    "model": factory.default_model,
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            )
        ),
    )

    assert list(
        provider.stream(
            rendered_request(),
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    ) == ["complete"]


def test_gemini_generate_content_non_streaming_response_is_parsed():
    factory = gemini()
    provider = GeminiProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "candidates": [
                        {"content": {"parts": [{"text": "complete"}]}, "finishReason": "STOP"}
                    ]
                },
            )
        ),
    )

    assert list(
        provider.stream(
            rendered_request(),
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    ) == ["complete"]


def test_anthropic_second_catalog_model_is_sent_in_messages_payload():
    factory = anthropic()
    selected_model = factory.models[1]
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "msg_second_model",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "complete"}],
                "model": selected_model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
    )

    assert list(
        provider.stream(
            rendered_request(),
            optimize_request(factory, stream=False, model=selected_model),
            CancellationToken(),
        )
    ) == ["complete"]
    assert json.loads(captured[0].content)["model"] == selected_model


def test_gemini_second_catalog_model_is_sent_in_generate_content_url():
    factory = gemini()
    selected_model = factory.models[1]
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"candidates": [{"content": {"parts": [{"text": "complete"}]}}]},
        )

    provider = GeminiProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
    )

    assert list(
        provider.stream(
            rendered_request(),
            optimize_request(factory, stream=False, model=selected_model),
            CancellationToken(),
        )
    ) == ["complete"]
    assert captured[0].url.path.endswith(f"/models/{selected_model}:generateContent")


def test_retryable_native_failure_reuses_one_idempotency_key_then_succeeds():
    factory = anthropic()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "id": "msg_recovered",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "recovered"}],
                "model": factory.default_model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    provider = AnthropicProvider(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )

    assert list(
        provider.stream(
            rendered_request(),
            optimize_request(factory, stream=False),
            CancellationToken(),
        )
    ) == ["recovered"]
    assert len(requests) == 2
    assert requests[0].headers["idempotency-key"] == requests[1].headers["idempotency-key"]


@pytest.mark.parametrize(
    ("build", "provider_type"),
    ((anthropic, AnthropicProvider), (gemini, GeminiProvider)),
)
def test_native_protocols_map_auth_errors_without_echoing_server_or_secret(build, provider_type):
    factory = build()
    provider = provider_type(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(401, content=PRIVATE_RESPONSE.encode())
        ),
        sleep=lambda _: None,
    )

    with pytest.raises(NativeProviderError) as caught:
        list(provider.stream(rendered_request(), optimize_request(factory), CancellationToken()))

    assert caught.value.code == "provider_auth_failed"
    assert caught.value.retryable is False
    assert PRIVATE_SECRET not in str(caught.value)
    assert PRIVATE_RESPONSE not in repr(caught.value)


@pytest.mark.parametrize(
    ("build", "provider_type"),
    ((anthropic, AnthropicProvider), (gemini, GeminiProvider)),
)
def test_cancelled_native_protocol_request_never_opens_network(build, provider_type):
    factory = build()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider = provider_type(
        factory,
        PRIVATE_SECRET,
        provider_config(factory),
        transport=httpx.MockTransport(handler),
    )
    cancellation = CancellationToken()
    cancellation.cancel()

    assert list(provider.stream(rendered_request(), optimize_request(factory), cancellation)) == []
    assert calls == 0
