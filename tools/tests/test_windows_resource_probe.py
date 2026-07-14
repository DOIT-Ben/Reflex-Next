from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "windows_resource_probe.py"
SPEC = importlib.util.spec_from_file_location("windows_resource_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
windows_resource_probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = windows_resource_probe
SPEC.loader.exec_module(windows_resource_probe)


class FakeAdapter:
    def __init__(self, result=None, failure: Exception | None = None) -> None:
        self.result = result
        self.failure = failure
        self.seen_pids: list[int] = []

    def sample(self, pid: int):
        self.seen_pids.append(pid)
        if self.failure is not None:
            raise self.failure
        return self.result


def make_sample(pid: int = 42, **overrides):
    values = {
        "pid": pid,
        "private_bytes": 100,
        "working_set_bytes": 80,
        "handle_count": 12,
        "thread_count": 3,
    }
    values.update(overrides)
    return windows_resource_probe.ProcessResourceSample(**values)


def test_sample_process_returns_all_bounded_metrics_from_injected_adapter():
    adapter = FakeAdapter(make_sample())

    sample = windows_resource_probe.sample_process(42, adapter=adapter, platform="win32")

    assert sample.to_dict() == {
        "pid": 42,
        "private_bytes": 100,
        "working_set_bytes": 80,
        "handle_count": 12,
        "thread_count": 3,
    }
    assert adapter.seen_pids == [42]


@pytest.mark.parametrize(
    "pid",
    [None, True, False, 0, -1, 1.0, "42", windows_resource_probe.MAX_WINDOWS_PID + 1],
)
def test_invalid_pid_is_rejected_with_one_fixed_safe_error(pid):
    with pytest.raises(windows_resource_probe.ResourceProbeError) as captured:
        windows_resource_probe.sample_process(pid, adapter=FakeAdapter(), platform="win32")

    assert captured.value.code == "invalid_pid"
    assert str(captured.value) == "invalid_pid"


@pytest.mark.parametrize("pid", [1, windows_resource_probe.MAX_WINDOWS_PID])
def test_pid_boundaries_are_accepted(pid):
    adapter = FakeAdapter(make_sample(pid))

    assert windows_resource_probe.sample_process(
        pid, adapter=adapter, platform="win32"
    ).pid == pid


def test_non_windows_platform_is_explicitly_unsupported_without_calling_adapter():
    adapter = FakeAdapter(make_sample())

    with pytest.raises(windows_resource_probe.ResourceProbeError) as captured:
        windows_resource_probe.sample_process(42, adapter=adapter, platform="linux")

    assert captured.value.code == "unsupported_platform"
    assert str(captured.value) == "unsupported_platform"
    assert adapter.seen_pids == []


def test_adapter_failure_is_mapped_without_leaking_sensitive_details():
    private_detail = r"C:\private\launch.exe --token secret-value"
    adapter = FakeAdapter(failure=OSError(private_detail))

    with pytest.raises(windows_resource_probe.ResourceProbeError) as captured:
        windows_resource_probe.sample_process(42, adapter=adapter, platform="win32")

    assert captured.value.code == "resource_sample_failed"
    assert str(captured.value) == "resource_sample_failed"
    assert private_detail not in repr(captured.value)
    assert captured.value.__cause__ is None


@pytest.mark.parametrize(
    "sample",
    [
        object(),
        make_sample(pid=41),
        make_sample(private_bytes=-1),
        make_sample(working_set_bytes=-1),
        make_sample(handle_count=-1),
        make_sample(thread_count=-1),
        make_sample(private_bytes=True),
    ],
)
def test_malformed_adapter_results_are_rejected_with_fixed_error(sample):
    with pytest.raises(windows_resource_probe.ResourceProbeError) as captured:
        windows_resource_probe.sample_process(
            42,
            adapter=FakeAdapter(sample),
            platform="win32",
        )

    assert captured.value.code == "resource_sample_failed"
    assert str(captured.value) == "resource_sample_failed"
