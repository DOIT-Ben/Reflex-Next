from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock, Thread

import pytest

from reflex_runtime.task_registry import (
    BoundedTaskScheduler,
    DuplicateRequestId,
    TaskCapacityExceeded,
    TaskRegistry,
    TaskSchedulerClosed,
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


def test_bounded_scheduler_runs_four_tasks_and_queues_thirty_two_without_more_threads():
    registry = TaskRegistry()
    scheduler = BoundedTaskScheduler(registry, max_workers=4, max_queue=32)
    release = Event()
    four_active = Event()
    active = 0
    lock = Lock()

    def run(_token):
        nonlocal active
        with lock:
            active += 1
            if active == 4:
                four_active.set()
        release.wait(timeout=2)

    try:
        for index in range(36):
            scheduler.submit(f"task-{index}", run, on_cancel=lambda: None)
        assert four_active.wait(timeout=1)
        assert scheduler.worker_count == 4
        with pytest.raises(TaskCapacityExceeded):
            scheduler.submit("overflow", run, on_cancel=lambda: None)
    finally:
        release.set()
        scheduler.close(timeout=2)


def test_bounded_scheduler_is_fifo_and_waiting_task_can_be_cancelled():
    registry = TaskRegistry()
    scheduler = BoundedTaskScheduler(registry, max_workers=1, max_queue=3)
    release = Event()
    started = Event()
    order = []
    cancelled = []

    def first(_token):
        started.set()
        release.wait(timeout=2)
        order.append("first")

    try:
        scheduler.submit("first", first, on_cancel=lambda: None)
        assert started.wait(timeout=1)
        scheduler.submit(
            "second", lambda _token: order.append("second"), on_cancel=lambda: None
        )
        scheduler.submit(
            "cancelled",
            lambda _token: order.append("cancelled"),
            on_cancel=lambda: cancelled.append("cancelled"),
        )
        scheduler.submit(
            "third", lambda _token: order.append("third"), on_cancel=lambda: None
        )

        assert scheduler.cancel("cancelled") is True
        assert not registry.is_active("cancelled")
        release.set()
        deadline = time.monotonic() + 2
        while registry.has_tasks() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert order == ["first", "second", "third"]
        assert cancelled == ["cancelled"]
    finally:
        release.set()
        scheduler.close(timeout=2)


def test_bounded_scheduler_close_leaves_no_worker_threads():
    registry = TaskRegistry()
    scheduler = BoundedTaskScheduler(registry, max_workers=2, max_queue=2)
    release = Event()
    scheduler.submit(
        "running", lambda token: release.wait(timeout=0.1), on_cancel=lambda: None
    )
    scheduler.close(timeout=2)

    assert not registry.has_tasks()
    assert scheduler.live_worker_count == 0


def test_bounded_scheduler_close_atomically_rejects_inflight_submit():
    registering = Event()
    continue_register = Event()
    ran = Event()

    class BlockingRegistry(TaskRegistry):
        def register(self, request_id, *, enforce_capacity=True):
            token = super().register(request_id, enforce_capacity=enforce_capacity)
            registering.set()
            continue_register.wait(timeout=2)
            return token

    registry = BlockingRegistry()
    scheduler = BoundedTaskScheduler(registry, max_workers=1, max_queue=1)
    errors = []
    submitter = Thread(
        target=lambda: _capture_exception(
            errors,
            lambda: scheduler.submit("raced", lambda _token: ran.set(), on_cancel=lambda: None),
        )
    )
    submitter.start()
    assert registering.wait(timeout=1)

    scheduler.close(timeout=1)
    continue_register.set()
    submitter.join(timeout=1)

    assert len(errors) == 1
    assert isinstance(errors[0], TaskSchedulerClosed)
    assert not registry.has_tasks()
    assert not ran.is_set()


def test_task_and_cancel_callback_failures_do_not_kill_worker_or_skip_cleanup():
    registry = TaskRegistry()
    scheduler = BoundedTaskScheduler(registry, max_workers=1, max_queue=3)
    release = Event()
    first_started = Event()
    second_ran = Event()
    cancellation_observed = Event()

    def blocking(_token):
        first_started.set()
        release.wait(timeout=2)

    try:
        scheduler.submit("blocking", blocking, on_cancel=lambda: None)
        assert first_started.wait(timeout=1)
        scheduler.submit(
            "bad-cancel",
            lambda _token: None,
            on_cancel=lambda: (_ for _ in ()).throw(RuntimeError("cancel failure")),
        )
        scheduler.submit(
            "good-cancel",
            lambda _token: None,
            on_cancel=lambda: cancellation_observed.set(),
        )
        scheduler.cancel_all()
        assert cancellation_observed.wait(timeout=1)

        release.set()
        deadline = time.monotonic() + 1
        while registry.has_tasks() and time.monotonic() < deadline:
            time.sleep(0.01)
        scheduler.submit(
            "bad-run",
            lambda _token: (_ for _ in ()).throw(RuntimeError("run failure")),
            on_cancel=lambda: None,
        )
        scheduler.submit("after-failure", lambda _token: second_ran.set(), on_cancel=lambda: None)
        assert second_ran.wait(timeout=1)
    finally:
        release.set()
        scheduler.close(timeout=2)

    assert not registry.has_tasks()
    assert scheduler.live_worker_count == 0


def test_partial_worker_start_failure_is_joinable_and_leaves_no_worker():
    registry = TaskRegistry()
    created = 0

    def partially_failing_factory(**kwargs):
        nonlocal created
        created += 1
        if created == 2:
            raise RuntimeError("worker start fixture failure")
        return Thread(**kwargs)

    scheduler = BoundedTaskScheduler(
        registry,
        max_workers=2,
        max_queue=1,
        thread_factory=partially_failing_factory,
    )

    with pytest.raises(RuntimeError, match="worker start fixture failure"):
        scheduler.submit("never-accepted", lambda _token: None, on_cancel=lambda: None)
    scheduler.close(timeout=2)

    assert not registry.has_tasks()
    assert scheduler.worker_count == 1
    assert scheduler.live_worker_count == 0


def _capture_exception(errors, operation):
    try:
        operation()
    except BaseException as error:
        errors.append(error)
