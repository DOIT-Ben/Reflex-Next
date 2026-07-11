from __future__ import annotations

from collections.abc import Mapping

import pytest

from reflex_core import CancellationToken, OperationCancelled
from reflex_translator import TranslatorPluginError, plugin


class GatewayServices(Mapping[str, object]):
    def __init__(self, gateway) -> None:
        self.gateway = gateway
        self.accessed: list[str] = []

    def __getitem__(self, key: str) -> object:
        self.accessed.append(key)
        if key != "provider_gateway":
            raise AssertionError(f"unexpected service access: {key}")
        return self.gateway

    def __iter__(self):
        return iter(("provider_gateway",))

    def __len__(self) -> int:
        return 1


def invoke(payload, gateway):
    services = GatewayServices(gateway)
    events = list(plugin().invoke("translate", payload, services, CancellationToken()))
    return events, services


def test_auto_direction_translates_detected_chinese_to_english_and_cleans_chunks() -> None:
    observed: dict[str, object] = {}

    def gateway(rendered, text, cancellation):
        observed.update(rendered=rendered, text=text, cancellation=cancellation)
        yield "Hello\x00\r\n"
        yield "world"

    events, services = invoke({"text": "  你好，世界  ", "target": "auto"}, gateway)

    assert events == [
        {"status": "chunk", "data": {"text": "Hello\n"}},
        {"status": "chunk", "data": {"text": "world"}},
        {
            "status": "result",
            "data": {
                "text": "Hello\nworld",
                "source_language": "zh",
                "target_language": "en",
            },
        },
    ]
    assert observed["text"] == "你好，世界"
    assert observed["rendered"] == {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Translate the user text into English. Preserve meaning, tone, paragraph "
                    "breaks, lists, and code. Return only the translation without explanations."
                ),
            },
            {"role": "user", "content": "你好，世界"},
        ]
    }
    assert services.accessed == ["provider_gateway"]


def test_auto_direction_uses_only_the_first_100_characters_for_chinese_detection() -> None:
    def gateway(_rendered, _text, _cancellation):
        yield "译文"

    events, _ = invoke({"text": "a" * 100 + "中", "target": "auto"}, gateway)

    assert events[-1]["data"]["source_language"] == "en"
    assert events[-1]["data"]["target_language"] == "zh"


@pytest.mark.parametrize(
    ("target", "expected_target", "target_name"),
    [("zh", "zh", "Chinese"), ("en", "en", "English")],
)
def test_explicit_target_language_is_honored(target, expected_target, target_name) -> None:
    observed = {}

    def gateway(rendered, _text, _cancellation):
        observed["system"] = rendered["messages"][0]["content"]
        yield "done"

    events, _ = invoke({"text": "source", "target": target}, gateway)

    assert events[-1]["data"]["target_language"] == expected_target
    assert f"into {target_name}" in observed["system"]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "", "target": "auto"},
        {"text": "   ", "target": "auto"},
        {"text": "text", "target": "fr"},
        {"text": "text"},
        {"text": "text", "target": "auto", "provider": "minimax"},
    ],
)
def test_invalid_translation_payload_is_rejected(payload) -> None:
    with pytest.raises(TranslatorPluginError) as caught:
        list(plugin().invoke("translate", payload, {}, CancellationToken()))

    assert caught.value.code == "translation_payload_invalid"


def test_missing_provider_gateway_is_a_fixed_service_error() -> None:
    with pytest.raises(TranslatorPluginError) as caught:
        list(
            plugin().invoke(
                "translate",
                {"text": "source", "target": "auto"},
                {},
                CancellationToken(),
            )
        )

    assert caught.value.code == "translation_service_unavailable"


def test_empty_provider_response_is_rejected() -> None:
    def gateway(_rendered, _text, _cancellation):
        return iter(("\x00", "\r"))

    with pytest.raises(TranslatorPluginError) as caught:
        invoke({"text": "source", "target": "auto"}, gateway)

    assert caught.value.code == "provider_empty_response"


def test_cancellation_after_a_chunk_emits_no_result() -> None:
    cancellation = CancellationToken()

    def gateway(_rendered, _text, _cancellation):
        yield "first"
        yield "second"

    stream = plugin().invoke(
        "translate",
        {"text": "source", "target": "auto"},
        {"provider_gateway": gateway},
        cancellation,
    )

    assert next(stream) == {"status": "chunk", "data": {"text": "first"}}
    cancellation.cancel()
    with pytest.raises(OperationCancelled):
        next(stream)


def test_gateway_safe_error_code_is_preserved_without_exposing_its_message() -> None:
    class SafeProviderError(RuntimeError):
        code = "provider_auth_failed"

    def gateway(_rendered, _text, _cancellation):
        raise SafeProviderError("api_key=private-value")
        yield

    with pytest.raises(SafeProviderError) as caught:
        invoke({"text": "source", "target": "auto"}, gateway)

    assert caught.value.code == "provider_auth_failed"
    assert "private-value" not in repr(plugin())
