from reflex_core import CancellationToken, EventType, OptimizeRequest, OptimizeUseCase, SceneDetectionResult
from reflex_core.testing import FakeProvider, FakeSceneDetector, FakeTemplateResolver


def make_use_case(provider=None, detector=None):
    return OptimizeUseCase(
        scene_detector=detector or FakeSceneDetector(
            SceneDetectionResult("report_writing", 0.9, "fake")
        ),
        template_resolver=FakeTemplateResolver(),
        provider=provider or FakeProvider(("hello ", "world")),
    )


def event_types(events):
    return [envelope.event.type for envelope in events]


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
