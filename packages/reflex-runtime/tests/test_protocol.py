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


def test_parse_private_provider_configuration_command():
    command = parse_command(
        {
            "version": 1,
            "request_id": "host-config-minimax",
            "type": "configure_provider",
            "payload": {
                "provider_id": "minimax",
                "secret": "fixture-private-credential",
                "config": {"model": "MiniMax-M2.7-highspeed"},
            },
        }
    )

    assert command.type == "configure_provider"
    assert command.payload["provider_id"] == "minimax"


@pytest.mark.parametrize(
    "payload",
    [
        {"provider_id": "../minimax", "secret": "fixture-secret", "config": {}},
        {"provider_id": "minimax", "secret": "", "config": {}},
        {"provider_id": "minimax", "secret": "fixture-secret", "config": []},
        {
            "provider_id": "minimax",
            "secret": "fixture-secret",
            "config": {},
            "unexpected": True,
        },
    ],
)
def test_private_provider_configuration_rejects_unsafe_payloads_without_echo(payload):
    with pytest.raises(ProtocolError) as caught:
        parse_command(
            {
                "version": 1,
                "request_id": "host-config-minimax",
                "type": "configure_provider",
                "payload": payload,
            }
        )

    assert str(caught.value) == "invalid provider configuration command"
    assert "fixture-secret" not in str(caught.value)

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
