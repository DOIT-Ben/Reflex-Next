import pytest

from reflex_runtime.protocol import CommandEnvelope, ProtocolError, parse_command


def test_parse_valid_optimize_command():
    command = parse_command(
        {
            "version": 1,
            "request_id": "req-1",
            "type": "optimize",
            "payload": {"text": "写一封邮件"},
        }
    )

    assert command == CommandEnvelope(
        version=1,
        request_id="req-1",
        type="optimize",
        payload={"text": "写一封邮件"},
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "request_id": "req-1", "type": "ping", "payload": {}},
        {"version": 1, "request_id": "", "type": "ping", "payload": {}},
        {"version": 1, "request_id": "req-1", "type": "unknown", "payload": {}},
        {"version": 1, "request_id": "req-1", "type": "ping", "payload": []},
    ],
)
def test_parse_rejects_invalid_command_envelopes(payload):
    with pytest.raises(ProtocolError):
        parse_command(payload)
