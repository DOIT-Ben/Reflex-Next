from __future__ import annotations

import json
from threading import Event, Thread
from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_openai_responses import openai_responses
from reflex_provider_openai_responses.provider import (
    ResponsesProvider,
    ResponsesProviderError,
)


class ChunkedByteStream(httpx.SyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    def __iter__(self):
        yield from self._chunks


class BlockingByteStream(httpx.SyncByteStream):
    def __init__(self) -> None:
        self.started = Event()
        self.closed = Event()

    def __iter__(self):
        self.started.set()
        assert self.closed.wait(5.0)
        return
        yield  # pragma: no cover

    def close(self) -> None:
        self.closed.set()


def config(factory, **overrides):
    values = {
        "model": factory.default_model,
        "base_url": "https://api.example.test/v1/responses",
        "timeout_seconds": 10.0,
        "ca_bundle_path": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def request(factory, stream=True):
    return OptimizeRequest(
        text="input",
        provider=factory.id,
        model=factory.default_model,
        stream=stream,
    )


def provider_with_response(factory, response):
    return ResponsesProvider(
        factory,
        "fixture-secret",
        config(factory),
        transport=httpx.MockTransport(lambda _: response),
    )


def test_model_discovery_uses_responses_sibling_models_endpoint():
    factory = openai_responses()
    captured = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"data": [{"id": "gpt-z"}, {"id": "gpt-a"}]})

    provider = ResponsesProvider(
        factory, "fixture-secret", config(factory), transport=httpx.MockTransport(handler)
    )

    assert provider.list_models() == ("gpt-a", "gpt-z")
    assert captured[0].url == httpx.URL("https://api.example.test/v1/models")


def sse(*events, ending=b"\n\n"):
    return b"\n\n".join(
        b"data: " + json.dumps(event).encode("utf-8") for event in events
    ) + ending


def test_responses_request_and_official_semantic_stream_events_are_mapped():
    factory = openai_responses()
    blocks = b"".join(
        [
            b'data: {"type":"response.created","response":{"id":"resp_1"}}\n\n',
            b'data: {"type":"response.output_text.delta","delta":"first"}\n\n',
            b'data: {"type":"response.output_text.delta","delta":"second"}\n\n',
            b'data: {"type":"response.completed","response":{"id":"resp_1","usage":{"input_tokens":3,"output_tokens":4,"total_tokens":7}}}\n\n',
        ]
    )
    captured: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        captured.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=blocks)

    provider = ResponsesProvider(factory, "fixture-secret", config(factory), transport=httpx.MockTransport(handler))
    events = list(provider.stream_events({"text": "input"}, request(factory), CancellationToken()))

    assert [event.kind for event in events] == ["request_started", "text_delta", "text_delta", "usage", "completed"]
    assert [event.data.get("text") for event in events if event.kind == "text_delta"] == ["first", "second"]
    assert events[-1].data["response_id"] == "resp_1"
    assert json.loads(captured[0].content)["input"] == [{"role": "user", "content": "input"}]


def test_request_maps_system_to_official_instructions_field():
    factory = openai_responses()
    captured: list[httpx.Request] = []

    def handler(req):
        captured.append(req)
        return httpx.Response(
            200,
            json={"id": "resp_1", "status": "completed", "output_text": "ok"},
        )

    provider = ResponsesProvider(
        factory,
        "fixture-secret",
        config(factory),
        transport=httpx.MockTransport(handler),
    )
    list(
        provider.stream_events(
            {"system": "Only answer", "user": "input"},
            request(factory, stream=False),
            CancellationToken(),
        )
    )

    payload = json.loads(captured[0].content)
    assert payload["instructions"] == "Only answer"
    assert payload["input"] == [{"role": "user", "content": "input"}]


def test_sse_accepts_crlf_arbitrary_byte_chunks_and_eof_terminal_event():
    factory = openai_responses()
    raw = (
        b': keep-alive\r\n'
        b'event: ignored\r\n'
        b'data: {"type":"response.created","response":{"id":"resp_crlf"}}\r\n\r\n'
        b'data: {"type":"response.output_item.added","item":{}}\r\n\r\n'
        b'data: {"type":"response.output_text.delta","delta":"hello"}\r\n\r\n'
        b'data: {"type":"response.completed","response":{"id":"resp_crlf"}}'
    )
    chunks = tuple(raw[index : index + 3] for index in range(0, len(raw), 3))
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=ChunkedByteStream(*chunks),
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, request(factory), CancellationToken()
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "text_delta",
        "completed",
    ]
    assert events[0].data["response_id"] == "resp_crlf"
    assert events[-1].data["response_id"] == "resp_crlf"


@pytest.mark.parametrize(
    ("reason", "finish_reason"),
    [
        ("max_output_tokens", "length"),
        ("content_filter", "content_filter"),
        ("future_reason", "incomplete"),
    ],
)
def test_stream_incomplete_preserves_usage_and_maps_finish_reason(
    reason, finish_reason
):
    factory = openai_responses()
    body = sse(
        {"type": "response.created", "response": {"id": "resp_inc"}},
        {"type": "response.output_text.delta", "delta": "partial"},
        {
            "type": "response.incomplete",
            "response": {
                "id": "resp_inc",
                "incomplete_details": {"reason": reason},
                "usage": {
                    "input_tokens": 2,
                    "output_tokens": 3,
                    "total_tokens": 5,
                },
            },
        },
    )
    provider = provider_with_response(
        factory,
        httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, request(factory), CancellationToken()
        )
    )

    assert [event.kind for event in events] == [
        "request_started",
        "text_delta",
        "usage",
        "completed",
    ]
    assert events[-1].data == {
        "finish_reason": finish_reason,
        "response_id": "resp_inc",
        "incomplete": True,
    }


@pytest.mark.parametrize(
    ("event", "code", "retryable"),
    [
        (
            {
                "type": "response.failed",
                "response": {
                    "id": "resp_failed",
                    "error": {"code": "server_error", "message": "private"},
                },
            },
            "provider_service_error",
            True,
        ),
        (
            {
                "type": "error",
                "code": "rate_limit_exceeded",
                "message": "private",
                "param": None,
            },
            "provider_rate_limited",
            True,
        ),
        (
            {
                "type": "error",
                "code": "invalid_prompt",
                "message": "private",
                "param": "input",
            },
            "provider_invalid_response",
            False,
        ),
    ],
)
def test_stream_failure_events_map_to_redacted_core_error(event, code, retryable):
    factory = openai_responses()
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(event),
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, request(factory), CancellationToken()
        )
    )

    assert events[-1].kind == "error"
    assert events[-1].data == {"code": code, "retryable": retryable}
    assert "private" not in repr(events[-1])


def test_legacy_stream_raises_safe_error_instead_of_treating_partial_text_as_success():
    factory = openai_responses()
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"type": "response.output_text.delta", "delta": "partial"},
                {
                    "type": "response.failed",
                    "response": {
                        "id": "resp_failed",
                        "error": {"code": "server_error", "message": "private"},
                    },
                },
            ),
        ),
    )
    stream = provider.stream(
        {"text": "input"}, request(factory), CancellationToken()
    )

    assert next(stream) == "partial"
    with pytest.raises(ResponsesProviderError) as caught:
        list(stream)
    assert caught.value.code == "provider_service_error"
    assert "private" not in repr(caught.value)


def test_responses_non_stream_output_array_is_supported():
    factory = openai_responses()
    provider = ResponsesProvider(
        factory,
        "fixture-secret",
        config(factory),
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "id": "resp_2",
                    "status": "completed",
                    "output": [{"content": [{"type": "output_text", "text": "complete"}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                },
            )
        ),
    )
    events = list(provider.stream_events({"text": "input"}, request(factory, stream=False), CancellationToken()))
    assert [event.kind for event in events] == ["request_started", "text_delta", "usage", "completed"]
    assert events[1].data["text"] == "complete"


@pytest.mark.parametrize(
    ("status", "details", "last_kind", "finish_reason"),
    [
        ("incomplete", {"reason": "max_output_tokens"}, "completed", "length"),
        ("incomplete", {"reason": "content_filter"}, "completed", "content_filter"),
        ("cancelled", None, "cancelled", None),
    ],
)
def test_non_stream_terminal_status_is_preserved(
    status, details, last_kind, finish_reason
):
    factory = openai_responses()
    body = {"id": "resp_status", "status": status, "output_text": "partial"}
    if details is not None:
        body["incomplete_details"] = details
    provider = provider_with_response(factory, httpx.Response(200, json=body))

    events = list(
        provider.stream_events(
            {"text": "input"}, request(factory, stream=False), CancellationToken()
        )
    )

    assert events[-1].kind == last_kind
    if finish_reason:
        assert events[-1].data["finish_reason"] == finish_reason
        assert events[-1].data["incomplete"] is True


def test_non_stream_failed_maps_error_and_usage():
    factory = openai_responses()
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            json={
                "id": "resp_failed",
                "status": "failed",
                "error": {"code": "server_error", "message": "private"},
                "usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1},
            },
        ),
    )

    events = list(
        provider.stream_events(
            {"text": "input"}, request(factory, stream=False), CancellationToken()
        )
    )

    assert [event.kind for event in events] == ["request_started", "usage", "error"]
    assert events[-1].data == {"code": "provider_service_error", "retryable": True}


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "provider_auth_failed", False),
        (403, "provider_auth_failed", False),
        (408, "provider_timeout", True),
        (429, "provider_rate_limited", True),
        (500, "provider_service_error", True),
        (503, "provider_service_error", True),
        (504, "provider_timeout", True),
        (529, "provider_service_error", True),
        (400, "provider_invalid_response", False),
    ],
)
def test_http_status_classification(status, code, retryable):
    factory = openai_responses()
    provider = provider_with_response(factory, httpx.Response(status))

    with pytest.raises(ResponsesProviderError) as caught:
        list(
            provider.stream_events(
                {"text": "input"}, request(factory), CancellationToken()
            )
        )

    assert caught.value.code == code
    assert caught.value.retryable is retryable


def test_cancellation_closes_blocked_response_and_emits_only_cancelled_terminal():
    factory = openai_responses()
    blocked = BlockingByteStream()
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=blocked,
        ),
    )
    token = CancellationToken()
    captured = []
    failure = []

    def consume():
        try:
            captured.extend(
                provider.stream_events({"text": "input"}, request(factory), token)
            )
        except Exception as exc:  # pragma: no cover - asserted below
            failure.append(exc)

    worker = Thread(target=consume)
    worker.start()
    assert blocked.started.wait(2.0)
    token.cancel()
    worker.join(2.0)

    assert not worker.is_alive()
    assert failure == []
    assert [event.kind for event in captured] == ["cancelled"]


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": -1},
        {"input_tokens": True},
        {"input_tokens": "1"},
    ],
)
def test_invalid_usage_is_rejected(usage):
    factory = openai_responses()
    provider = provider_with_response(
        factory,
        httpx.Response(
            200,
            json={
                "id": "resp_usage",
                "status": "completed",
                "output_text": "ok",
                "usage": usage,
            },
        ),
    )

    with pytest.raises(ResponsesProviderError) as caught:
        list(
            provider.stream_events(
                {"text": "input"},
                request(factory, stream=False),
                CancellationToken(),
            )
        )
    assert caught.value.code == "provider_invalid_response"
