from __future__ import annotations

import gc
import weakref
from threading import Barrier, Event, Lock, Thread

from reflex_core import CancellationToken


class Callback:
    def __init__(self, called: list[str]) -> None:
        self._called = called

    def __call__(self) -> None:
        self._called.append("called")


def test_cancel_invokes_callback_once_and_releases_its_reference():
    token = CancellationToken()
    called: list[str] = []
    callback = Callback(called)
    callback_ref = weakref.ref(callback)
    unregister = token.register(callback)

    token.cancel()
    token.cancel()
    del callback
    gc.collect()

    assert called == ["called"]
    assert callback_ref() is None
    unregister()


def test_unregister_prevents_notification_and_releases_callback():
    token = CancellationToken()
    called: list[str] = []
    callback = Callback(called)
    callback_ref = weakref.ref(callback)
    unregister = token.register(callback)

    unregister()
    unregister()
    del callback
    gc.collect()
    token.cancel()

    assert called == []
    assert callback_ref() is None


def test_callbacks_run_in_lifo_order_and_one_failure_does_not_block_cleanup():
    token = CancellationToken()
    closed: list[str] = []

    token.register(lambda: closed.append("client"))

    def close_response() -> None:
        closed.append("response")
        raise RuntimeError("private close detail")

    token.register(close_response)

    token.cancel()

    assert closed == ["response", "client"]


def test_registration_racing_with_cancel_is_not_lost_or_duplicated():
    for _ in range(100):
        token = CancellationToken()
        barrier = Barrier(2)
        called = 0
        called_lock = Lock()

        def callback() -> None:
            nonlocal called
            with called_lock:
                called += 1

        def register() -> None:
            barrier.wait()
            token.register(callback)

        thread = Thread(target=register, daemon=True)
        thread.start()
        barrier.wait()
        token.cancel()
        thread.join(timeout=1.0)

        assert not thread.is_alive()
        assert called == 1


def test_wait_is_released_immediately_by_cancel():
    token = CancellationToken()
    waiting = Event()
    finished = Event()

    def wait() -> None:
        waiting.set()
        assert token.wait(30.0) is True
        finished.set()

    thread = Thread(target=wait, daemon=True)
    thread.start()
    assert waiting.wait(1.0)

    token.cancel()

    assert finished.wait(0.5)
    thread.join(timeout=1.0)
    assert not thread.is_alive()
