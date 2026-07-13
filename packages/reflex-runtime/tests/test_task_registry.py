from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from reflex_runtime.task_registry import (
    DuplicateRequestId,
    TaskCapacityExceeded,
    TaskRegistry,
)


def test_duplicate_active_request_id_is_rejected():
    registry = TaskRegistry()
    registry.register("same-id")

    with pytest.raises(DuplicateRequestId):
        registry.register("same-id")


def test_cancellation_token_only_cancels_its_own_request():
    registry = TaskRegistry()
    first = registry.register("first")
    second = registry.register("second")

    assert registry.cancel("first") is True
    assert first.is_cancelled is True
    assert second.is_cancelled is False


def test_task_scope_cleans_up_after_success_and_exception():
    registry = TaskRegistry()

    with registry.task("success"):
        assert registry.is_active("success")
    assert not registry.is_active("success")

    with pytest.raises(RuntimeError):
        with registry.task("failure"):
            raise RuntimeError("fixture failure")
    assert not registry.is_active("failure")


def test_cancel_all_cancels_every_active_task_and_cleanup_is_identity_safe():
    registry = TaskRegistry()
    first = registry.register("first")
    second = registry.register("second")

    registry.cancel_all()
    registry.cleanup("first", second)

    assert first.is_cancelled
    assert second.is_cancelled
    assert registry.is_active("first")
    registry.cleanup("first", first)
    assert not registry.is_active("first")


def test_concurrent_registration_allows_exactly_one_owner():
    registry = TaskRegistry()

    def register_once():
        try:
            return registry.register("raced")
        except DuplicateRequestId:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: register_once(), range(2)))

    assert sum(result is not None for result in results) == 1


def test_registration_capacity_is_bounded_and_reusable_after_cleanup():
    registry = TaskRegistry(max_tasks=2)
    first = registry.register("first")
    registry.register("second")

    with pytest.raises(DuplicateRequestId):
        registry.register("first")
    with pytest.raises(TaskCapacityExceeded) as caught:
        registry.register("private-input-must-not-leak")

    assert caught.value.code == "runtime_busy"
    assert str(caught.value) == "runtime_busy"

    registry.cleanup("first", first)
    registry.register("replacement")
    assert registry.is_active("replacement")
