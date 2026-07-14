import time

import pytest

from reflex_core import CancellationToken
from reflex_runtime.plugin_limits import PluginCallBudget, PluginLimitExceeded


def test_plugin_budget_cancels_token_after_deadline():
    token = CancellationToken()
    budget = PluginCallBudget(token, timeout_seconds=0.02)

    try:
        assert token.wait(timeout=1)
        with pytest.raises(PluginLimitExceeded, match="plugin_timeout") as raised:
            budget.check()
        assert raised.value.code == "plugin_timeout"
    finally:
        budget.close()


def test_plugin_budget_rejects_event_count_overflow():
    budget = PluginCallBudget(CancellationToken(), timeout_seconds=1, max_events=2)

    try:
        budget.account_event({"index": 1})
        budget.account_event({"index": 2})
        with pytest.raises(PluginLimitExceeded) as raised:
            budget.account_event({"index": 3})
        assert raised.value.code == "plugin_event_limit"
    finally:
        budget.close()


def test_plugin_budget_counts_utf8_serialized_bytes():
    budget = PluginCallBudget(
        CancellationToken(), timeout_seconds=1, max_output_bytes=14
    )

    try:
        budget.account_event({"text": "中"})
        with pytest.raises(PluginLimitExceeded) as raised:
            budget.account_event({"text": "a"})
        assert raised.value.code == "plugin_output_too_large"
    finally:
        budget.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"timeout_seconds": 0}, "plugin timeout"),
        ({"max_events": 0}, "plugin event"),
        ({"max_output_bytes": 0}, "plugin output"),
    ],
)
def test_plugin_budget_rejects_invalid_configuration(kwargs, message):
    with pytest.raises(ValueError, match=message):
        PluginCallBudget(CancellationToken(), **kwargs)


def test_plugin_budget_close_does_not_cancel_a_completed_call():
    token = CancellationToken()
    budget = PluginCallBudget(token, timeout_seconds=0.02)
    budget.close()

    time.sleep(0.04)

    assert not token.is_cancelled
