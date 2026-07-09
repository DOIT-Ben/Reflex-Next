import pytest

from reflex_core import Event, EventEnvelope, EventType, PROTOCOL_VERSION


def test_event_envelope_serializes_stable_protocol_fields():
    envelope = EventEnvelope("req-1", Event(EventType.CHUNK, {"text": "hello"}))

    assert envelope.to_dict() == {
        "version": PROTOCOL_VERSION,
        "request_id": "req-1",
        "event": {"type": "chunk", "data": {"text": "hello"}},
    }


def test_event_envelope_rejects_wrong_protocol_version():
    with pytest.raises(ValueError):
        EventEnvelope("req-1", Event(EventType.CHUNK), version=999)
