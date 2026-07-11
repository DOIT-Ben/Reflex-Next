from types import SimpleNamespace

import httpx
import pytest

from reflex_core import CancellationToken, OptimizeRequest
from reflex_provider_openai_compatible import deepseek, qwen, siliconflow, zhipu
from reflex_provider_openai_compatible.provider import CompatibleProvider, MiniMaxProviderError

FACTORIES = (deepseek, qwen, zhipu, siliconflow)

@pytest.mark.parametrize("build", FACTORIES)
def test_factory_has_a_fixed_safe_contract(build):
    provider = build()
    assert provider.id in {"deepseek", "qwen", "zhipu", "siliconflow"}
    assert provider.default_model in provider.models
    assert provider.default_base_url.startswith("https://")

def test_streams_openai_sse_and_does_not_leak_secret():
    factory = deepseek()
    config = SimpleNamespace(model=factory.default_model, base_url=factory.default_base_url, timeout_seconds=10.0, ca_bundle_path=None)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'))
    provider = CompatibleProvider(factory, "fixture-private-key", config, transport=transport)
    request = OptimizeRequest(text="x", provider="deepseek", model=factory.default_model)
    assert list(provider.stream({"text": "x"}, request, CancellationToken())) == ["ok"]
    assert "fixture-private-key" not in repr(provider)
    assert factory.id == "deepseek"

def test_rejects_unapproved_model_before_network():
    factory = qwen()
    config = SimpleNamespace(model="unsafe", base_url=factory.default_base_url, timeout_seconds=10.0, ca_bundle_path=None)
    with pytest.raises(MiniMaxProviderError):
        CompatibleProvider(factory, "fixture-private-key", config)
