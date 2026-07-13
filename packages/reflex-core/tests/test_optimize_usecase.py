from reflex_core import (
    CancellationToken,
    EventType,
    OperationCancelled,
    OptimizeRequest,
    OptimizeUseCase,
    SceneDetectionResult,
)
from reflex_core.testing import FakeProvider, FakeSceneDetector, FakeTemplateResolver


def make_use_case(provider=None, detector=None, resolver=None):
    return OptimizeUseCase(
        scene_detector=detector or FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=resolver or FakeTemplateResolver(),
        provider=provider or FakeProvider(("hello ", "world")),
    )


def event_types(events):
    return [envelope.event.type for envelope in events]


class ManualTimer:
    def __init__(self, callback):
        self.callback = callback
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if self.started and not self.cancelled:
            self.callback()


class ManualTimerFactory:
    def __init__(self):
        self.timers = []

    def __call__(self, seconds, callback):
        assert seconds == 120.0
        timer = ManualTimer(callback)
        self.timers.append(timer)
        return timer


def test_normal_event_sequence_and_final_result():
    events = list(make_use_case().optimize(OptimizeRequest("input"), request_id="req-1"))

    assert event_types(events) == [
        EventType.STATUS,
        EventType.SCENE,
        EventType.REQUEST,
        EventType.CHUNK,
        EventType.CHUNK,
        EventType.DONE,
        EventType.METRIC,
    ]
    assert {event.request_id for event in events} == {"req-1"}
    assert events[-2].event.data["text"] == "hello world"


def test_scene_detector_failure_falls_back_to_general():
    detector = FakeSceneDetector(error=RuntimeError("detector failed"))
    events = list(make_use_case(detector=detector).optimize(OptimizeRequest("input")))
    scene = next(event.event for event in events if event.event.type is EventType.SCENE)

    assert scene.data["scene"] == "general"
    assert scene.data["method"] == "fallback"
    assert EventType.DONE in event_types(events)


def test_manual_scene_bypasses_detector_failure():
    detector = FakeSceneDetector(error=RuntimeError("must not run"))
    request = OptimizeRequest("input", scene="email", scene_policy="manual")
    events = list(make_use_case(detector=detector).optimize(request))
    scene = next(event.event for event in events if event.event.type is EventType.SCENE)

    assert scene.data["scene"] == "email"
    assert scene.data["method"] == "manual"


def test_cancel_stops_before_done_even_if_provider_ignores_cancellation():
    token = CancellationToken()

    def cancel_after_first_chunk(index, cancellation):
        if index == 1:
            cancellation.cancel()

    provider = FakeProvider(
        ("first", "late", "later"),
        on_chunk=cancel_after_first_chunk,
        ignore_cancellation=True,
    )
    events = list(
        make_use_case(provider=provider).optimize(
            OptimizeRequest("input"), request_id="cancel-me", cancellation=token
        )
    )

    assert EventType.DONE not in event_types(events)
    assert events[-1].event.type is EventType.STATUS
    assert events[-1].event.data["phase"] == "cancelled"
    chunks = [event.event.data["text"] for event in events if event.event.type is EventType.CHUNK]
    assert chunks == ["first"]
    terminal_events = [
        event
        for event in events
        if event.event.type in {EventType.DONE, EventType.ERROR}
        or event.event.data.get("phase") == "cancelled"
    ]
    assert len(terminal_events) == 1


def test_operation_cancelled_from_provider_emits_cancelled_terminal_status():
    provider = FakeProvider(error=OperationCancelled("api_key=provider-secret"))
    events = list(make_use_case(provider=provider).optimize(OptimizeRequest("input")))

    assert EventType.ERROR not in event_types(events)
    assert EventType.DONE not in event_types(events)
    assert events[-1].event.type is EventType.STATUS
    assert events[-1].event.data == {
        "phase": "cancelled",
        "message": "Generation cancelled.",
    }


def test_request_stops_at_120_second_deadline_without_emitting_late_chunk():
    now = [0.0]

    def advance_to_deadline(index, cancellation):
        del index, cancellation
        now[0] = 120.0

    provider = FakeProvider(("late",), on_chunk=advance_to_deadline)
    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=FakeTemplateResolver(),
        provider=provider,
        clock=lambda: now[0],
    )

    events = list(use_case.optimize(OptimizeRequest("input")))

    assert EventType.CHUNK not in event_types(events)
    assert EventType.DONE not in event_types(events)
    assert events[-1].event.type is EventType.ERROR
    assert events[-1].event.data == {
        "code": "request_timeout",
        "message": "Request exceeded the 120 second time limit.",
        "recoverable": True,
        "action": "retry",
    }


def test_deadline_watchdog_actively_cancels_blocked_provider_as_timeout():
    timer_factory = ManualTimerFactory()
    token = CancellationToken()
    cancellation_notified = []

    class BlockingProvider:
        id = "fixture"
        model = "fixture-model"

        def stream(self, rendered_request, request, cancellation):
            del rendered_request, request
            cancellation.register(lambda: cancellation_notified.append(True))
            timer_factory.timers[0].fire()
            cancellation.raise_if_cancelled()
            yield "late"

    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=FakeTemplateResolver(),
        provider=BlockingProvider(),
        timer_factory=timer_factory,
    )

    events = list(use_case.optimize(OptimizeRequest("input"), cancellation=token))

    assert cancellation_notified == [True]
    assert token.is_cancelled
    assert EventType.CHUNK not in event_types(events)
    assert EventType.DONE not in event_types(events)
    assert events[-1].event.data["code"] == "request_timeout"


def test_success_cancels_watchdog_before_done_and_prevents_late_expiry():
    timer_factory = ManualTimerFactory()
    token = CancellationToken()
    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=FakeTemplateResolver(),
        provider=FakeProvider(("done",)),
        timer_factory=timer_factory,
    )

    events = list(use_case.optimize(OptimizeRequest("input"), cancellation=token))
    timer_factory.timers[0].fire()

    assert EventType.DONE in event_types(events)
    assert timer_factory.timers[0].cancelled
    assert not token.is_cancelled


def test_error_terminal_closes_watchdog_before_generator_is_resumed():
    timer_factory = ManualTimerFactory()
    token = CancellationToken()
    use_case = OptimizeUseCase(
        scene_detector=FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=FakeTemplateResolver(),
        provider=FakeProvider(("unused",)),
        timer_factory=timer_factory,
    )
    stream = use_case.optimize(OptimizeRequest("   "), cancellation=token)

    terminal = next(stream)
    timer_factory.timers[0].fire()

    assert terminal.event.type is EventType.ERROR
    assert terminal.event.data["code"] == "invalid_input"
    assert timer_factory.timers[0].cancelled
    assert not token.is_cancelled
    stream.close()


def test_stream_output_exceeding_utf8_byte_limit_is_nonrecoverable_error():
    three_byte_character = "\u754c"
    within_limit = three_byte_character * 699_050 + "ab"
    provider = FakeProvider((within_limit, three_byte_character))
    events = list(make_use_case(provider=provider).optimize(OptimizeRequest("input")))

    chunks = [event for event in events if event.event.type is EventType.CHUNK]
    assert len(chunks) == 1
    assert EventType.DONE not in event_types(events)
    assert events[-1].event.type is EventType.ERROR
    assert events[-1].event.data == {
        "code": "output_too_large",
        "message": "Provider output exceeded the allowed limit.",
        "recoverable": False,
        "action": None,
    }


def test_stream_output_exceeding_valid_chunk_limit_is_nonrecoverable_error():
    provider = FakeProvider(("\x00",) * 5 + ("x",) * 50_001)
    events = list(make_use_case(provider=provider).optimize(OptimizeRequest("input")))

    chunks = [event for event in events if event.event.type is EventType.CHUNK]
    assert len(chunks) == 50_000
    assert EventType.DONE not in event_types(events)
    assert events[-1].event.type is EventType.ERROR
    assert events[-1].event.data == {
        "code": "output_too_large",
        "message": "Provider output exceeded the allowed limit.",
        "recoverable": False,
        "action": None,
    }


def test_provider_error_is_safe_and_has_no_secret():
    provider = FakeProvider(error=RuntimeError("api_key=very-secret"))
    events = list(make_use_case(provider=provider).optimize(OptimizeRequest("input")))
    error = events[-1].event

    assert error.type is EventType.ERROR
    assert error.data["code"] == "provider_error"
    assert "very-secret" not in error.data["message"]
    assert EventType.DONE not in event_types(events)


def test_empty_provider_result_is_recoverable_error():
    events = list(make_use_case(provider=FakeProvider(())).optimize(OptimizeRequest("input")))
    assert events[-1].event.type is EventType.ERROR
    assert events[-1].event.data["code"] == "empty_result"


def test_template_error_happens_before_provider_request_and_is_safe():
    resolver = FakeTemplateResolver(error=RuntimeError("api_key=template-secret"))
    events = list(make_use_case(resolver=resolver).optimize(OptimizeRequest("input")))

    assert event_types(events) == [EventType.STATUS, EventType.SCENE, EventType.ERROR]
    assert events[-1].event.data["code"] == "template_render_error"
    assert "template-secret" not in events[-1].event.data["message"]
